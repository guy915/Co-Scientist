from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import credentials, engine_tasks, store
from app.config import settings
from app.main import app
from tests._llm_fake_backend import install_completion_backend

_SECRET = "byok-flow-secret"
_KEY = "sk-flow-abcdef123456"
_HEADERS = {
    "X-LLM-API-Key": _KEY,
    "X-LLM-Provider": "deepseek",
    "X-Client-ID": "byok-flow-scientist",
}


@pytest.fixture
def byok_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "byok_encryption_key", _SECRET)


@pytest.fixture(autouse=True)
def _no_background_title_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Disable background titling so credential-flow tests cannot reach the
    # network.

    async def _no_title(goal: str) -> None:
        return None

    monkeypatch.setattr("app.runs.crud.generate_run_title", _no_title)


def _node_task(run_id: str) -> store.ScientificTask:
    return store.ScientificTask(
        id="task-1",
        run_id=run_id,
        task_type="engine.node.generate",
        status="leased",
        priority=90,
        inputs={},
        dependencies=(),
        provenance={},
        idempotency_key="engine.node.generate:0",
        budget={},
        attempt=1,
        max_attempts=3,
        lease_owner="test",
        lease_expires_at=None,
        result=None,
        error=None,
        created_at=0.0,
        updated_at=0.0,
        started_at=None,
        completed_at=None,
    )


def _fake_validation(
    monkeypatch: pytest.MonkeyPatch, *, fail_auth: bool = False
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.clear()
        captured.update(kwargs)
        if fail_auth:
            from litellm.exceptions import AuthenticationError

            raise AuthenticationError(
                "Invalid Authentication",
                llm_provider="deepseek",
                model=str(kwargs.get("model")),
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    monkeypatch.setattr(credentials, "_acompletion", fake_acompletion)
    return captured


def _create_byok_run(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/runs",
        json={"research_goal": "BYOK goal"},
        headers=_HEADERS,
    )
    assert response.status_code == 200, response.text
    created: dict[str, Any] = response.json()
    return created


def test_rejected_key_fails_creation_before_any_run(
    byok_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_validation(monkeypatch, fail_auth=True)
    with TestClient(app) as client:
        response = client.post(
            "/api/runs",
            json={"research_goal": "doomed goal"},
            headers=_HEADERS,
        )
        assert response.status_code == 400
        assert "rejected" in response.json()["detail"]
        assert _KEY not in response.text
        assert client.get("/api/runs").json()["runs"] == []


def test_key_without_provider_is_a_400(
    byok_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_validation(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/runs",
            json={"research_goal": "goal"},
            headers={"X-LLM-API-Key": _KEY},
        )
        assert response.status_code == 400


def test_byok_disabled_deployment_refuses_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "byok_encryption_key", "")
    _fake_validation(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/runs",
            json={"research_goal": "goal"},
            headers=_HEADERS,
        )
        assert response.status_code == 503


def test_byok_run_is_real_backed_and_stores_the_credential(
    byok_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _fake_validation(monkeypatch)
    with TestClient(app) as client:
        run = _create_byok_run(client)

    assert captured["api_key"] == _KEY
    assert captured["model"] == "deepseek/deepseek-v4-flash"
    assert _KEY not in json.dumps(run)
    row = store.get_run(run["id"])
    assert row is not None
    assert row.llm_backend == "real"
    assert row.config.get("byok_provider") == "deepseek"
    assert _KEY not in json.dumps(row.config)

    from app.engine_adapter import (
        resolve_offline_backend,
        sync_engine_llm_backend,
    )
    from app.run_modes import resolved_run_config

    cfg = resolved_run_config(row.config)
    assert cfg.get("byok_provider") == "deepseek"
    assert resolve_offline_backend(cfg) is False
    sync_engine_llm_backend(run["id"], cfg, None)
    refreshed = store.get_run(run["id"])
    assert refreshed is not None
    assert refreshed.llm_backend == "real"

    stored = credentials.get_run_credential(run["id"])
    assert stored is not None
    assert stored.api_key == _KEY
    assert stored.provider == "deepseek"
    assert stored.model == "deepseek/deepseek-v4-flash"


def test_generator_for_a_byok_run_uses_the_runs_key(
    byok_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.engine_tasks.support import _generator_and_opts

    _fake_validation(monkeypatch)
    with TestClient(app) as client:
        run = _create_byok_run(client)

    task = _node_task(run["id"])
    generator, _opts = _generator_and_opts(task, None)
    assert generator.model_name == "deepseek/deepseek-v4-flash"
    assert generator.supervisor_model_name == "deepseek/deepseek-v4-flash"
    assert generator.api_key == _KEY
    # BYOK calls must not share cached replies; credentials are not cache keys.
    assert generator.enable_cache is False


async def test_execute_engine_task_scopes_the_credential(
    byok_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from co_scientist.llm import current_api_key

    _fake_validation(monkeypatch)
    with TestClient(app) as client:
        run = _create_byok_run(client)

    seen: dict[str, Any] = {}

    async def fake_node_task(
        task: Any, *, db_path: str | None = None
    ) -> dict[str, Any]:
        seen["engine_key"] = current_api_key()
        seen["app_credential"] = credentials.current_byok()
        return {"status": "completed"}

    monkeypatch.setattr(engine_tasks, "execute_node_task", fake_node_task)
    await engine_tasks.execute_engine_task(_node_task(run["id"]))
    assert seen["engine_key"] == _KEY
    assert seen["app_credential"] is not None
    assert seen["app_credential"].api_key == _KEY
    assert current_api_key() is None
    assert credentials.current_byok() is None


async def test_byok_key_absent_from_serialized_checkpoint(
    byok_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from co_scientist.checkpoint import serialize_workflow_state

    from app.engine_tasks.support import _generator_and_opts

    _fake_validation(monkeypatch)
    with TestClient(app) as client:
        run = _create_byok_run(client)

    task = _node_task(run["id"])
    generator, opts = _generator_and_opts(task, None)
    state = await generator.prepare_task_state(
        "BYOK goal", opts=opts, run_id=run["id"]
    )
    envelope = serialize_workflow_state(state, last_event_seq=0)
    from app.store.checkpoints import NewCheckpoint, save_checkpoint

    save_checkpoint(
        run["id"],
        NewCheckpoint(
            stage="test", schema_version=1, last_event_seq=0, state=envelope
        ),
    )
    checkpoint = store.get_latest_checkpoint(run["id"])
    assert checkpoint is not None
    blob = json.dumps(checkpoint["state"])
    assert _KEY not in blob


def test_diagnostics_never_report_key_material(
    byok_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_validation(monkeypatch)
    with TestClient(app) as client:
        _create_byok_run(client)
        status = client.get("/status")
        config = client.get("/config")
    with TestClient(app, client=("127.0.0.1", 50000)) as operator:
        operator_status = operator.get("/status")

    assert status.status_code == 200
    assert operator_status.json()["byok_enabled"] is True
    assert status.json()["byok_enabled"] is None
    for response in (status, config, operator_status):
        assert _KEY not in response.text
        assert _SECRET not in response.text


def _byok_qa_stream(**kwargs: Any) -> Any:
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="the answer", reasoning=None)
            )
        ]
    )

    class _Stream:
        def __init__(self) -> None:
            self.kwargs = kwargs

        def __aiter__(self) -> _Stream:
            self._sent = False
            return self

        async def __anext__(self) -> Any:
            if self._sent:
                raise StopAsyncIteration
            self._sent = True
            return chunk

    return _Stream()


def test_qa_answers_with_the_runs_stored_key(
    byok_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _byok_qa_stream(**kwargs)

    _fake_validation(monkeypatch)
    install_completion_backend(monkeypatch, fake_acompletion)
    with TestClient(app) as client:
        run = _create_byok_run(client)
        captured.clear()
        response = client.post(
            f"/api/runs/{run['id']}/messages/ask",
            headers=_HEADERS,
            json={"question": "what did you find?"},
        )
    assert response.status_code == 200
    assert captured["api_key"] == _KEY
    assert captured["model"] == "deepseek/deepseek-v4-flash"


def test_interview_turn_scopes_the_header_credential(
    byok_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_stream(interview: dict[str, Any], on_reasoning: Any) -> str:
        seen["credential"] = credentials.current_byok()
        return (
            '{"assistant_message": "ready", "research_challenge": "g",'
            ' "focus_area": [], "preferences": [], "completed": true}'
        )

    monkeypatch.setattr(
        "app.interviews.model._stream_interview_content", fake_stream
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/interviews",
            json={"research_challenge": "challenge"},
            headers=_HEADERS,
        )
    assert response.status_code == 200, response.text
    credential = seen["credential"]
    assert credential is not None
    assert credential.api_key == _KEY
    assert credential.provider == "deepseek"

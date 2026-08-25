"""Creating a computational-discovery run over the API.

Before this, `config["discovery"]` could only be written straight into
the store, which meant the whole discovery product -- sandbox, proposal
agent, archive, report -- was complete and unreachable from outside
Python. Two rules are pinned here. The spec has to survive run creation
verbatim, because the override path coerces unknown keys to numbers and
would drop a dict without a word. And a malformed spec has to fail the
request, because every later read of it raises: deferred, it becomes
hundreds of identically-failing evaluations instead of one 422.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests._client import make_client as _client
from tests._store_helpers import _existing_report, _existing_run


def _spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "objective": {"metric": "score", "direction": "maximize"},
        "stages": [
            {
                "name": "run",
                "argv": [sys.executable, "main.py"],
                "timeout_seconds": 60,
            }
        ],
        "seed_source": {"main.py": "print('hi')\n"},
    }
    spec.update(overrides)
    return spec


@pytest.fixture
def client(isolated_db: str) -> Any:
    with _client() as client:
        yield client


def test_a_discovery_spec_survives_run_creation(client: TestClient) -> None:
    created = client.post(
        "/api/runs",
        json={"research_goal": "beat the baseline", "discovery": _spec()},
    )
    assert created.status_code == 200
    run = client.get(f"/api/runs/{created.json()['id']}").json()
    assert run["config"]["discovery"] == _spec()


def test_a_run_without_one_is_untouched(client: TestClient) -> None:
    created = client.post("/api/runs", json={"research_goal": "cure things"})
    run = client.get(f"/api/runs/{created.json()['id']}").json()
    assert "discovery" not in run["config"]


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ({"objective": {"metric": "score"}}, "no stages"),
        (_spec(stages=[]), "empty stages"),
        (
            _spec(objective={"metric": "s", "direction": "sideways"}),
            "direction",
        ),
        (_spec(seed_source={}), "no seed"),
        (_spec(grid={"strategy": "invented"}), "unknown strategy"),
        (
            _spec(
                grid={"strategy": "fixed"},
                descriptors=[{"feature": "ast_shape", "bins": [0.5]}],
            ),
            "a vector axis a fixed grid can never bin",
        ),
    ],
)
def test_a_malformed_spec_is_refused_at_creation(
    client: TestClient, spec: dict[str, Any], reason: str
) -> None:
    created = client.post(
        "/api/runs",
        json={"research_goal": "beat the baseline", "discovery": spec},
    )
    assert created.status_code == 422, reason
    assert "discovery spec" in created.json()["detail"]


async def _drain(run_id: str, limit: int = 60) -> None:
    """Starts the run and drains its queue until nothing is claimable."""
    from app import engine_tasks, store

    engine_tasks.enqueue_bootstrap(run_id)
    for _ in range(limit):
        task = store.claim_task("test-worker", run_id=run_id)
        if task is None:
            return
        result: dict[str, Any] = {"skipped": True}
        if task.task_type.startswith("engine."):
            result = await engine_tasks.execute_engine_task(task)
        store.complete_task(task.id, "test-worker", result)
    raise AssertionError("discovery loop did not settle")


@pytest.mark.asyncio
async def test_an_api_created_run_reaches_the_discovery_loop(
    client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The point of the endpoint. Asserting the config key alone would
    # pass even if bootstrap ignored it and ran the hypothesis graph.
    from app import store

    monkeypatch.setenv("COSCIENTIST_WORKSPACE_DIR", str(tmp_path / "ws"))
    created = client.post(
        "/api/runs",
        json={
            "research_goal": "beat the baseline",
            "discovery": _spec(max_generations=1),
        },
    ).json()
    await _drain(created["id"])

    variants = store.list_code_variants(created["id"])
    assert [v["source"] for v in variants] == [_spec()["seed_source"]]
    assert _existing_run(created["id"]).status == "completed"
    assert (
        _existing_report(created["id"])["payload"]["report_kind"] == "discovery"
    )


@pytest.mark.asyncio
async def test_a_run_inherits_the_archive_of_an_earlier_one(
    client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nothing carried across runs before this: a program found yesterday
    # was not available as a starting point today.
    from app import store

    monkeypatch.setenv("COSCIENTIST_WORKSPACE_DIR", str(tmp_path / "ws"))
    scoring = dict(
        _spec(max_generations=1),
        seed_source={
            "main.py": (
                "import json\n"
                "json.dump({'score': 4.0}, open('metrics.json', 'w'))\n"
            )
        },
    )
    first = client.post(
        "/api/runs",
        json={"research_goal": "first pass", "discovery": scoring},
    ).json()
    await _drain(first["id"])

    second = client.post(
        "/api/runs",
        json={
            "research_goal": "carry on",
            "discovery": dict(scoring, seed_from_run=first["id"]),
        },
    ).json()
    await _drain(second["id"])

    carried = store.list_code_variants(second["id"])
    assert (
        carried[0]["source"]
        == store.list_code_variants(first["id"])[0]["source"]
    )
    assert "Carried forward" in carried[0]["rationale"]


def test_inheriting_from_another_client_s_run_is_refused(
    client: TestClient,
) -> None:
    # It reads the other run's whole source out of the store, below the
    # ownership middleware that guards every HTTP path to it.
    theirs = client.post(
        "/api/runs",
        headers={"X-Client-ID": "someone-else"},
        json={"research_goal": "theirs", "discovery": _spec()},
    ).json()
    refused = client.post(
        "/api/runs",
        json={
            "research_goal": "mine",
            "discovery": dict(_spec(), seed_from_run=theirs["id"]),
        },
    )
    assert refused.status_code == 404


def test_a_seed_reference_that_is_not_a_run_id_is_refused(
    client: TestClient,
) -> None:
    refused = client.post(
        "/api/runs",
        json={
            "research_goal": "mine",
            "discovery": dict(_spec(), seed_from_run=42),
        },
    )
    assert refused.status_code == 422


class TestUnconfinableHost:
    """A host with no confinement primitive, e.g. a pre-5.13 kernel.

    Every variant is unrunnable there, and neither half of that is the
    run's fault, so both halves have to say so rather than looking like
    a program that will not compile.
    """

    def test_creation_is_refused_rather_than_accepted_and_doomed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 503, not 422: nothing in the spec is wrong and there is
        # nothing for the caller to edit.
        monkeypatch.setattr(
            "app.runs_models.code_execution_backend", lambda: None
        )
        response = client.post(
            "/api/runs",
            json={"research_goal": "evolve it", "discovery": _spec()},
        )
        assert response.status_code == 503
        assert "sandboxed code" in response.json()["detail"]

    def test_an_ordinary_run_is_unaffected(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The gate is per discovery run, not per deployment: hypothesis
        # generation executes nothing and must not be taken down with it.
        monkeypatch.setattr(
            "app.runs_models.code_execution_backend", lambda: None
        )
        response = client.post("/api/runs", json={"research_goal": "why?"})
        assert response.status_code in (200, 201)

    async def test_evaluation_fails_permanently_instead_of_retrying(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The guarantee the create-time gate only approximates: with a
        # separate worker service the evaluating host is not the one
        # that answered the request. Anything but UnsupportedTaskError
        # here spends the retry budget on a refusal that is identical
        # every time, and strands the run with no reason attached.
        from app.discovery_execution import evaluate_confined
        from app.task_worker_outcomes import UnsupportedTaskError

        monkeypatch.setattr(
            "co_scientist.sandbox.argv.sandbox_backend", lambda: None
        )
        with pytest.raises(UnsupportedTaskError, match="sandboxed code"):
            await evaluate_confined(*_unconfinable_evaluation())


def _unconfinable_evaluation() -> tuple[Any, Any]:
    """A real session and request, so the refusal comes from the sandbox."""
    import tempfile
    from pathlib import Path

    from co_scientist.code_eval import EvaluationRequest
    from co_scientist.workspace.session import WorkspaceSession

    root = Path(tempfile.mkdtemp())
    spec_config = {"discovery": _spec()}
    from app.discovery_spec import evaluator_spec

    return (
        WorkspaceSession(root),
        EvaluationRequest(
            spec=evaluator_spec(spec_config), files={"main.py": "print(1)"}
        ),
    )

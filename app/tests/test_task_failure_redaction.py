"""Durable BYOK task failures keep key material out of stored diagnostics."""

from __future__ import annotations

import json
from typing import Any

import pytest
from co_scientist.exceptions import LLMTimeoutError

from app import credentials, engine_tasks, store, task_worker
from app.config import settings
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client

_BYOK_SECRET = "synthetic-byok-encryption-secret"
_BYOK_KEY = "sk-synthetic-echo-redaction-67890"
_DIAGNOSTIC = "provider diagnostic preserved"


def _parse_sse(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_durable_byok_failure_redacts_owned_surfaces_after_reopen(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider echo stays out of durable task diagnostics."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "byok_encryption_key", _BYOK_SECRET)

    async def _echo_key(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise LLMTimeoutError(f"provider echoed {_BYOK_KEY}; {_DIAGNOSTIC}")

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _echo_key)

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "synthetic failure goal"}
        )
        assert created.status_code == 200
        run_id = created.json()["id"]
        credentials.store_run_credential(
            run_id,
            DEFAULT_TEST_CLIENT_ID,
            credentials.ByokCredential(
                provider="deepseek",
                api_key=_BYOK_KEY,
                model="deepseek/deepseek-v4-flash",
            ),
            db_path=isolated_db,
        )
        assert (
            client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
        )

        # An ambiguous stored-key timeout requires an explicit owner retry.
        assert await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )
        assert not await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )

    # A new API client models reopening the persisted store after the worker
    # process has gone away; the same owner can still read its run and replay.
    with make_client() as reopened:
        run = reopened.get(f"/api/runs/{run_id}")
        tasks = reopened.get(f"/api/runs/{run_id}/tasks")
        events = reopened.get(f"/api/runs/{run_id}/events")
        logs = reopened.get(
            f"/api/runs/{run_id}/logs", params={"verbose": True}
        )

    assert (
        run.status_code
        == tasks.status_code
        == events.status_code
        == logs.status_code
        == 200
    )
    run_body = run.json()
    task_rows = tasks.json()["tasks"]
    replayed_events = _parse_sse(events.text)
    serialized = json.dumps(
        [run_body, task_rows, replayed_events, logs.json()], sort_keys=True
    )
    assert run_body["status"] == "failed"
    assert run_body["failure_kind"] == "llm_timeout_unknown"
    assert _BYOK_KEY not in serialized
    assert "[REDACTED]" in serialized
    assert _DIAGNOSTIC in serialized
    assert task_rows[-1]["status"] == "failed"
    assert len(task_rows[-1]["attempts"]) == 1
    assert replayed_events[-1]["type"] == "_terminal"
    assert any(
        row.get("exc_text") and _DIAGNOSTIC in row["exc_text"]
        for row in logs.json()["logs"]
    )


@pytest.mark.asyncio
async def test_required_auth_owner_can_reopen_redacted_failure_replay(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signed owner reads survive reopen; another researcher gets 404."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "byok_encryption_key", _BYOK_SECRET)
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "auth_secret", "synthetic-test-signing-key")
    monkeypatch.setattr(
        settings,
        "researcher_access_codes",
        '{"failure-owner":"owner-invite","failure-other":"other-invite"}',
    )

    async def _echo_key(
        _task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        raise LLMTimeoutError(f"provider echoed {_BYOK_KEY}; {_DIAGNOSTIC}")

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", _echo_key)

    with make_client() as client:
        owner_session = client.post(
            "/api/auth/exchange", json={"access_code": "owner-invite"}
        )
        other_session = client.post(
            "/api/auth/exchange", json={"access_code": "other-invite"}
        )
        assert owner_session.status_code == other_session.status_code == 200
        owner_headers = {
            "Authorization": f"Bearer {owner_session.json()['access_token']}"
        }
        other_headers = {
            "Authorization": f"Bearer {other_session.json()['access_token']}"
        }
        created = client.post(
            "/api/runs",
            headers=owner_headers,
            json={"research_goal": "authenticated synthetic failure"},
        )
        assert created.status_code == 200
        run_id = created.json()["id"]
        credentials.store_run_credential(
            run_id,
            "failure-owner",
            credentials.ByokCredential(
                provider="deepseek",
                api_key=_BYOK_KEY,
                model="deepseek/deepseek-v4-flash",
            ),
            db_path=isolated_db,
        )
        assert (
            client.post(
                f"/api/runs/{run_id}/start", headers=owner_headers, json={}
            ).status_code
            == 200
        )
        assert await task_worker.run_once(
            "synthetic-worker", db_path=isolated_db
        )

    with make_client() as reopened:
        owner_run = reopened.get(f"/api/runs/{run_id}", headers=owner_headers)
        owner_events = reopened.get(
            f"/api/runs/{run_id}/events", headers=owner_headers
        )
        owner_logs = reopened.get(
            f"/api/runs/{run_id}/logs",
            headers=owner_headers,
            params={"verbose": True},
        )
        other_run = reopened.get(f"/api/runs/{run_id}", headers=other_headers)
        other_events = reopened.get(
            f"/api/runs/{run_id}/events", headers=other_headers
        )

    assert owner_run.status_code == owner_events.status_code == 200
    assert owner_logs.status_code == 200
    assert other_run.status_code == other_events.status_code == 404
    replayed = _parse_sse(owner_events.text)
    failed = [
        event
        for event in replayed
        if event["type"] == "status"
        and event.get("payload", {}).get("status") == "failed"
    ]
    assert len(failed) == 1
    owned_output = json.dumps(
        [owner_run.json(), replayed, owner_logs.json()], sort_keys=True
    )
    assert "[REDACTED]" in owned_output
    assert _BYOK_KEY not in owned_output
    assert _DIAGNOSTIC in owned_output

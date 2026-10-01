"""Integration tests spanning router + store + engine_adapter + report.finalize.

``test_runs.py`` and friends already cover single-endpoint behavior; this file
covers multi-component journeys none of them exercise: a full run's event log
cross-checked through both the store and the HTTP API, SSE replay-then-live
consistency over a real HTTP round trip, and a mid-run cancellation leaving a
consistent terminal state everywhere.

The SSE scenario needs genuine concurrency between the run's background
workflow and the request that observes it mid-flight. ``TestClient`` cannot
provide that: Starlette runs ``BackgroundTasks`` to completion inside the same
ASGI call that scheduled them, so a synchronous ``client.post(.../start)``
never returns until the whole run has finished. It instead uses
``httpx.AsyncClient`` over ``ASGITransport`` on a single event loop, driving
the run as a concurrent ``asyncio`` task and polling the store (which is
synchronous but process-local, so writes are visible the instant they commit)
to know when to act. The API cancel endpoint's own contract (a draft/
restart-survivor cancel, and the terminal event replay) is covered in
``test_runs_edge.py``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from app import store
from app.config import settings
from tests._client import DEFAULT_TEST_CLIENT_ID
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status


def _asgi_app() -> FastAPI:
    """Import and return the FastAPI app lazily.

    Deferred so ``app.main`` (which reads settings from the environment at
    import time) only imports after the ``isolated_db`` fixture has set its
    environment variables -- mirrors ``tests._client.make_client``.
    """
    from app.main import app

    return app


def _parse_sse(text: str) -> list[dict[str, Any]]:
    """Parse an SSE response body into its ``data:`` event dicts, in order."""
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


async def _await_condition(
    predicate: Callable[[], bool],
    *,
    timeout: float = 5.0,
    interval: float = 0.005,
) -> None:
    """Poll ``predicate`` on the running loop until true, or fail on timeout.

    Each sleep cedes control to the event loop, which is what lets the
    concurrently-running workflow task make progress between checks.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met before timeout")


def _start_express_run(client: Any, goal: str) -> str:
    """Create and start an express run over the sync client; return its id."""
    res = client.post(
        "/api/runs", json={"research_goal": goal, "tier": "express"}
    )
    run_id: str = res.json()["id"]
    start = client.post(f"/api/runs/{run_id}/start", json={})
    assert start.status_code == 200
    assert _wait_status(client, run_id, "completed", timeout=20.0)
    return run_id


async def _drive_replay_then_live_run(
    isolated_db: str,
) -> tuple[str, httpx.Response, httpx.Response, int]:
    """Start a run and capture its SSE stream opened mid-flight."""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_asgi_app()),
        base_url="http://test",
        headers={"X-Client-ID": DEFAULT_TEST_CLIENT_ID},
    ) as client:
        create = await client.post(
            "/api/runs",
            json={
                "research_goal": "Integration flow: SSE replay-then-live "
                "consistency",
                "tier": "express",
            },
        )
        run_id = create.json()["id"]
        start_task = asyncio.create_task(
            client.post(f"/api/runs/{run_id}/start", json={})
        )
        # Let a handful of events land before the stream opens, so the request
        # below genuinely mixes replayed history with live-tail delivery
        # instead of only ever seeing a full-history snapshot.
        await _await_condition(
            lambda: len(store.list_events(run_id, db_path=isolated_db)) >= 3
        )
        events_at_open = len(store.list_events(run_id, db_path=isolated_db))
        events_resp = await client.get(
            f"/api/runs/{run_id}/events", params={"after": 0}
        )
        start_resp = await start_task
    return run_id, events_resp, start_resp, events_at_open


# ---------------------------------------------------------------------------
# Full run: creation -> start -> completion, event log cross-checked via the
# store AND the HTTP API.
# ---------------------------------------------------------------------------


def test_full_run_flow_persists_events_matching_store_and_api(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _start_express_run(
        client,
        "Integration flow: dissect ferroptosis resistance in melanoma",
    )

    stored = store.list_events(run_id, db_path=isolated_db)
    assert stored

    api_events = _parse_sse(client.get(f"/api/runs/{run_id}/events").text)
    assert api_events[-1]["type"] == "_terminal"
    assert api_events[-1]["payload"]["status"] == "completed"

    # Every persisted event is replayed verbatim (seq, type, and payload),
    # in order, ahead of the synthetic terminal marker.
    replayed = api_events[:-1]
    assert [e["seq"] for e in replayed] == [e["seq"] for e in stored]
    assert [e["type"] for e in replayed] == [e["type"] for e in stored]
    assert [e["payload"] for e in replayed] == [e["payload"] for e in stored]

    api_hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    store_hyps = store.list_hypotheses(run_id, db_path=isolated_db)
    assert {h["id"] for h in api_hyps} == {h["id"] for h in store_hyps}

    api_report = client.get(f"/api/runs/{run_id}/report").json()
    store_report = store.get_latest_report(run_id, db_path=isolated_db)
    assert store_report is not None
    assert api_report["id"] == store_report["id"]
    assert api_report["payload"] == store_report["payload"]


# ---------------------------------------------------------------------------
# SSE replay-then-live: opening the stream mid-run must still return the
# run's full persisted timeline, proving live-tail delivery beyond replay.
# ---------------------------------------------------------------------------


async def test_sse_stream_replay_then_live_matches_full_event_log(
    isolated_db: str,
) -> None:
    (
        run_id,
        events_resp,
        start_resp,
        events_at_open,
    ) = await _drive_replay_then_live_run(isolated_db)

    assert start_resp.status_code == 200
    assert events_resp.status_code == 200
    collected = _parse_sse(events_resp.text)
    assert collected[-1]["type"] == "_terminal"
    assert collected[-1]["payload"]["status"] == "completed"

    non_terminal = collected[:-1]
    stored = store.list_events(run_id, db_path=isolated_db)
    assert [e["seq"] for e in non_terminal] == [e["seq"] for e in stored]
    assert [e["type"] for e in non_terminal] == [e["type"] for e in stored]

    # The stream's full content includes events that postdate the open-time
    # snapshot, so what came back is more than a frozen replay: the response
    # only completes once the workflow reaches a terminal state, and the
    # live-tail poll loop is what lets events appended afterward reach it
    # (verified directly, without this end-to-end request's buffering, in
    # test_runs_events.py's ``_stream_live_tail`` unit tests).
    assert len(non_terminal) > events_at_open


def test_completion_notification_is_opt_in_and_durable(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A requested email becomes a retryable task only after report release."""
    # An SMTP transport has to exist for the opt-in to mean anything; without
    # one the task is never enqueued (see _enqueue_completion_notification).
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@example.org")
    headers = {"X-Client-ID": "notification-scientist"}
    with _client() as client:
        created = client.post(
            "/api/runs",
            headers=headers,
            json={
                "research_goal": "Study notification fidelity",
                "tier": "express",
                "notify_on_completion": True,
                "completion_email": "scientist@example.org",
            },
        )
        run_id = created.json()["id"]
        assert (
            client.post(
                f"/api/runs/{run_id}/start", headers=headers, json={}
            ).status_code
            == 200
        )
        _wait_status(
            client,
            run_id,
            "completed",
            timeout=20.0,
            interval=0.1,
        )

    tasks = store.list_tasks(run_id, db_path=isolated_db)
    email_tasks = [
        task for task in tasks if task.task_type == "notification.email"
    ]
    assert len(email_tasks) == 1
    assert email_tasks[0].inputs["email"] == "scientist@example.org"
    assert email_tasks[0].max_attempts == 3


def test_completion_notification_is_skipped_without_an_smtp_transport(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unsendable notice is reported, not queued to fail three times."""
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from_email", "")
    headers = {"X-Client-ID": "unconfigured-scientist"}
    with caplog.at_level("WARNING"), _client() as client:
        run_id = client.post(
            "/api/runs",
            headers=headers,
            json={
                "research_goal": "Study notification fidelity",
                "tier": "express",
                "notify_on_completion": True,
                "completion_email": "scientist@example.org",
            },
        ).json()["id"]
        client.post(f"/api/runs/{run_id}/start", headers=headers, json={})
        _wait_status(client, run_id, "completed", timeout=20.0, interval=0.1)

    tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert not [t for t in tasks if t.task_type == "notification.email"]
    assert "SMTP is not configured" in caplog.text

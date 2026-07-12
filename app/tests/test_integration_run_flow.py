"""Integration tests spanning router + store + engine_adapter + report_render.

``test_runs.py`` and friends already cover single-endpoint behavior for the
mock provider; this file covers multi-component journeys none of them
exercise: a full run's event log cross-checked through both the store and
the HTTP API, SSE replay-then-live consistency over a real HTTP round trip,
a mid-run cancellation leaving a consistent terminal state everywhere, and a
steering message queued (and drained) while the workflow is already running.

The SSE/cancellation/steering scenarios need genuine concurrency between the
run's background workflow and the request that observes it mid-flight.
``TestClient`` cannot provide that: Starlette runs ``BackgroundTasks`` to
completion inside the same ASGI call that scheduled them, so a synchronous
``client.post(.../start)`` never returns until the whole run has finished.
Those scenarios instead use ``httpx.AsyncClient`` over ``ASGITransport`` on
a single event loop, driving the run as a concurrent ``asyncio`` task and
polling the store (which is synchronous but process-local, so writes are
visible the instant they commit) to know when to act.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import FastAPI
from httpx import ASGITransport

from app import store
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


def _event_type_count(run_id: str, db_path: str, type_: str) -> int:
    """Count persisted events of ``type_`` for a run."""
    events = store.list_events(run_id, db_path=db_path)
    return sum(1 for e in events if e["type"] == type_)


# ---------------------------------------------------------------------------
# Full run: creation -> start -> completion, event log cross-checked via the
# store AND the HTTP API.
# ---------------------------------------------------------------------------


def test_full_run_flow_persists_events_matching_store_and_api(
    isolated_db: str,
) -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Integration flow: dissect ferroptosis "
            "resistance in melanoma",
            "tier": "standard",
        },
    )
    run_id = res.json()["id"]

    start = client.post(f"/api/runs/{run_id}/start", json={})
    assert start.status_code == 200
    assert _wait_status(client, run_id, "completed", timeout=20.0)

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
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_asgi_app()), base_url="http://test"
    ) as client:
        create = await client.post(
            "/api/runs",
            json={
                "research_goal": "Integration flow: SSE replay-then-live "
                "consistency",
                "tier": "standard",
            },
        )
        run_id = create.json()["id"]

        start_task: asyncio.Task[httpx.Response] = asyncio.create_task(
            client.post(f"/api/runs/{run_id}/start", json={})
        )

        # Let a handful of events land before the stream opens, so the
        # request below genuinely mixes replayed history with live-tail
        # delivery instead of only ever seeing a full-history snapshot.
        await _await_condition(
            lambda: len(store.list_events(run_id, db_path=isolated_db)) >= 3
        )
        events_at_open = len(store.list_events(run_id, db_path=isolated_db))

        events_resp = await client.get(
            f"/api/runs/{run_id}/events", params={"after": 0}
        )
        start_resp = await start_task

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


# ---------------------------------------------------------------------------
# Cancellation mid-run: a cancel issued once the tournament has genuinely
# started must leave a consistent terminal state everywhere.
# ---------------------------------------------------------------------------


async def test_cancel_mid_run_leaves_consistent_terminal_state(
    isolated_db: str,
) -> None:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_asgi_app()), base_url="http://test"
    ) as client:
        create = await client.post(
            "/api/runs",
            json={
                "research_goal": "Integration flow: cancel mid-run consistency",
                "tier": "standard",
            },
        )
        run_id = create.json()["id"]

        start_task: asyncio.Task[httpx.Response] = asyncio.create_task(
            client.post(f"/api/runs/{run_id}/start", json={})
        )

        # Wait for the first tournament round to land -- proof the run has
        # genuinely progressed (hypotheses generated, first Elo round done)
        # -- before cancelling, so this is a real mid-run cancel rather than
        # the pre-start rejection already covered by test_runs_edge.py.
        await _await_condition(
            lambda: _event_type_count(run_id, isolated_db, "ranking") >= 1
        )

        cancel_resp = await client.post(f"/api/runs/{run_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelling"

        start_resp = await start_task
        assert start_resp.status_code == 200

        run_resp = await client.get(f"/api/runs/{run_id}")
        events_resp = await client.get(f"/api/runs/{run_id}/events")
        report_resp = await client.get(f"/api/runs/{run_id}/report")
        report_md_resp = await client.get(f"/api/runs/{run_id}/report.md")

    assert run_resp.json()["status"] == "cancelled"

    api_events = _parse_sse(events_resp.text)
    assert api_events[-1]["type"] == "_terminal"
    assert api_events[-1]["payload"]["status"] == "cancelled"
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "cancelled"
        for e in api_events
    )
    assert report_resp.status_code == 404
    assert report_md_resp.status_code == 404

    stored = store.list_events(run_id, db_path=isolated_db)
    assert stored[-1]["type"] == "status"
    assert stored[-1]["payload"]["status"] == "cancelled"
    # Partial progress persisted (hypotheses from generation), but the run
    # never reached finalization.
    assert store.list_hypotheses(run_id, db_path=isolated_db)
    assert store.get_latest_report(run_id, db_path=isolated_db) is None


# ---------------------------------------------------------------------------
# Steering mid-run: a message queued after the workflow has started must be
# drained by a later iteration, not just by the pre-run drain.
# ---------------------------------------------------------------------------


async def test_steering_message_queued_mid_run_is_drained(
    isolated_db: str,
) -> None:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_asgi_app()), base_url="http://test"
    ) as client:
        create = await client.post(
            "/api/runs",
            json={
                "research_goal": "Integration flow: steering drained mid-run",
                "tier": "standard",
            },
        )
        run_id = create.json()["id"]

        start_task: asyncio.Task[httpx.Response] = asyncio.create_task(
            client.post(f"/api/runs/{run_id}/start", json={})
        )

        # Wait for the first tournament round -- steering sent after this
        # point is queued strictly mid-run, not before the workflow began
        # (that pre-run path is already covered by test_messages.py).
        await _await_condition(
            lambda: _event_type_count(run_id, isolated_db, "ranking") >= 1
        )

        send_resp = await client.post(
            f"/api/runs/{run_id}/messages",
            json={"content": "prioritize the top-ranked mechanism"},
        )
        assert send_resp.status_code == 200
        assert send_resp.json()["applied"] is False
        msg_id = send_resp.json()["id"]

        start_resp = await start_task
        assert start_resp.status_code == 200

        messages_resp = await client.get(f"/api/runs/{run_id}/messages")

    msgs = messages_resp.json()["messages"]
    sent = next(m for m in msgs if m["id"] == msg_id)
    assert sent["applied"] is True

    # A second tournament round happened after the message was queued -- the
    # drain point (top of the next iteration) genuinely ran mid-run, not
    # before the workflow started.
    stored_types = [
        e["type"] for e in store.list_events(run_id, db_path=isolated_db)
    ]
    assert stored_types.count("ranking") >= 2


def test_completion_notification_is_opt_in_and_durable(
    isolated_db: str,
) -> None:
    """A requested email becomes a retryable task only after report release."""
    headers = {"X-Client-ID": "notification-scientist"}
    with _client() as client:
        created = client.post(
            "/api/runs",
            headers=headers,
            json={
                "research_goal": "Study notification fidelity",
                "notify_on_completion": True,
                "completion_email": "scientist@example.org",
            },
        )
        run_id = created.json()["id"]
        assert client.post(
            f"/api/runs/{run_id}/start", headers=headers, json={}
        ).status_code == 200
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

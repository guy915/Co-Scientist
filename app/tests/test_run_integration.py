"""Tests for run integration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport

from app import seed, store, task_worker
from app.config import settings
from app.demo_seed_data import (
    DEMO_SCENARIOS,
    DEMO_SEED_VERSION,
    scenario_hypotheses,
    scenario_key,
)
from app.engine_adapter.events import (
    _canonical_engine_payload,
    _canonical_event_type,
)
from app.engine_tasks import inputs as engine_tasks_inputs
from app.engine_tasks import node as engine_tasks_node
from app.engine_tasks import support as engine_tasks_support
from app.report import build as report_build
from app.report import finalize as report_finalize
from app.seed.overview import full_review_count, simulation_review_count
from app.store import DEMO_CLIENT_ID, RunRow, RunStatus
from app.store import db as store_db
from tests._client import DEFAULT_TEST_CLIENT_ID, wait_for_status
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status
from tests._drain_helpers import (
    _engine_hypothesis,
    _final_state_with_features,
    _persist,
)

# Reader-facing visibility of engine schema degradations (L7).
#
# The engine records every enhancement node served a placeholder fallback
# instead of parseable LLM output (``degraded_nodes`` in workflow state).
# These tests pin the app half: the drain hands the list to the report
# path, the persisted report payload carries it as ``degraded_sections``,
# and canonical node events surface it once a commit holds it -- so a blank
# report section can explain itself instead of showing silence.


def test_drain_result_carries_degraded_sections(isolated_db: str) -> None:
    """The drain hands the engine's degraded nodes to the report path."""
    run = store.create_run("degraded goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["degraded_nodes"] = ["meta_review", "research_overview"]

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["degraded_sections"] == [
        "meta_review",
        "research_overview",
    ]


def test_drain_result_defaults_to_no_degraded_sections(
    isolated_db: str,
) -> None:
    """A run without degradations reports an empty list, not an absent key."""
    run = store.create_run("clean goal", "standard", "engine", {})

    drained = _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    assert drained.report_inputs["degraded_sections"] == []


def test_report_payload_carries_degraded_sections(isolated_db: str) -> None:
    """The persisted report payload names the sections that degraded."""
    run = store.create_run("degraded goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["degraded_nodes"] = ["meta_review"]

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": type_, "payload": payload}

    from tests._client import drain as _drain

    _drain(
        report_finalize.finalize_report(
            run.id,
            report_build.ReportRequest(
                research_goal=run.research_goal,
                run_mode="standard",
                provider="engine",
                execution_time=1.0,
                db_path=isolated_db,
                **drained.report_inputs,
            ),
            _emit,
        )
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["degraded_sections"] == ["meta_review"]


def test_report_payload_degraded_sections_default_empty(
    isolated_db: str,
) -> None:
    """Reports for clean runs still carry the field, empty."""
    run = store.create_run("clean goal", "standard", "engine", {})

    drained = _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": type_, "payload": payload}

    from tests._client import drain as _drain

    _drain(
        report_finalize.finalize_report(
            run.id,
            report_build.ReportRequest(
                research_goal=run.research_goal,
                run_mode="standard",
                provider="engine",
                execution_time=1.0,
                db_path=isolated_db,
                **drained.report_inputs,
            ),
            _emit,
        )
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["degraded_sections"] == []


def test_node_event_payload_surfaces_degraded_nodes() -> None:
    """A node commit holding degradations carries them on its event."""
    state: dict[str, Any] = {
        "current_iteration": 1,
        "degraded_nodes": ["deep_verification"],
    }

    payload = _canonical_engine_payload(
        "ranking", _canonical_event_type("ranking"), state
    )

    assert payload["degraded"] == ["deep_verification"]


def test_node_event_payload_omits_degraded_when_clean() -> None:
    """Clean runs emit no degraded key on their node events."""
    state: dict[str, Any] = {"current_iteration": 0, "degraded_nodes": []}

    payload = _canonical_engine_payload(
        "generate", _canonical_event_type("generate"), state
    )

    assert "degraded" not in payload


# Tests for restart-safety: interrupted-run reconciliation and WAL checkpoint.
#
# These harness fixes ensure a long research run does not get stuck "running"
# forever when the server is restarted mid-run.


def _make_run(goal: str, isolated_db: str) -> str:
    run = store.create_run(
        goal,
        "default",
        "engine",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    return run.id


def test_reconcile_fails_interrupted_runs(isolated_db: str) -> None:
    """Queued/running/synthesizing runs become failed; terminal runs left."""
    running = _make_run("running goal", isolated_db)
    store.update_run_status(
        running, store.RunStatus.RUNNING, db_path=isolated_db
    )
    queued = _make_run("queued goal", isolated_db)
    store.update_run_status(queued, store.RunStatus.QUEUED, db_path=isolated_db)
    synth = _make_run("synth goal", isolated_db)
    store.update_run_status(
        synth, store.RunStatus.SYNTHESIZING, db_path=isolated_db
    )
    done = _make_run("done goal", isolated_db)
    store.update_run_status(
        done, store.RunStatus.COMPLETED, db_path=isolated_db
    )

    reconciled = store.reconcile_interrupted_runs(db_path=isolated_db)

    # None of these have a checkpoint, so all fail (none resumable).
    assert set(reconciled["failed"]) == {running, queued, synth}
    assert reconciled["resumable"] == []
    for rid in (running, queued, synth):
        row = store.get_run(rid, db_path=isolated_db)
        assert row is not None
        assert row.status == store.RunStatus.FAILED.value
        assert row.error and "restart" in row.error
    # Terminal runs are untouched.
    done_row = store.get_run(done, db_path=isolated_db)
    assert done_row is not None
    assert done_row.status == store.RunStatus.COMPLETED.value


def test_active_engine_tasks_are_discoverable_before_lease_expiry(
    isolated_db: str,
) -> None:
    """Startup recovery sees a live lease without waiting to reconcile it."""
    run = store.create_run(
        "recover leased science",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.review",
            inputs={"checkpoint_seq": 1},
            idempotency_key="recover-review",
        ),
        db_path=isolated_db,
    )
    assert (
        store.claim_task("dead-worker", lease_seconds=300, db_path=isolated_db)
        is not None
    )

    assert store.list_active_engine_task_run_ids(db_path=isolated_db) == [
        run.id
    ]


def test_reconcile_marks_checkpointed_run_resumable(isolated_db: str) -> None:
    """An interrupted run with a checkpoint is resumable, not failed (M4)."""
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, store.RunStatus.RUNNING, db_path=isolated_db)
    store.save_checkpoint(
        rid,
        store.NewCheckpoint(
            stage="post_ranking",
            schema_version=1,
            last_event_seq=7,
            state={"round": 1},
        ),
        db_path=isolated_db,
    )

    reconciled = store.reconcile_interrupted_runs(db_path=isolated_db)

    assert reconciled["resumable"] == [rid]
    assert reconciled["failed"] == []
    # A resumable run is NOT marked failed.
    row = store.get_run(rid, db_path=isolated_db)
    assert row is not None
    assert row.status != store.RunStatus.FAILED.value
    # A 'resumable' status event is logged for the stream/UI.
    events = store.list_events(rid, db_path=isolated_db)
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "resumable"
        for e in events
    )


def test_reconcile_appends_status_event(isolated_db: str) -> None:
    """A reconciled run gets a terminal 'failed' status event for the stream."""
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, store.RunStatus.RUNNING, db_path=isolated_db)
    store.reconcile_interrupted_runs(db_path=isolated_db)
    events = store.list_events(rid, db_path=isolated_db)
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "failed"
        for e in events
    )


def test_reconcile_is_idempotent(isolated_db: str) -> None:
    """A second pass finds nothing to reconcile (all runs already terminal)."""
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, store.RunStatus.RUNNING, db_path=isolated_db)
    assert store.reconcile_interrupted_runs(db_path=isolated_db)["failed"] == [
        rid
    ]
    assert not store.reconcile_interrupted_runs(db_path=isolated_db)["failed"]


def test_reconciled_run_is_restartable(isolated_db: str) -> None:
    """A reconciled (failed) run is restartable.

    It is no longer in an un-startable in-progress state -- ``start_run``
    only rejects running/synthesizing/completed.
    """
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, store.RunStatus.RUNNING, db_path=isolated_db)
    store.reconcile_interrupted_runs(db_path=isolated_db)
    row = store.get_run(rid, db_path=isolated_db)
    assert row is not None
    assert row.status not in (
        store.RunStatus.RUNNING.value,
        store.RunStatus.SYNTHESIZING.value,
        store.RunStatus.COMPLETED.value,
    )


def test_checkpoint_wal_runs_cleanly(isolated_db: str) -> None:
    """The WAL checkpoint helper succeeds on an initialized database."""
    _make_run("g", isolated_db)
    # Should not raise.
    store.checkpoint_wal(db_path=isolated_db)


def test_headerless_run_survives_restart(isolated_db: str) -> None:
    """A header-less (empty client_id) run is not purged on restart.

    The pre-client-isolation purge must be one-time (only when the column is
    first added), not run on every startup -- otherwise every API run created
    without an X-Client-ID header would silently vanish on restart.
    """
    run = store.create_run(
        "g",
        "default",
        "engine",
        {},
        store.RunCreateOptions(client_id="", db_path=isolated_db),
    )
    # Simulate a server restart re-running migrations on the existing DB.
    with store.connect(isolated_db) as conn:
        store_db._run_migrations(conn)
    rows = store.list_runs(client_id="", db_path=isolated_db)
    assert any(r.id == run.id for r in rows)


# Tests for append-only evolution and hypothesis lineage.


def _wait_completed(
    client: TestClient, run_id: str, timeout: float = 20.0
) -> None:
    assert wait_for_status(client, run_id, "completed", timeout=timeout), (
        "run did not complete in time"
    )


def _by_id(hyps: list[dict[str, Any]], hid: str) -> dict[str, Any]:
    """Look up a hypothesis by id within a fetched hypothesis list."""
    return next(h for h in hyps if h["id"] == hid)


def _walk_to_root(
    hyps: list[dict[str, Any]], child: dict[str, Any]
) -> dict[str, Any]:
    """Walk a hypothesis's parent chain back to its root.

    Asserts there is no cycle along the way.
    """
    cur = child
    seen: set[str] = set()
    while cur["parent_id"]:
        assert cur["id"] not in seen, "lineage cycle"
        seen.add(cur["id"])
        cur = _by_id(hyps, cur["parent_id"])
    return cur


def _split_by_lineage(
    hyps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split hypotheses into (initial, evolved) by parent_id presence."""
    initial = [h for h in hyps if h["parent_id"] is None]
    evolved = [h for h in hyps if h["parent_id"] is not None]
    return initial, evolved


def _assert_child_lineage(
    hyps: list[dict[str, Any]], child: dict[str, Any], initial_ids: set[str]
) -> None:
    """Assert one evolved child's lineage, generation, and identity.

    Walks the child's lineage back to an initial (gen 0) hypothesis, checks
    its generation is exactly one past its parent's, and confirms the engine
    did not overwrite the parent in place (distinct id from every initial).
    """
    root = _walk_to_root(hyps, child)
    assert root["id"] in initial_ids
    parent_row = _by_id(hyps, child["parent_id"])
    assert child["generation"] == parent_row["generation"] + 1
    assert child["id"] not in initial_ids


def _three_generation_state() -> dict[str, Any]:
    """A final state whose lineage runs root -> child -> grandchild.

    Two generations deep on purpose: a run that evolves more than once
    breeds from children as well as roots, and depth one cannot tell a
    correct parent walk from one that stops at the first hop.
    """
    return {
        "hypotheses": [
            _engine_hypothesis(
                "root-1",
                "Root hypothesis about glioma stem-cell apoptosis.",
                parent_id=None,
                generation=0,
                origin="generation",
            ),
            _engine_hypothesis(
                "child-1",
                "Refined hypothesis naming a specific caspase cascade.",
                parent_id="root-1",
                generation=1,
                origin="evolution",
            ),
            _engine_hypothesis(
                "grandchild-1",
                "Further refined hypothesis adding a delivery route.",
                parent_id="child-1",
                generation=2,
                origin="evolution",
            ),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def test_evolution_creates_new_rows_with_parent_lineage(
    isolated_db: str,
) -> None:
    """Evolved rows sit alongside their parents and keep a walkable lineage.

    Driven through the drain rather than a live run. A live run cannot
    assert that any child exists: the near-duplicate guard legitimately
    creates no child when a refinement lands on text a peer already holds,
    which offline content -- built from one goal's small template pool --
    reaches often enough to make the assertion a coin flip. What the
    product does guarantee is that whatever evolution *does* produce is
    appended with correct lineage, which is what this pins, at the depth
    a multi-iteration run actually reaches.
    """
    run = store.create_run(
        "Targeted apoptosis in glioma stem cells",
        "express",
        "engine",
        {},
        store.RunCreateOptions(
            client_id=DEFAULT_TEST_CLIENT_ID, db_path=isolated_db
        ),
    )
    _persist(
        run_id=run.id,
        final_state=_three_generation_state(),
        db_path=isolated_db,
    )

    client = _client()
    hyps = client.get(f"/api/runs/{run.id}/hypotheses").json()["hypotheses"]
    initial, evolved = _split_by_lineage(hyps)

    # Append semantics: the root survives its own refinement.
    assert [h["id"] for h in initial] == ["root-1"]
    assert {h["id"] for h in evolved} == {"child-1", "grandchild-1"}

    initial_ids = {h["id"] for h in initial}
    for child in evolved:
        _assert_child_lineage(hyps, child, initial_ids)


def test_evolution_runs_between_ranking_rounds(isolated_db: str) -> None:
    """Evolve runs after the first tournament and feeds a second one.

    The durable node executor records a completed ``evolve`` task in the run
    event log, and the tournament produces matches on both sides of it.

    Deliberately does not assert that a child was published. The
    near-duplicate guard creates no child when a refinement matches text a
    peer already holds, which is correct behaviour and happens often enough
    against offline content to make that assertion a coin flip. Lineage
    itself is pinned deterministically by
    ``test_evolution_creates_new_rows_with_parent_lineage``.
    """
    from app import store

    client = _client()
    rid = client.post(
        "/api/runs",
        json={
            "research_goal": "Lipid raft remodelling in viral entry",
            "tier": "express",
        },
    ).json()["id"]
    client.post(f"/api/runs/{rid}/start", json={})
    _wait_completed(client, rid)

    res = client.get(f"/api/runs/{rid}/events")
    assert res.status_code == 200

    # The durable path emits a scientific_task event per specialist node; the
    # evolve node's completion is the direct signal it ran.
    events = store.list_events(rid, db_path=isolated_db)
    assert any(
        e["type"] == "scientific_task" and e["payload"].get("task") == "evolve"
        for e in events
    )
    # The tournament produced matches on both sides of the evolve step.
    assert len(client.get(f"/api/runs/{rid}/matches").json()["matches"]) >= 2


# Integration tests spanning router + store + engine_adapter + report.finalize.
#
# ``test_runs.py`` and friends already cover single-endpoint behavior; this file
# covers multi-component journeys none of them exercise: a full run's event log
# cross-checked through both the store and the HTTP API, SSE replay-then-live
# consistency over a real HTTP round trip, and a mid-run cancellation leaving a
# consistent terminal state everywhere.
#
# The SSE scenario needs genuine concurrency between the run's background
# workflow and the request that observes it mid-flight. ``TestClient`` cannot
# provide that: Starlette runs ``BackgroundTasks`` to completion inside the same
# ASGI call that scheduled them, so a synchronous ``client.post(.../start)``
# never returns until the whole run has finished. It instead uses
# ``httpx.AsyncClient`` over ``ASGITransport`` on a single event loop, driving
# the run as a concurrent ``asyncio`` task and polling the store (which is
# synchronous but process-local, so writes are visible the instant they commit)
# to know when to act. The API cancel endpoint's own contract (a draft/
# restart-survivor cancel, and the terminal event replay) is covered in
# ``test_runs_edge.py``.


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


# End-to-end durability of steering and fan-out isolation on a real run.
#
# Both tests drive a whole offline-backed express run through the durable
# executor -- the real ``HypothesisGenerator`` on the deterministic offline
# backend, the real graph, the real ``build_engine_opts``, the real task
# queue -- and inject one fault into it.
#
# The first queues a scientist steer mid-run and loses the worker between
# the moment the steer is read and the moment the checkpoint that honors it
# commits. The second fails one matchup of the tournament fan-out and
# checks that its siblings were committed rather than re-judged.


_STEER = "Prioritise chaperone co-expression over temperature shifts"


def _persist_offline_run(isolated_db: str) -> Any:
    """Persist an offline-backed express run on the engine path."""
    return store.create_run(
        "Explain how protein X folds under crowding.",
        "express",
        "mock",
        {"tier": "express", "enable_literature_review": False},
        store.RunCreateOptions(
            client_id="steering-e2e",
            llm_backend="offline",
            db_path=isolated_db,
        ),
    )


def _drive(run_id: str, isolated_db: str) -> None:
    """Run the whole durable cohort for one run to settlement."""
    asyncio.run(
        task_worker.run_run_worker_pool(
            run_id,
            "steering-e2e-worker",
            policy=task_worker.WorkerPolicy(db_path=isolated_db),
        )
    )


def _steer_mid_run_then_crash(
    monkeypatch: pytest.MonkeyPatch, run_id: str, db_path: str
) -> dict[str, int]:
    """Queue a steer after the run is under way, then lose the next commit.

    The steer is appended from the second successor commit, so it enters a
    run already past bootstrap. The first commit that then *carries* it
    dies before its transaction, which is exactly the window between
    reading the steering queue and committing the checkpoint that honors
    it. Patched in all three namespaces the helper is imported into, since
    each caller resolves its own module-level name.
    """
    real = engine_tasks_support._save_state_and_enqueue
    box = {"commits": 0, "crashes": 0}

    def crashing(
        commit: Any,
        state: Any,
        successor: Any,
        *,
        pause_if_requested: bool = False,
    ) -> Any:
        box["commits"] += 1
        if box["commits"] == 2:
            store.append_message(
                store.NewMessage(
                    run_id=run_id,
                    sender="user",
                    content=_STEER,
                    kind="steering",
                ),
                db_path=db_path,
            )
        if commit.steering_ids and not box["crashes"]:
            box["crashes"] += 1
            raise RuntimeError("worker lost before the checkpoint committed")
        return real(
            commit,
            state,
            successor,
            pause_if_requested=pause_if_requested,
        )

    for module in (
        engine_tasks_support,
        engine_tasks_inputs,
        engine_tasks_node,
    ):
        monkeypatch.setattr(module, "_save_state_and_enqueue", crashing)
    return box


def test_mid_run_steering_survives_a_crash_and_applies_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A steer queued mid-run reaches the engine exactly once, crash or not."""
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    run = _persist_offline_run(isolated_db)
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    box = _steer_mid_run_then_crash(monkeypatch, run.id, isolated_db)

    _drive(run.id, isolated_db)

    assert box["crashes"] == 1, "the crash window was never exercised"
    assert store.get_pending_steering(run.id, db_path=isolated_db) == []
    steers = [
        message
        for message in store.list_messages(run.id, db_path=isolated_db)
        if message.kind == "steering"
    ]
    assert [message.applied for message in steers] == [True]
    final = store.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is not None


def _fail_one_judged_matchup(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Make one tournament matchup's judge raise, the rest go through."""
    import co_scientist.agents.ranking.operations as ranking_module

    real = ranking_module.judge_matchup
    box = {"calls": 0, "failed": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        box["calls"] += 1
        if box["calls"] == 2:
            box["failed"] += 1
            raise RuntimeError("judge provider refused this matchup")
        return await real(*args, **kwargs)

    monkeypatch.setattr(ranking_module, "judge_matchup", flaky)
    return box


def test_one_failed_matchup_leaves_the_rest_of_the_run_intact(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-item fault in the tournament fan-out settles the run anyway."""
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    run = _persist_offline_run(isolated_db)
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    box = _fail_one_judged_matchup(monkeypatch)

    _drive(run.id, isolated_db)

    assert box["failed"] == 1, "the failure window was never exercised"
    final = store.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    matches = store.list_matches(run.id, db_path=isolated_db)
    assert len(matches) > 1
    # Every judged matchup but the failed one was committed, and none was
    # judged twice: an aborted wave would have re-judged its siblings on
    # the task's retry, so the call count would exceed the match count by
    # a whole wave rather than by the single failure.
    assert box["calls"] == len(matches) + 1
    failed_tasks = [
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.status == "failed"
    ]
    assert failed_tasks == []


# Offline engine workflow: unified event vocabulary and artifact shape.
#
# These tests drive the durable run path (the same node-level task executor a
# real ``POST /start`` uses) pinned to the deterministic offline backend, then
# read the persisted event log. They assert the unified engine event vocabulary,
# the terminal lifecycle, and the shape of the deep-verification and
# research-overview artifacts. The offline router's per-call determinism is
# proven in the engine's own ``tests/test_offline_llm.py``; run-level artifact
# determinism does *not* hold here (later prompts embed fresh per-hypothesis
# identifiers), so it is not asserted.


def _run_offline_workflow(
    goal: str, db_path: str
) -> tuple[str, list[dict[str, Any]]]:
    """Drive one express offline engine run and return (run_id, events).

    Delivers the run through the durable task queue and drains it with a
    bounded worker cohort (as the embedded API worker does), then returns the
    persisted event log so the vocabulary and ordering can be asserted.
    """
    run = store.create_run(
        goal,
        "express",
        "engine",
        {"tier": "express"},
        store.RunCreateOptions(llm_backend="offline", db_path=db_path),
    )
    task_worker.enqueue_run_workflow(run.id, db_path=db_path)
    asyncio.run(
        task_worker.run_run_worker_pool(
            run.id,
            "offline-workflow-test",
            policy=task_worker.WorkerPolicy(db_path=db_path),
        )
    )
    events = store.list_events(run.id, db_path=db_path)
    return run.id, events


def test_offline_workflow_emits_canonical_event_sequence(
    isolated_db: str,
) -> None:
    """The durable run emits the gate/stage vocabulary in graph order."""
    run_id, events = _run_offline_workflow("Sequence test goal", isolated_db)
    types = [e["type"] for e in events]
    # Each durable node commit surfaces a ``scientific_task`` event naming the
    # node it completed; the graph stages are read from those, not from
    # per-node top-level event types, which this path does not emit.
    nodes = [
        e["payload"].get("task")
        for e in events
        if e["type"] == "scientific_task"
    ]

    # The lifecycle gate/stage events the durable path emits at the boundaries.
    expected_gate_events = {
        "safety.intake",
        "safety.hypothesis",
        "citation.grounding",
        "citation_audit",
        "safety.final",
        "report",
    }
    assert expected_gate_events <= set(types), (
        f"missing gate events: {expected_gate_events - set(types)}"
    )

    # Every substantive graph node the engine runs appears as a completed
    # durable task. Proximity is not in this set: the scheduler only runs it
    # when the pool grew since the last proximity pass, and evolution's
    # children are sometimes rejected (unchanged echoes or near-duplicates),
    # so an offline express run can legitimately finish without one.
    expected_nodes = {
        "supervisor",
        "generate",
        "review",
        "ranking",
        "evolve",
        "meta_review",
        "deep_verification",
        "research_overview",
    }
    assert expected_nodes <= set(nodes), (
        f"missing nodes: {expected_nodes - set(nodes)}"
    )

    # The scheduling link still holds: pool growth is the trigger for a
    # proximity pass, and express's max_iterations=1 rules out a second
    # generate, so an evolved child in the store exactly mirrors the
    # scheduler's pool-grew signal.
    hyps = store.list_hypotheses(run_id, db_path=isolated_db)
    if any(h.get("parent_id") for h in hyps):
        assert "proximity" in nodes, "missing nodes: {'proximity'}"

    # Ordering the graph guarantees: intake gates first, planning precedes
    # generation, and the report is the last thing before the terminal status.
    assert types.index("safety.intake") == 0
    assert nodes.index("supervisor") < nodes.index("generate")
    assert types[-1] == "status"
    assert types.index("report") == len(types) - 2


def test_offline_workflow_completes_with_report(isolated_db: str) -> None:
    """A keyless offline run reaches completed and publishes a ranked report."""
    run_id, events = _run_offline_workflow("Completion test goal", isolated_db)

    assert events[-1]["type"] == "status"
    assert events[-1]["payload"].get("status") == "completed"

    final = store.get_run(run_id)
    assert final is not None
    assert final.status == store.RunStatus.COMPLETED.value

    hyps = store.list_hypotheses(run_id)
    assert hyps
    report = store.get_latest_report(run_id)
    assert report is not None
    assert report["payload"]["leaderboard"]
    assert report["payload"]["provider"] == "engine"


def test_offline_deep_verification_writes_reviews(isolated_db: str) -> None:
    """Deep verification runs as a durable node and attaches its review rows."""
    run_id, events = _run_offline_workflow(
        "Deep verification goal", isolated_db
    )

    nodes = [
        e["payload"].get("task")
        for e in events
        if e["type"] == "scientific_task"
    ]
    assert "deep_verification" in nodes

    # The reviews table carries deep_verification-authored rows for the probed
    # hypotheses, alongside the standard review pass.
    reviews = store.list_reviews(run_id, db_path=isolated_db)
    deep = [r for r in reviews if r["reviewer_agent"] == "deep_verification"]
    assert deep
    assert all(r["summary"] for r in deep)


def test_offline_research_overview_rides_report(isolated_db: str) -> None:
    """The research overview lands in the report payload and its markdown."""
    run_id, events = _run_offline_workflow(
        "Research overview goal", isolated_db
    )

    nodes = [
        e["payload"].get("task")
        for e in events
        if e["type"] == "scientific_task"
    ]
    assert "research_overview" in nodes

    report = store.get_latest_report(run_id, db_path=isolated_db)
    assert report is not None
    assert report["payload"].get("research_overview")

    markdown = report["markdown_text"]
    assert "## Research Overview" in markdown


# Tests for the startup demo-run seeder in ``app.seed``.
#
# Exercises the full seed-then-reseed lifecycle directly (not through the app's
# lifespan), including the already-seeded no-op branch, the reseed-on-missing-
# report branch, and the per-goal failure isolation.


def _seed(db_path: str) -> None:
    asyncio.run(seed.seed_demo_runs(db_path=db_path))


def test_seed_demo_runs_creates_three_runs_with_reports(
    isolated_db: str,
) -> None:
    _seed(isolated_db)

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    goals = {r.research_goal for r in runs}
    assert goals == set(seed._DEMO_GOALS)
    for run in runs:
        # Each default demo is a complete browseable, offline-backed example.
        assert run.status == "completed"
        assert run.llm_backend == "offline"
        assert store.run_used_offline(run)
        md = store.read_report_markdown(run.id, db_path=isolated_db)
        assert md is not None and "Research Report" in md
        scenario = DEMO_SCENARIOS[run.research_goal]
        expected_ideas = len(scenario_hypotheses(scenario))
        hypotheses = store.list_hypotheses(run.id, db_path=isolated_db)
        assert len(hypotheses) == expected_ideas
        evidence = store.list_evidence(run.id, db_path=isolated_db)
        assert len(evidence) == 6
        # R12-12: the demo's real curated sources carry a PubMed id
        # wired through from their own url, so the run-wide bibliography
        # is populated with real identifiers rather than empty.
        assert all(item["pmid"] for item in evidence)
        assert "\n## References\n" in md
        assert md.count("\n- [") == 6
        key = scenario_key(scenario)
        # Every idea carries reflection + deep_verification; only the
        # highest-ranked ideas additionally carry a curated full/simulation
        # review row (see app.seed.overview).
        expected_reviews = (
            expected_ideas * 2
            + full_review_count(key)
            + simulation_review_count(key)
        )
        assert (
            len(store.list_reviews(run.id, db_path=isolated_db))
            == expected_reviews
        )
        assert len(store.list_matches(run.id, db_path=isolated_db)) == (
            expected_ideas - 1 + expected_ideas // 2
        )
        # Every example idea has a tournament record; none is shown unranked.
        assert all(
            hypothesis["win_count"] + hypothesis["loss_count"]
            for hypothesis in hypotheses
        )
        assert "Curated demonstration only" in md
        report = store.get_latest_report(run.id, db_path=isolated_db)
        assert report is not None
        assert report["payload"]["demo_seed_version"] == DEMO_SEED_VERSION
        assert len(report["payload"]["knowledge_base"]) == 6
        overview = report["payload"]["research_overview"]
        aims = overview["nih_specific_aims"]["aims"]
        assert len(aims) == 3
        metrics = store.get_run_metrics(run.id, db_path=isolated_db)
        assert metrics is not None
        assert metrics["total_time"] == scenario.duration_seconds
        assert max(hypothesis["elo_rating"] for hypothesis in hypotheses) == (
            scenario.elo_ceiling
        )

    assert sorted(
        len(scenario_hypotheses(scenario))
        for scenario in DEMO_SCENARIOS.values()
    ) == [15, 19, 21]


def test_seed_demo_runs_render_criteria_and_unexpected_directions(
    isolated_db: str,
) -> None:
    """Both R12-18/R12-23 report sections are populated, not merely wired.

    A report is stored, frozen ``reports.markdown_text``; nothing
    re-renders it, so a demo only shows a new section once it is re-seeded
    with curated data that supplies it. This pins that the curated
    ``critical_criteria`` (``seed/config_synthesis.py``) fill the report's
    prose "Evaluation Criteria" section (``_render_evaluation_criteria_
    markdown``) and that the curated ``unexpected_research_directions``
    fill the "Unexpected research directions" bullets
    (``_render_unexpected_directions_section``) on all three demos.
    """
    _seed(isolated_db)

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    for run in runs:
        md = store.read_report_markdown(run.id, db_path=isolated_db)
        assert md is not None
        assert "\n## Evaluation Criteria\n" in md
        section = md.split("## Evaluation Criteria", 1)[1]
        next_heading = re.search(r"\n## ", section)
        body = section[: next_heading.start()] if next_heading else section
        entries = [line for line in body.splitlines() if line.startswith("**")]
        assert entries
        for entry in entries:
            assert entry.startswith("**")
            assert ":** " in entry

        assert "\n### Unexpected research directions\n" in md
        directions_section = md.split("### Unexpected research directions", 1)[
            1
        ]
        next_directions_heading = re.search(r"\n#{1,3} ", directions_section)
        directions_body = (
            directions_section[: next_directions_heading.start()]
            if next_directions_heading
            else directions_section
        )
        bullets = [
            line
            for line in directions_body.splitlines()
            if line.startswith("- ")
        ]
        assert len(bullets) == 3
        for bullet in bullets:
            assert bullet.startswith("- **")
            assert bullet.count("**") >= 2


def test_seed_demo_runs_render_main_research_directions(
    isolated_db: str,
) -> None:
    """R14-27: all three demos show the report's own narrative directions.

    Pins that the curated ``main_research_directions``
    (``seed/meta_review.py``) fills the report's "## Main
    Research Directions" section, sitting immediately before Top
    hypotheses (R14-27's own published "before Candidate Ideas"
    placement), with two genuinely populated paragraphs -- not a bare
    heading.
    """
    _seed(isolated_db)

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    for run in runs:
        md = store.read_report_markdown(run.id, db_path=isolated_db)
        assert md is not None
        assert "\n## Main Research Directions\n" in md

        directions_index = md.index("## Main Research Directions")
        candidates_index = md.index("## Top hypotheses")
        assert directions_index < candidates_index

        section = md.split("## Main Research Directions", 1)[1]
        next_heading = re.search(r"\n#{1,2} ", section)
        body = section[: next_heading.start()] if next_heading else section
        paragraphs = [
            p.strip() for p in body.strip().split("\n\n") if p.strip()
        ]
        assert len(paragraphs) == 2
        for paragraph in paragraphs:
            assert paragraph
            assert "**" in paragraph


def test_seed_demo_runs_is_idempotent_when_reports_exist(
    isolated_db: str,
) -> None:
    _seed(isolated_db)
    before = {
        r.id: store.get_latest_report(r.id, db_path=isolated_db)
        for r in store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    }

    _seed(isolated_db)

    after_runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(after_runs) == 3
    assert {r.id for r in after_runs} == set(before)
    # No report was regenerated: created_at timestamps are unchanged.
    for run in after_runs:
        report = store.get_latest_report(run.id, db_path=isolated_db)
        assert report is not None
        seeded_at = before[run.id]["created_at"]  # type: ignore[index]
        assert report["created_at"] == seeded_at


def test_seed_demo_runs_reseeds_run_missing_report(isolated_db: str) -> None:
    goal = seed._DEMO_GOALS[0]
    run = store.create_run(
        goal,
        "default",
        "mock",
        {},
        store.RunCreateOptions(client_id=DEMO_CLIENT_ID, db_path=isolated_db),
    )
    assert store.read_report_markdown(run.id, db_path=isolated_db) is None

    _seed(isolated_db)

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    reseeded = next(r for r in runs if r.research_goal == goal)
    # The existing row is reused (re-seeded in place), not duplicated.
    assert reseeded.id == run.id
    assert (
        store.read_report_markdown(reseeded.id, db_path=isolated_db) is not None
    )


def test_seed_demo_runs_replaces_legacy_demo_content(isolated_db: str) -> None:
    """An older persisted report is upgraded to the curated scenario."""
    goal = seed._DEMO_GOALS[0]
    run = store.create_run(
        goal,
        "express",
        "engine",
        {},
        store.RunCreateOptions(client_id=DEMO_CLIENT_ID, db_path=isolated_db),
    )
    store.save_report(run.id, {"legacy": True}, "# Legacy", db_path=isolated_db)

    _seed(isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["demo_seed_version"] == DEMO_SEED_VERSION
    assert "Curated demonstration only" in report["markdown_text"]


def test_seed_demo_runs_backfills_goal_detail_config(isolated_db: str) -> None:
    """A current report cannot leave an old demo row's details empty."""
    goal = seed._DEMO_GOALS[0]
    run = store.create_run(
        goal,
        "standard",
        "engine",
        {},
        store.RunCreateOptions(client_id=DEMO_CLIENT_ID, db_path=isolated_db),
    )
    store.save_report(
        run.id,
        {"demo_seed_version": DEMO_SEED_VERSION},
        "# Current-looking report",
        db_path=isolated_db,
    )

    _seed(isolated_db)

    upgraded = store.get_run(run.id, db_path=isolated_db)
    assert upgraded is not None
    setup = upgraded.config["setup"]
    assert len(setup["requirements"]) == 6
    assert len(setup["attributes"]) == 5


def test_seed_demo_run_failure_is_swallowed(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed per-goal seed is logged and does not abort the others."""

    async def _boom(goal: str, run: RunRow | None, db_path: str | None) -> None:
        raise RuntimeError("seed failure")

    monkeypatch.setattr(seed, "_seed_demo_run", _boom)

    with caplog.at_level(logging.ERROR, logger="app.seed"):
        _seed(isolated_db)

    assert "Failed to seed demo run" in caplog.text
    assert store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db) == []


def test_seed_demo_run_creates_new_run_when_none_given(
    isolated_db: str,
) -> None:
    """``_seed_demo_run`` creates a run itself when passed ``run=None``."""
    # This exercises the seeding primitive directly, bypassing
    # ``seed_demo_runs`` (which installs the router itself), so install the
    # offline router first -- otherwise the engine run's offline/ model calls
    # have no handler and the run fails. Idempotent; a passthrough for real
    # models.
    from co_scientist.offline.llm import install_offline_router

    install_offline_router()
    goal = "A standalone seeding goal"
    asyncio.run(seed._seed_demo_run(goal, None, isolated_db))

    runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    created = [r for r in runs if r.research_goal == goal]
    assert len(created) == 1
    assert created[0].status == "completed"
    assert created[0].llm_backend == "offline"
    assert store.read_report_markdown(created[0].id, db_path=isolated_db)


@pytest.mark.parametrize("has_report", [False, True])
def test_custom_goal_is_reseeded_only_when_report_missing(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, has_report: bool
) -> None:
    run = store.create_run(
        "custom goal",
        "express",
        "engine",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    if has_report:
        store.save_report(run.id, {"k": "v"}, "# md", db_path=isolated_db)
    reseeded: list[str] = []

    async def record_seed(
        goal: str, existing: RunRow | None, db_path: str | None
    ) -> None:
        assert goal == run.research_goal
        assert existing == run
        assert db_path == isolated_db
        reseeded.append(run.id)

    monkeypatch.setattr(seed, "_seed_demo_run", record_seed)
    asyncio.run(
        seed._seed_or_reseed_demo_run(run.research_goal, run, isolated_db)
    )

    assert reseeded == ([] if has_report else [run.id])

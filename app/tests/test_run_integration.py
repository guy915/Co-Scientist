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

from app import seed, task_worker
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
from app.store import checkpoints, db, messages, records, reports
from app.store import events as store_events
from app.store import hypotheses as store_hypotheses
from app.store import retrieval_calls as retrieval
from app.store import runs as store
from app.store import runs_views as views
from app.store import tasks as store_tasks
from app.store.checkpoints import NewCheckpoint
from app.store.messages import NewMessage
from app.store.models import DEMO_CLIENT_ID, RunRow, RunStatus
from app.store.runs import RunCreateOptions
from app.store.tasks import NewTask
from tests._client import DEFAULT_TEST_CLIENT_ID, wait_for_status
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status
from tests._drain_helpers import (
    _engine_hypothesis,
    _final_state_with_features,
    _persist,
    emit_event,
)


def test_drain_result_carries_degraded_sections(isolated_db: str) -> None:
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
    run = store.create_run("clean goal", "standard", "engine", {})

    drained = _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    assert drained.report_inputs["degraded_sections"] == []


def test_report_payload_carries_degraded_sections(isolated_db: str) -> None:
    run = store.create_run("degraded goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["degraded_nodes"] = ["meta_review"]

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

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
            emit_event,
        )
    )

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["degraded_sections"] == ["meta_review"]


def test_report_payload_degraded_sections_default_empty(
    isolated_db: str,
) -> None:
    run = store.create_run("clean goal", "standard", "engine", {})

    drained = _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

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
            emit_event,
        )
    )

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["degraded_sections"] == []


def test_node_event_payload_surfaces_degraded_nodes() -> None:
    state: dict[str, Any] = {
        "current_iteration": 1,
        "degraded_nodes": ["deep_verification"],
    }

    payload = _canonical_engine_payload(
        "ranking", _canonical_event_type("ranking"), state
    )

    assert payload["degraded"] == ["deep_verification"]


def test_node_event_payload_omits_degraded_when_clean() -> None:
    state: dict[str, Any] = {"current_iteration": 0, "degraded_nodes": []}

    payload = _canonical_engine_payload(
        "generate", _canonical_event_type("generate"), state
    )

    assert "degraded" not in payload


def _make_run(goal: str, isolated_db: str) -> str:
    run = store.create_run(
        goal,
        "default",
        "engine",
        {},
        RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    return run.id


def test_reconcile_fails_interrupted_runs(isolated_db: str) -> None:
    running = _make_run("running goal", isolated_db)
    store.update_run_status(running, RunStatus.RUNNING, db_path=isolated_db)
    queued = _make_run("queued goal", isolated_db)
    store.update_run_status(queued, RunStatus.QUEUED, db_path=isolated_db)
    synth = _make_run("synth goal", isolated_db)
    store.update_run_status(synth, RunStatus.SYNTHESIZING, db_path=isolated_db)
    done = _make_run("done goal", isolated_db)
    store.update_run_status(done, RunStatus.COMPLETED, db_path=isolated_db)

    reconciled = views.reconcile_interrupted_runs(db_path=isolated_db)

    assert set(reconciled["failed"]) == {running, queued, synth}
    assert reconciled["resumable"] == []
    for rid in (running, queued, synth):
        row = store.get_run(rid, db_path=isolated_db)
        assert row is not None
        assert row.status == RunStatus.FAILED.value
        assert row.error and "restart" in row.error
    done_row = store.get_run(done, db_path=isolated_db)
    assert done_row is not None
    assert done_row.status == RunStatus.COMPLETED.value


def test_active_engine_tasks_are_discoverable_before_lease_expiry(
    isolated_db: str,
) -> None:
    run = store.create_run(
        "recover leased science",
        "standard",
        "engine",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    store.update_run_status(run.id, RunStatus.RUNNING, db_path=isolated_db)
    store_tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.review",
            inputs={"checkpoint_seq": 1},
            idempotency_key="recover-review",
        ),
        db_path=isolated_db,
    )
    assert (
        store_tasks.claim_task(
            "dead-worker", lease_seconds=300, db_path=isolated_db
        )
        is not None
    )

    assert store_tasks.list_active_engine_task_run_ids(db_path=isolated_db) == [
        run.id
    ]


def test_reconcile_marks_checkpointed_run_resumable(isolated_db: str) -> None:
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, RunStatus.RUNNING, db_path=isolated_db)
    checkpoints.save_checkpoint(
        rid,
        NewCheckpoint(
            stage="post_ranking",
            schema_version=1,
            last_event_seq=7,
            state={"round": 1},
        ),
        db_path=isolated_db,
    )

    reconciled = views.reconcile_interrupted_runs(db_path=isolated_db)

    assert reconciled["resumable"] == [rid]
    assert reconciled["failed"] == []
    row = store.get_run(rid, db_path=isolated_db)
    assert row is not None
    assert row.status != RunStatus.FAILED.value
    events = store_events.list_events(rid, db_path=isolated_db)
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "resumable"
        for e in events
    )


def test_reconcile_appends_status_event(isolated_db: str) -> None:
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, RunStatus.RUNNING, db_path=isolated_db)
    views.reconcile_interrupted_runs(db_path=isolated_db)
    events = store_events.list_events(rid, db_path=isolated_db)
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "failed"
        for e in events
    )


def test_reconcile_is_idempotent(isolated_db: str) -> None:
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, RunStatus.RUNNING, db_path=isolated_db)
    assert views.reconcile_interrupted_runs(db_path=isolated_db)["failed"] == [
        rid
    ]
    assert not views.reconcile_interrupted_runs(db_path=isolated_db)["failed"]


def test_reconciled_run_is_restartable(isolated_db: str) -> None:
    rid = _make_run("g", isolated_db)
    store.update_run_status(rid, RunStatus.RUNNING, db_path=isolated_db)
    views.reconcile_interrupted_runs(db_path=isolated_db)
    row = store.get_run(rid, db_path=isolated_db)
    assert row is not None
    assert row.status not in (
        RunStatus.RUNNING.value,
        RunStatus.SYNTHESIZING.value,
        RunStatus.COMPLETED.value,
    )


def test_checkpoint_wal_runs_cleanly(isolated_db: str) -> None:
    _make_run("g", isolated_db)
    db.checkpoint_wal(db_path=isolated_db)


def test_headerless_run_survives_restart(isolated_db: str) -> None:
    run = store.create_run(
        "g",
        "default",
        "engine",
        {},
        RunCreateOptions(client_id="", db_path=isolated_db),
    )
    db._initialized.discard(isolated_db)
    with db.connect(isolated_db):
        pass
    rows = views.list_runs(client_id="", db_path=isolated_db)
    assert any(r.id == run.id for r in rows)


def _wait_completed(
    client: TestClient, run_id: str, timeout: float = 20.0
) -> None:
    assert wait_for_status(client, run_id, "completed", timeout=timeout), (
        "run did not complete in time"
    )


def _by_id(hyps: list[dict[str, Any]], hid: str) -> dict[str, Any]:
    return next(h for h in hyps if h["id"] == hid)


def _walk_to_root(
    hyps: list[dict[str, Any]], child: dict[str, Any]
) -> dict[str, Any]:
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
    initial = [h for h in hyps if h["parent_id"] is None]
    evolved = [h for h in hyps if h["parent_id"] is not None]
    return initial, evolved


def _assert_child_lineage(
    hyps: list[dict[str, Any]], child: dict[str, Any], initial_ids: set[str]
) -> None:
    root = _walk_to_root(hyps, child)
    assert root["id"] in initial_ids
    parent_row = _by_id(hyps, child["parent_id"])
    assert child["generation"] == parent_row["generation"] + 1
    assert child["id"] not in initial_ids


def _three_generation_state() -> dict[str, Any]:
    # Two generations distinguish a complete parent walk from one that stops
    # after the first hop.
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
    # Offline near-duplicate guards may produce no child; deterministic drain
    # fixtures test actual lineage guarantees.
    run = store.create_run(
        "Targeted apoptosis in glioma stem cells",
        "express",
        "engine",
        {},
        RunCreateOptions(client_id=DEFAULT_TEST_CLIENT_ID, db_path=isolated_db),
    )
    _persist(
        run_id=run.id,
        final_state=_three_generation_state(),
        db_path=isolated_db,
    )

    client = _client()
    hyps = client.get(f"/api/runs/{run.id}/hypotheses").json()["hypotheses"]
    initial, evolved = _split_by_lineage(hyps)

    assert [h["id"] for h in initial] == ["root-1"]
    assert {h["id"] for h in evolved} == {"child-1", "grandchild-1"}

    initial_ids = {h["id"] for h in initial}
    for child in evolved:
        _assert_child_lineage(hyps, child, initial_ids)


def test_evolution_runs_between_ranking_rounds(isolated_db: str) -> None:
    # Evolution need not create a child when a peer already holds its refinement
    # text.
    from app.store import events as store

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

    events = store.list_events(rid, db_path=isolated_db)
    assert any(
        e["type"] == "scientific_task" and e["payload"].get("task") == "evolve"
        for e in events
    )
    assert len(client.get(f"/api/runs/{rid}/matches").json()["matches"]) >= 2


# Use one async loop for concurrent SSE observation; TestClient background
# execution can finish before return.


def _asgi_app() -> FastAPI:
    # Import settings only after isolated_db establishes its environment.
    from app.main import app

    return app


def _parse_sse(text: str) -> list[dict[str, Any]]:
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
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met before timeout")


def _start_express_run(client: Any, goal: str) -> str:
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
        await _await_condition(
            lambda: (
                len(store_events.list_events(run_id, db_path=isolated_db)) >= 3
            )
        )
        events_at_open = len(
            store_events.list_events(run_id, db_path=isolated_db)
        )
        events_resp = await client.get(
            f"/api/runs/{run_id}/events", params={"after": 0}
        )
        start_resp = await start_task
    return run_id, events_resp, start_resp, events_at_open


def test_full_run_flow_persists_events_matching_store_and_api(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _start_express_run(
        client,
        "Integration flow: dissect ferroptosis resistance in melanoma",
    )

    stored = store_events.list_events(run_id, db_path=isolated_db)
    assert stored

    api_events = _parse_sse(client.get(f"/api/runs/{run_id}/events").text)
    assert api_events[-1]["type"] == "_terminal"
    assert api_events[-1]["payload"]["status"] == "completed"

    replayed = api_events[:-1]
    assert [e["seq"] for e in replayed] == [e["seq"] for e in stored]
    assert [e["type"] for e in replayed] == [e["type"] for e in stored]
    assert [e["payload"] for e in replayed] == [e["payload"] for e in stored]

    api_hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    store_hyps = store_hypotheses.list_hypotheses(run_id, db_path=isolated_db)
    assert {h["id"] for h in api_hyps} == {h["id"] for h in store_hyps}

    api_report = client.get(f"/api/runs/{run_id}/report").json()
    store_report = reports.get_latest_report(run_id, db_path=isolated_db)
    assert store_report is not None
    assert api_report["id"] == store_report["id"]
    assert api_report["payload"] == store_report["payload"]


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
    stored = store_events.list_events(run_id, db_path=isolated_db)
    assert [e["seq"] for e in non_terminal] == [e["seq"] for e in stored]
    assert [e["type"] for e in non_terminal] == [e["type"] for e in stored]

    assert len(non_terminal) > events_at_open


def test_completion_notification_is_opt_in_and_durable(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    tasks = store_tasks.list_tasks(run_id, db_path=isolated_db)
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

    tasks = store_tasks.list_tasks(run_id, db_path=isolated_db)
    assert not [t for t in tasks if t.task_type == "notification.email"]
    assert "SMTP is not configured" in caplog.text


_STEER = "Prioritise chaperone co-expression over temperature shifts"


def _persist_offline_run(isolated_db: str) -> Any:
    return store.create_run(
        "Explain how protein X folds under crowding.",
        "express",
        "mock",
        {"tier": "express", "enable_literature_review": False},
        RunCreateOptions(
            client_id="steering-e2e",
            llm_backend="offline",
            db_path=isolated_db,
        ),
    )


def _drive(run_id: str, isolated_db: str) -> None:
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
    # Lose the first commit carrying steering to test the read-before-checkpoint
    # failure window.
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
            messages.append_message(
                NewMessage(
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
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    run = _persist_offline_run(isolated_db)
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    box = _steer_mid_run_then_crash(monkeypatch, run.id, isolated_db)

    _drive(run.id, isolated_db)

    assert box["crashes"] == 1, "the crash window was never exercised"
    assert messages.get_pending_steering(run.id, db_path=isolated_db) == []
    steers = [
        message
        for message in messages.list_messages(run.id, db_path=isolated_db)
        if message.kind == "steering"
    ]
    assert [message.applied for message in steers] == [True]
    final = store.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    assert reports.get_latest_report(run.id, db_path=isolated_db) is not None


def _fail_one_judged_matchup(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
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
    matches = records.list_matches(run.id, db_path=isolated_db)
    assert len(matches) > 1
    # Sibling matchup commits survive one failure; only the failed judgment may
    # rerun.
    assert box["calls"] == len(matches) + 1
    failed_tasks = [
        task
        for task in store_tasks.list_tasks(run.id, db_path=isolated_db)
        if task.status == "failed"
    ]
    assert failed_tasks == []


# Fresh hypothesis identifiers affect later prompts, so run-level offline
# artifact equality is not guaranteed.


def _run_offline_workflow(
    goal: str, db_path: str
) -> tuple[str, list[dict[str, Any]]]:
    run = store.create_run(
        goal,
        "express",
        "engine",
        {"tier": "express"},
        RunCreateOptions(llm_backend="offline", db_path=db_path),
    )
    task_worker.enqueue_run_workflow(run.id, db_path=db_path)
    asyncio.run(
        task_worker.run_run_worker_pool(
            run.id,
            "offline-workflow-test",
            policy=task_worker.WorkerPolicy(db_path=db_path),
        )
    )
    events = store_events.list_events(run.id, db_path=db_path)
    return run.id, events


def test_offline_workflow_emits_canonical_event_sequence(
    isolated_db: str,
) -> None:
    run_id, events = _run_offline_workflow("Sequence test goal", isolated_db)
    types = [e["type"] for e in events]
    nodes = [
        e["payload"].get("task")
        for e in events
        if e["type"] == "scientific_task"
    ]

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

    # Proximity only runs after pool growth; near-duplicate rejection can
    # legitimately leave no pass.
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

    hyps = store_hypotheses.list_hypotheses(run_id, db_path=isolated_db)
    if any(h.get("parent_id") for h in hyps):
        assert "proximity" in nodes, "missing nodes: {'proximity'}"

    assert types.index("safety.intake") == 0
    assert nodes.index("supervisor") < nodes.index("generate")
    assert types[-1] == "status"
    assert types.index("report") == len(types) - 2


def test_offline_workflow_completes_with_report(isolated_db: str) -> None:
    run_id, events = _run_offline_workflow("Completion test goal", isolated_db)

    assert events[-1]["type"] == "status"
    assert events[-1]["payload"].get("status") == "completed"

    final = store.get_run(run_id)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value

    hyps = store_hypotheses.list_hypotheses(run_id)
    assert hyps
    report = reports.get_latest_report(run_id)
    assert report is not None
    assert report["payload"]["leaderboard"]
    assert report["payload"]["provider"] == "engine"


def test_offline_deep_verification_writes_reviews(isolated_db: str) -> None:
    run_id, events = _run_offline_workflow(
        "Deep verification goal", isolated_db
    )

    nodes = [
        e["payload"].get("task")
        for e in events
        if e["type"] == "scientific_task"
    ]
    assert "deep_verification" in nodes

    reviews = records.list_reviews(run_id, db_path=isolated_db)
    deep = [r for r in reviews if r["reviewer_agent"] == "deep_verification"]
    assert deep
    assert all(r["summary"] for r in deep)


def test_offline_research_overview_rides_report(isolated_db: str) -> None:
    run_id, events = _run_offline_workflow(
        "Research overview goal", isolated_db
    )

    nodes = [
        e["payload"].get("task")
        for e in events
        if e["type"] == "scientific_task"
    ]
    assert "research_overview" in nodes

    report = reports.get_latest_report(run_id, db_path=isolated_db)
    assert report is not None
    assert report["payload"].get("research_overview")

    markdown = report["markdown_text"]
    assert "## Research Overview" in markdown


def _seed(db_path: str) -> None:
    asyncio.run(seed.seed_demo_runs(db_path=db_path))


def test_seed_demo_runs_creates_three_runs_with_reports(
    isolated_db: str,
) -> None:
    _seed(isolated_db)

    runs = views.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    goals = {r.research_goal for r in runs}
    assert goals == set(seed._DEMO_GOALS)
    for run in runs:
        assert run.status == "completed"
        assert run.llm_backend == "offline"
        assert store.run_used_offline(run)
        md = reports.read_report_markdown(run.id, db_path=isolated_db)
        assert md is not None and "Research Report" in md
        scenario = DEMO_SCENARIOS[run.research_goal]
        expected_ideas = len(scenario_hypotheses(scenario))
        hypotheses = store_hypotheses.list_hypotheses(
            run.id, db_path=isolated_db
        )
        assert len(hypotheses) == expected_ideas
        evidence = records.list_evidence(run.id, db_path=isolated_db)
        assert len(evidence) == 6
        assert all(item["pmid"] for item in evidence)
        assert "\n## References\n" in md
        assert md.count("\n- [") == 6
        key = scenario_key(scenario)
        expected_reviews = (
            expected_ideas * 2
            + full_review_count(key)
            + simulation_review_count(key)
        )
        assert (
            len(records.list_reviews(run.id, db_path=isolated_db))
            == expected_reviews
        )
        assert len(records.list_matches(run.id, db_path=isolated_db)) == (
            expected_ideas - 1 + expected_ideas // 2
        )
        assert all(
            hypothesis["win_count"] + hypothesis["loss_count"]
            for hypothesis in hypotheses
        )
        assert "Curated demonstration only" in md
        report = reports.get_latest_report(run.id, db_path=isolated_db)
        assert report is not None
        assert report["payload"]["demo_seed_version"] == DEMO_SEED_VERSION
        assert len(report["payload"]["knowledge_base"]) == 6
        overview = report["payload"]["research_overview"]
        aims = overview["nih_specific_aims"]["aims"]
        assert len(aims) == 3
        metrics = retrieval.get_run_metrics(run.id, db_path=isolated_db)
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
    # Demo reports are frozen markdown; newly curated sections require reseeding
    # rather than lazy rendering.
    _seed(isolated_db)

    runs = views.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    for run in runs:
        md = reports.read_report_markdown(run.id, db_path=isolated_db)
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
    _seed(isolated_db)

    runs = views.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    for run in runs:
        md = reports.read_report_markdown(run.id, db_path=isolated_db)
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
        r.id: reports.get_latest_report(r.id, db_path=isolated_db)
        for r in views.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    }

    _seed(isolated_db)

    after_runs = views.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(after_runs) == 3
    assert {r.id for r in after_runs} == set(before)
    for run in after_runs:
        report = reports.get_latest_report(run.id, db_path=isolated_db)
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
        RunCreateOptions(client_id=DEMO_CLIENT_ID, db_path=isolated_db),
    )
    assert reports.read_report_markdown(run.id, db_path=isolated_db) is None

    _seed(isolated_db)

    runs = views.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(runs) == 3
    reseeded = next(r for r in runs if r.research_goal == goal)
    assert reseeded.id == run.id
    assert (
        reports.read_report_markdown(reseeded.id, db_path=isolated_db)
        is not None
    )


def test_seed_demo_runs_replaces_legacy_demo_content(isolated_db: str) -> None:
    goal = seed._DEMO_GOALS[0]
    run = store.create_run(
        goal,
        "express",
        "engine",
        {},
        RunCreateOptions(client_id=DEMO_CLIENT_ID, db_path=isolated_db),
    )
    reports.save_report(
        run.id, {"legacy": True}, "# Legacy", db_path=isolated_db
    )

    _seed(isolated_db)

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["demo_seed_version"] == DEMO_SEED_VERSION
    assert "Curated demonstration only" in report["markdown_text"]


def test_seed_demo_runs_backfills_goal_detail_config(isolated_db: str) -> None:
    goal = seed._DEMO_GOALS[0]
    run = store.create_run(
        goal,
        "standard",
        "engine",
        {},
        RunCreateOptions(client_id=DEMO_CLIENT_ID, db_path=isolated_db),
    )
    reports.save_report(
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

    async def _boom(goal: str, run: RunRow | None, db_path: str | None) -> None:
        raise RuntimeError("seed failure")

    monkeypatch.setattr(seed, "_seed_demo_run", _boom)

    with caplog.at_level(logging.ERROR, logger="app.seed"):
        _seed(isolated_db)

    assert "Failed to seed demo run" in caplog.text
    assert views.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db) == []


def test_seed_demo_run_creates_new_run_when_none_given(
    isolated_db: str,
) -> None:
    # Direct seeding bypasses the wrapper that installs the offline router;
    # install it before offline model calls.
    from co_scientist.offline.llm import install_offline_router

    install_offline_router()
    goal = "A standalone seeding goal"
    asyncio.run(seed._seed_demo_run(goal, None, isolated_db))

    runs = views.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    created = [r for r in runs if r.research_goal == goal]
    assert len(created) == 1
    assert created[0].status == "completed"
    assert created[0].llm_backend == "offline"
    assert reports.read_report_markdown(created[0].id, db_path=isolated_db)


@pytest.mark.parametrize("has_report", [False, True])
def test_custom_goal_is_reseeded_only_when_report_missing(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, has_report: bool
) -> None:
    run = store.create_run(
        "custom goal",
        "express",
        "engine",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    if has_report:
        reports.save_report(run.id, {"k": "v"}, "# md", db_path=isolated_db)
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

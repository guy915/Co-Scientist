from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from typing import Any

import pytest
from co_scientist.models import SCIENTIST_REVIEWER
from fastapi.testclient import TestClient

from app import engine_tasks, task_worker
from app.config import settings
from app.engine_adapter.drain import hypotheses as drain_hypotheses
from app.engine_tasks import inputs as engine_tasks_inputs
from app.engine_tasks import node as engine_tasks_restore
from app.engine_tasks.support import NODE_TASK_PREFIX
from app.store import checkpoints, hypotheses, messages, records, runs
from app.store import db as store_db
from app.store import events as store_events
from app.store import tasks as store
from app.store import tasks_lifecycle as lifecycle
from app.store.hypotheses import HypothesisStateChanges, NewHypothesis
from app.store.models import RunStatus, ScientificTask
from app.store.records import NewReview, NewSafetyDecision
from tests._client import create_run as _create_run
from tests._client import make_client
from tests._client import make_client as _client
from tests._engine_tasks_helpers import (
    _Generator,
    _seed_checkpoint,
    _task_state,
)
from tests._store_helpers import (
    enqueue_task,
    event_seqs,
    seed_checkpoint,
    seed_run,
)


def _checkpointed_run(db: str, client: Any) -> tuple[str, str]:
    response = _create_run(client, "Resume/cancel ordering", tier="express")
    assert response.status_code == 200, response.text
    run_id = str(response.json()["id"])
    runs.update_run_status(run_id, RunStatus.RUNNING, db_path=db)

    writer_type = f"{engine_tasks.NODE_TASK_PREFIX}generate"
    writer = enqueue_task(
        run_id,
        writer_type,
        "resume-cancel:writer",
        inputs={"checkpoint_seq": 0},
        db_path=db,
    )
    claimed = store.claim_task("checkpoint-writer", run_id=run_id, db_path=db)
    assert claimed is not None and claimed.id == writer.id
    assert lifecycle.complete_task(
        writer.id, "checkpoint-writer", {}, db_path=db
    )

    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    checkpoint_seq = seed_checkpoint(
        run_id,
        {"provider": "engine", "resume_successor": successor_type},
        stage=f"engine_task:{writer.id}",
        db_path=db,
    )
    successor = enqueue_task(
        run_id,
        successor_type,
        f"{successor_type}:after:{writer.id}",
        inputs={"checkpoint_seq": checkpoint_seq},
        dependencies=(writer.id,),
        provenance={"scheduled_by": writer_type},
        db_path=db,
    )
    return run_id, successor.id


def _hold_resume_admission(
    monkeypatch: pytest.MonkeyPatch, *, first_only: bool = False
) -> tuple[Event, Event]:
    from app.runs import lifecycle as runs_lifecycle

    reached = Event()
    release = Event()
    original = runs_lifecycle._queue_resume_workflow

    def hold(*args: Any, **kwargs: Any) -> ScientificTask:
        if not (first_only and reached.is_set()):
            reached.set()
            assert release.wait(timeout=5), "resume barrier was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(runs_lifecycle, "_queue_resume_workflow", hold)
    return reached, release


def _assert_settled(
    run_id: str, successor_id: str, db: str, status: RunStatus
) -> ScientificTask:
    run = runs.get_run(run_id, db_path=db)
    task = store.get_task(successor_id, db_path=db)
    assert run is not None and run.status == status.value
    assert task is not None
    assert store.claim_task("after-race", run_id=run_id, db_path=db) is None
    return task


def test_cancel_wins_when_it_commits_before_resume_enqueue(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    run_id, successor_id = _checkpointed_run(isolated_db, owner)
    assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200

    foreign = make_client()
    foreign_headers = {"X-Client-ID": "resume-cancel-foreign"}
    assert (
        foreign.post(
            f"/api/runs/{run_id}/resume", headers=foreign_headers
        ).status_code
        == 404
    )
    assert (
        foreign.post(
            f"/api/runs/{run_id}/cancel", headers=foreign_headers
        ).status_code
        == 404
    )

    queue_reached, release_queue = _hold_resume_admission(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        resume_future = pool.submit(owner.post, f"/api/runs/{run_id}/resume")
        assert queue_reached.wait(timeout=5), (
            "resume did not reach enqueue boundary"
        )
        cancelled = owner.post(f"/api/runs/{run_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        release_queue.set()
        resumed = resume_future.result(timeout=5)

    assert resumed.status_code == 409, resumed.text
    task = _assert_settled(
        run_id, successor_id, isolated_db, RunStatus.CANCELLED
    )
    assert task.status == "cancelled"
    [cancelled_seq] = event_seqs(
        run_id, "status", status="cancelled", db_path=isolated_db
    )
    assert not [
        seq
        for seq in event_seqs(
            run_id, "status", status="resuming", db_path=isolated_db
        )
        if seq > cancelled_seq
    ]

    later_resume = owner.post(f"/api/runs/{run_id}/resume")
    assert later_resume.status_code == 200, later_resume.text
    later_task = store.get_task(successor_id, db_path=isolated_db)
    assert later_task is not None
    assert later_task.task_type == f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    assert later_task.status == "queued"
    assert later_task.dependencies == (task.dependencies[0],)
    claimed_later = store.claim_task(
        "later-resume-worker", run_id=run_id, db_path=isolated_db
    )
    assert claimed_later is not None and claimed_later.id == successor_id


def test_resume_transaction_commits_before_waiting_cancel(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    cancel_client = make_client()
    run_id, successor_id = _checkpointed_run(isolated_db, owner)
    assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200

    enqueue_entered = Event()
    release_enqueue = Event()
    observe_cancel = Event()
    cancel_transaction_entered = Event()
    original_enqueue = task_worker.enqueue_run_workflow
    original_transaction = store_db.transaction

    @contextmanager
    def track_cancel_transaction(
        path: str | None = None,
    ) -> Iterator[sqlite3.Connection]:
        if observe_cancel.is_set():
            cancel_transaction_entered.set()
        with original_transaction(path) as conn:
            yield conn

    def hold_resume_transaction(*args: Any, **kwargs: Any) -> ScientificTask:
        enqueue_entered.set()
        assert release_enqueue.wait(timeout=5), (
            "resume transaction was not released"
        )
        return original_enqueue(*args, **kwargs)

    monkeypatch.setattr(store_db, "transaction", track_cancel_transaction)
    monkeypatch.setattr(
        task_worker,
        "enqueue_run_workflow",
        hold_resume_transaction,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        resume_future = pool.submit(owner.post, f"/api/runs/{run_id}/resume")
        assert enqueue_entered.wait(timeout=5), (
            "resume did not enter its transaction"
        )
        observe_cancel.set()
        cancel_future = pool.submit(
            cancel_client.post, f"/api/runs/{run_id}/cancel"
        )
        try:
            assert cancel_transaction_entered.wait(timeout=5)
        finally:
            release_enqueue.set()
        resumed = resume_future.result(timeout=5)
        cancelled = cancel_future.result(timeout=5)

    assert resumed.status_code == 200, resumed.text
    assert cancelled.status_code == 200, cancelled.text
    task = _assert_settled(
        run_id, successor_id, isolated_db, RunStatus.CANCELLED
    )
    assert task.status == "cancelled"
    [resuming_seq] = event_seqs(
        run_id, "status", status="resuming", db_path=isolated_db
    )
    [cancelled_seq] = event_seqs(
        run_id, "status", status="cancelled", db_path=isolated_db
    )
    assert resuming_seq < cancelled_seq


def test_lifecycle_revision_rejects_paused_cancel_resume_pause_aba(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    later_resumer = make_client()
    run_id, successor_id = _checkpointed_run(isolated_db, owner)
    assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200

    first_queue_reached, release_first_queue = _hold_resume_admission(
        monkeypatch, first_only=True
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale_resume = pool.submit(owner.post, f"/api/runs/{run_id}/resume")
        assert first_queue_reached.wait(timeout=5)
        assert owner.post(f"/api/runs/{run_id}/cancel").status_code == 200
        later = later_resumer.post(f"/api/runs/{run_id}/resume")
        assert later.status_code == 200, later.text
        assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200
        release_first_queue.set()
        stale = stale_resume.result(timeout=5)

    assert stale.status_code == 409, stale.text
    task = _assert_settled(run_id, successor_id, isolated_db, RunStatus.PAUSED)
    assert task.status == "paused"
    paused_seq = max(
        event_seqs(
            run_id, "lifecycle", event="pause_requested", db_path=isolated_db
        )
    )
    resuming = event_seqs(
        run_id, "status", status="resuming", db_path=isolated_db
    )
    assert all(seq < paused_seq for seq in resuming)


def test_startup_resume_skips_cancelled_run_after_admission_race(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    run_id, successor_id = _checkpointed_run(isolated_db, owner)

    from app.runs import lifecycle as runs_lifecycle

    queue_reached, release_queue = _hold_resume_admission(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        startup = pool.submit(
            asyncio.run, runs_lifecycle.resume_interrupted_runs([run_id])
        )
        assert queue_reached.wait(timeout=5)
        assert owner.post(f"/api/runs/{run_id}/cancel").status_code == 200
        release_queue.set()
        startup.result(timeout=5)

    task = _assert_settled(
        run_id, successor_id, isolated_db, RunStatus.CANCELLED
    )
    assert task.status == "cancelled"
    [cancelled_seq] = event_seqs(
        run_id, "status", status="cancelled", db_path=isolated_db
    )
    assert not [
        seq
        for seq in event_seqs(
            run_id, "status", status="resuming", db_path=isolated_db
        )
        if seq > cancelled_seq
    ]


def test_adjudication_rejection_does_not_overwrite_cancel(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    created = _create_run(
        owner, "Safety rejection cancellation", tier="express"
    )
    assert created.status_code == 200
    run_id = str(created.json()["id"])
    runs.update_run_status(run_id, RunStatus.PAUSED, db_path=isolated_db)
    records.add_safety_decision(
        NewSafetyDecision(
            run_id=run_id,
            stage="intake",
            decision="hold",
            reason="Needs review",
            matches=[],
            category="uncertain",
            policy_version="coscientist-safety-v2",
            requires_review=True,
        ),
        db_path=isolated_db,
    )
    [decision] = records.list_safety_decisions(run_id, db_path=isolated_db)
    decision_id = int(decision["id"])

    resolved = Event()
    release_adjudication = Event()
    original_resolve = records.resolve_safety_decision

    def resolve_then_wait(*args: Any, **kwargs: Any) -> bool:
        result = original_resolve(*args, **kwargs)
        resolved.set()
        assert release_adjudication.wait(timeout=5)
        return result

    monkeypatch.setattr(records, "resolve_safety_decision", resolve_then_wait)
    with ThreadPoolExecutor(max_workers=1) as pool:
        adjudication = pool.submit(
            owner.post,
            f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
            json={"resolution": "rejected"},
        )
        assert resolved.wait(timeout=5)
        assert owner.post(f"/api/runs/{run_id}/cancel").status_code == 200
        release_adjudication.set()
        response = adjudication.result(timeout=5)

    assert response.status_code == 409, response.text
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == RunStatus.CANCELLED.value
    [decision] = records.list_safety_decisions(run_id, db_path=isolated_db)
    assert decision["resolution"] == "rejected"


def _started_bootstrap(
    client: TestClient, goal: str, db: str
) -> tuple[str, str]:
    run = _create_run(client, goal, tier="express")
    run_id = str(run.json()["id"])
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    [bootstrap] = store.list_tasks(run_id, db_path=db)
    claimed = store.claim_task("bootstrap-owner", run_id=run_id, db_path=db)
    assert claimed is not None and claimed.id == bootstrap.id
    return run_id, bootstrap.id


@pytest.mark.parametrize(
    "lease_state", ["live", "expired_retryable", "expired_spent"]
)
def test_resume_reuses_precheckpoint_bootstrap_lease(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    lease_state: str,
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, task_id = _started_bootstrap(
        client, f"Resume {lease_state} bootstrap", isolated_db
    )
    original = store.get_task(task_id, db_path=isolated_db)
    assert original is not None
    lease_expiry = time.time() + 3600
    if lease_state != "live":
        lease_expiry = time.time() - 3600
    with store_db.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=?, "
            "attempt=CASE WHEN ? THEN max_attempts ELSE attempt END WHERE id=?",
            (lease_expiry, int(lease_state == "expired_spent"), task_id),
        )

    paused = client.post(f"/api/runs/{run_id}/pause")
    assert paused.status_code == 200
    paused_run = runs.get_run(run_id, db_path=isolated_db)
    assert paused_run is not None and paused_run.status == "paused"
    assert not checkpoints.has_checkpoint(run_id, db_path=isolated_db)

    resumed = client.post(f"/api/runs/{run_id}/resume")

    assert resumed.status_code == 200, resumed.text
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "queued"
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert len(tasks) == 1 and tasks[0].id == task_id
    assert tasks[0].task_type == "engine.bootstrap"
    if lease_state == "live":
        assert tasks[0].status == "leased"
        assert tasks[0].lease_owner == "bootstrap-owner"
        assert (
            store.claim_task(
                "second-worker", run_id=run_id, db_path=isolated_db
            )
            is None
        )
    elif lease_state == "expired_retryable":
        assert tasks[0].status == "queued"
        assert tasks[0].attempt == original.attempt
        reclaimed = store.claim_task(
            "second-worker", run_id=run_id, db_path=isolated_db
        )
        assert reclaimed is not None and reclaimed.id == task_id
        assert reclaimed.attempt == original.attempt + 1
    else:
        assert tasks[0].status == "queued"
        assert tasks[0].attempt == original.max_attempts
        reclaimed = store.claim_task(
            "second-worker", run_id=run_id, db_path=isolated_db
        )
        assert reclaimed is not None and reclaimed.id == task_id
        assert reclaimed.lease_owner == "second-worker"
        assert reclaimed.attempt == original.max_attempts + 1
    events = store_events.list_events(run_id, db_path=isolated_db)
    assert (
        sum(
            event["type"] == "status"
            and event["payload"].get("status") == "resuming"
            for event in events
        )
        == 1
    )


def test_precheckpoint_resume_keeps_owner_and_cancellation_precedence(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    run_id, task_id = _started_bootstrap(
        owner, "Owner-scoped bootstrap resume", isolated_db
    )
    assert owner.post(f"/api/runs/{run_id}/pause").status_code == 200
    foreign = make_client()
    assert (
        foreign.post(
            f"/api/runs/{run_id}/resume",
            headers={"X-Client-ID": "other-client"},
        ).status_code
        == 404
    )
    assert owner.post(f"/api/runs/{run_id}/cancel").status_code == 200

    rejected = owner.post(f"/api/runs/{run_id}/resume")

    assert rejected.status_code == 409
    cancelled_run = runs.get_run(run_id, db_path=isolated_db)
    assert cancelled_run is not None and cancelled_run.status == "cancelled"
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None and task.status == "cancelled"
    assert not any(
        event["type"] == "status"
        and event["payload"].get("status") == "resuming"
        for event in store_events.list_events(run_id, db_path=isolated_db)
    )


def test_resume_recovers_spent_bootstrap_abandoned_after_pause(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, task_id = _started_bootstrap(
        client, "Recover paused bootstrap", isolated_db
    )
    task = store.get_task(task_id, db_path=isolated_db)
    assert task is not None
    with store_db.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0, "
            "attempt=max_attempts "
            "WHERE id=?",
            (task_id,),
        )
    records.add_safety_decision(
        NewSafetyDecision(
            run_id=run_id,
            stage="intake",
            decision="allow",
            reason="intake audit",
            matches=[],
        ),
        db_path=isolated_db,
    )
    assert client.post(f"/api/runs/{run_id}/pause").status_code == 200
    assert lifecycle.abandon_dead_leases(run_id, db_path=isolated_db) == 1
    paused = runs.get_run(run_id, db_path=isolated_db)
    assert paused is not None and paused.status == "paused"
    abandoned = store.get_task(task_id, db_path=isolated_db)
    assert abandoned is not None and abandoned.status == "failed"

    resumed = client.post(f"/api/runs/{run_id}/resume")

    assert resumed.status_code == 200, resumed.text
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "queued"
    [reused] = store.list_tasks(run_id, db_path=isolated_db)
    assert reused.id == task_id and reused.task_type == "engine.bootstrap"
    assert reused.status == "queued" and reused.attempt == task.max_attempts
    assert (
        records.list_safety_decisions(run_id, db_path=isolated_db)[0]["reason"]
        == "intake audit"
    )
    reclaimed = store.claim_task(
        "bootstrap-recovery", run_id=run_id, db_path=isolated_db
    )
    assert reclaimed is not None and reclaimed.id == task_id
    assert reclaimed.attempt == task.max_attempts + 1


@pytest.mark.parametrize(
    "scenario",
    ["ordinary_failure", "cancelled_after_abandon", "paused_permanent_failure"],
)
def test_dead_precheckpoint_bootstrap_is_not_resumable(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, task_id = _started_bootstrap(client, scenario, isolated_db)
    if scenario == "ordinary_failure":
        assert store.fail_task(
            task_id,
            "bootstrap-owner",
            "permanent failure",
            retryable=False,
            db_path=isolated_db,
        )
    elif scenario == "cancelled_after_abandon":
        with store_db.connect(isolated_db) as conn:
            conn.execute(
                "UPDATE scientific_tasks SET lease_expires_at=0, "
                "attempt=max_attempts WHERE id=?",
                (task_id,),
            )
        assert client.post(f"/api/runs/{run_id}/pause").status_code == 200
        assert lifecycle.abandon_dead_leases(run_id, db_path=isolated_db) == 1
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
    else:
        assert client.post(f"/api/runs/{run_id}/pause").status_code == 200
        with store_db.connect(isolated_db) as conn:
            conn.execute(
                "UPDATE scientific_tasks SET attempt=max_attempts WHERE id=?",
                (task_id,),
            )
        assert store.fail_task(
            task_id,
            "bootstrap-owner",
            "permanent budget ceiling",
            retryable=False,
            db_path=isolated_db,
        )

    response = client.post(f"/api/runs/{run_id}/resume")

    assert response.status_code == 409
    run = runs.get_run(run_id, db_path=isolated_db)
    task = store.get_task(task_id, db_path=isolated_db)
    assert run is not None and task is not None and task.status == "failed"
    assert (
        run.status
        == {
            "ordinary_failure": run.status,
            "cancelled_after_abandon": "cancelled",
            "paused_permanent_failure": "paused",
        }[scenario]
    )


# Merge scientist ideas only at the orchestrator; growing pools inside ranking
# or fan-out forks state.


def _node_task(run_id: str, node: str, seq: int, db_path: str) -> Any:
    enqueue_task(
        run_id,
        f"{NODE_TASK_PREFIX}{node}",
        f"engine:{node}:{seq}",
        inputs={"checkpoint_seq": seq},
        priority=90,
        db_path=db_path,
    )
    task = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert task is not None
    return task


def _restored_at(run_id: str, node: str, db_path: str) -> dict[str, Any]:
    state = _task_state(run_id)
    seq = _seed_checkpoint(run_id, state, db_path=db_path)
    task = _node_task(run_id, node, seq, db_path)
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    return engine_tasks_restore._restore_node_task_state(
        task, checkpoint, _Generator(state), {}, db_path
    )


def _seed_hypothesis(run_id: str, db_path: str) -> str:
    hypothesis_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Scientist idea",
            statement="A scientist-proposed mechanism for kinase X.",
            created_by_agent="scientist_manual",
            author="dr-who",
        ),
        db_path=db_path,
    )
    hypotheses.update_hypothesis_state(
        hypothesis_id,
        HypothesisStateChanges(safety_status="allow"),
        db_path=db_path,
    )
    return hypothesis_id


def _seed_review(
    run_id: str, hypothesis_id: str, verdict: str, db_path: str
) -> None:
    records.add_review(
        NewReview(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            reviewer_agent="scientist",
            summary=f"Scientist verdict: {verdict} (by dr-who)",
            critique="The proposed control cannot distinguish the mechanism.",
            author="dr-who",
            verdict=verdict,
        ),
        db_path=db_path,
    )


@pytest.mark.parametrize(
    ("node", "verdict", "admitted", "rankable"),
    [
        ("orchestrator", None, True, True),
        ("orchestrator", "support", True, True),
        ("orchestrator", "oppose", True, False),
        ("ranking", None, False, False),
    ],
)
def test_scientist_idea_is_admitted_only_at_the_orchestrator_boundary(
    isolated_db: str,
    node: str,
    verdict: str | None,
    admitted: bool,
    rankable: bool,
) -> None:
    from co_scientist.models import has_peer_review

    run = seed_run("Admission", profile="express")
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)
    if verdict:
        _seed_review(run.id, hypothesis_id, verdict, isolated_db)

    state = _restored_at(run.id, node, isolated_db)

    assert [h.id for h in state["hypotheses"]] == (
        [hypothesis_id] if admitted else []
    )
    if admitted:
        merged = state["hypotheses"][0]
        assert merged.origin.value == "scientist_manual"
        # A scientist verdict never stands in for the run's own peer review.
        assert not has_peer_review(merged)
        assert (merged.review_disposition == "inaccurate") is (not rankable)
        assert [r.reviewer for r in merged.reviews] == (
            [SCIENTIST_REVIEWER] if verdict else []
        )


def test_authorship_and_screen_survive_a_checkpoint_round_trip(
    isolated_db: str,
) -> None:
    from co_scientist.checkpoint import (
        restore_workflow_state,
        serialize_workflow_state,
    )

    run = seed_run("Provenance", profile="express")
    _seed_hypothesis(run.id, isolated_db)
    state = {**_task_state(run.id)}
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)

    envelope = serialize_workflow_state(state, last_event_seq=0)
    restored = restore_workflow_state(envelope, tool_registry=None)

    hypothesis = restored["hypotheses"][0]
    assert hypothesis.origin.value == "scientist_manual"
    assert hypothesis.enrichments["scientist_author"] == "dr-who"
    assert hypothesis.safety_status == "allow"
    assert (
        drain_hypotheses._payload_author(hypothesis.to_dict())
        == hypothesis.enrichments[engine_tasks_inputs.SCIENTIST_AUTHOR_MARK]
    )


def test_an_unscreened_row_does_not_suppress_the_engine_safety_screen(
    isolated_db: str,
) -> None:
    # Pending is a placeholder, not a finished screen; sending it suppresses the
    # real safety decision.
    from co_scientist.agents.safety import (
        _screen_one_hypothesis,
    )

    run = seed_run("Unscreened", profile="express")
    hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="Unscreened idea",
            statement="A scientist-proposed mechanism for kinase X.",
            created_by_agent="scientist_manual",
            author="dr-who",
        ),
        db_path=isolated_db,
    )

    state = _restored_at(run.id, "orchestrator", isolated_db)

    merged = state["hypotheses"][0]
    assert merged.safety_status is None
    _screen_one_hypothesis(merged)
    assert merged.safety_status == "allow"


def test_the_drain_reattributes_an_idea_whose_row_is_gone(
    isolated_db: str,
) -> None:
    from tests._drain_helpers import _persist

    run = seed_run("Reattribute", profile="express")
    _seed_hypothesis(run.id, isolated_db)
    state: dict[str, Any] = {"hypotheses": []}
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)
    payload = [h.to_dict() for h in state["hypotheses"]]
    payload[0]["id"] = "unseen-engine-id"
    other = seed_run("Fresh store", profile="express")

    _persist(
        run_id=other.id,
        final_state={
            "hypotheses": payload,
            "articles": [],
            "tournament_matchups": [],
            "proximity_graph": {},
            "meta_review": {},
            "research_overview": {},
        },
        db_path=isolated_db,
    )

    rows = hypotheses.list_hypotheses(other.id, isolated_db)
    assert [row["author"] for row in rows] == ["dr-who"]
    assert rows[0]["created_by_agent"] == "scientist_manual"


def test_admitting_the_same_idea_twice_creates_one_pool_member(
    isolated_db: str,
) -> None:
    run = seed_run("Idempotent", profile="express")
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)
    _seed_review(run.id, hypothesis_id, "revise", isolated_db)
    state = {**_task_state(run.id)}

    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)

    assert [h.id for h in state["hypotheses"]] == [hypothesis_id]
    assert len(state["hypotheses"][0].reviews) == 1


_LATE_CONTRIB_WORKER = "late-contrib-test"


async def _drain_until_finalize_enqueued(run_id: str, isolated_db: str) -> None:
    for _ in range(500):
        tasks = store.list_tasks(run_id, db_path=isolated_db)
        if any(t.task_type == "engine.finalize" for t in tasks):
            return
        worked = await task_worker.run_once(
            _LATE_CONTRIB_WORKER, run_id=run_id, db_path=isolated_db
        )
        assert worked, "run finished before finalize was ever enqueued"
    raise AssertionError("finalize never appeared inside the task cap")


@pytest.mark.asyncio
async def test_late_contribution_reopens_the_run_once_it_completes(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Contributions arriving after the last orchestrator need a continuation
    # once finalization settles.
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    created = _create_run(client, "Late contribution reopen", tier="express")
    run_id = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200

    await _drain_until_finalize_enqueued(run_id, isolated_db)
    pre_status = runs.get_run(run_id, db_path=isolated_db)
    assert pre_status is not None and pre_status.status != "completed"

    posted = client.post(
        f"/api/runs/{run_id}/messages",
        json={"content": "also consider off-target kinase effects"},
    )
    assert posted.status_code == 200
    assert posted.json()["continuation_task_id"] is None
    assert messages.get_pending_steering(run_id, db_path=isolated_db)

    await task_worker.run_run_until_idle(
        run_id, _LATE_CONTRIB_WORKER, db_path=isolated_db
    )

    reopened = runs.get_run(run_id, db_path=isolated_db)
    assert reopened is not None and reopened.status == "completed", (
        reopened.error if reopened else None
    )
    tasks_after = store.list_tasks(run_id, db_path=isolated_db)
    assert any(
        task.task_type == "engine.node.orchestrator"
        and task.provenance.get("behavior") == "scientist-directed-continuation"
        for task in tasks_after
    )
    lifecycle_events = [
        event["payload"]
        for event in store_events.list_events(run_id, db_path=isolated_db)
        if event["payload"].get("event") == "reopened_for_scientist_input"
    ]
    assert lifecycle_events
    assert not messages.get_pending_steering(run_id, db_path=isolated_db)

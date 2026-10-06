from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.llm import ModelCallStats, record_call
from co_scientist.models import (
    Hypothesis,
)

import app.engine_tasks.fanout as engine_tasks_fanout_generation
from app import engine_tasks, safety, task_worker
from app.config import settings
from app.engine_tasks import inputs as engine_tasks_inputs
from app.engine_tasks import node as engine_tasks_node
from app.engine_tasks import ranking as engine_tasks_ranking
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.fanout import _GenerationPlan, _StrategyInputs
from app.engine_tasks.fanout_aggregates import _AggregateSpec
from app.engine_tasks.support import ExactSuccessor, TaskCommit
from app.safety.types import SafetyDecision
from app.store import checkpoints, db, records, runs
from app.store import events as store_events
from app.store import retrieval_calls as retrieval
from app.store import tasks as store
from app.store import tasks_lifecycle as lifecycle
from app.store.models import RunStatus as StoreRunStatus
from app.store.records import NewSafetyDecision
from tests._client import create_run as _create_run
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _Generator,
    _install_runtime,
    _milestones,
    _patch_generator,
    _patch_task_node,
    _RankingSeed,
    _run_ranking_node,
    _seed_checkpoint,
    _seed_ranking_node,
    _task_events,
    _task_state,
)
from tests._store_helpers import enqueue_task, seed_run


class _PauseDuringPrepare:
    def __init__(self, client: Any, run_id: str, state: dict[str, Any]) -> None:
        self.client = client
        self.run_id = run_id
        self.state = state

    async def prepare_task_state(self, *_: Any, **__: Any) -> dict[str, Any]:
        response = self.client.post(f"/api/runs/{self.run_id}/pause")
        assert response.status_code == 200
        return self.state


def _start_bootstrap(
    monkeypatch: pytest.MonkeyPatch, db_path: str, goal: str = "Bootstrap race"
) -> tuple[Any, str, Any]:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    created = _create_run(client, goal)
    run_id = str(created.json()["id"])
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    task = store.claim_task("bootstrap-worker", run_id=run_id, db_path=db_path)
    assert task is not None
    return client, run_id, task


def _stub_bootstrap_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_intake(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(
        engine_tasks_inputs, "_screen_bootstrap_intake", no_intake
    )
    monkeypatch.setattr(
        engine_tasks_inputs, "sync_engine_llm_backend", lambda *_: None
    )


def _pause_during_bootstrap_prepare(
    monkeypatch: pytest.MonkeyPatch, db_path: str
) -> tuple[Any, str, Any]:
    client, run_id, task = _start_bootstrap(
        monkeypatch, db_path, "Pause during bootstrap prepare"
    )
    _stub_bootstrap_providers(monkeypatch)
    _patch_generator(
        monkeypatch, _PauseDuringPrepare(client, run_id, _task_state(run_id))
    )
    monkeypatch.setattr(
        engine_tasks_support,
        "_enqueue_node_portfolio",
        _enqueue_bootstrap_successor,
    )
    return client, run_id, task


def _resume_after_paused_snapshot(
    monkeypatch: pytest.MonkeyPatch, client: Any, run_id: str
) -> list[bool]:
    get_run = runs.get_run
    resumed: list[bool] = []

    def interleaved_get(
        requested: str, db_path: str | None = None, conn: Any | None = None
    ) -> Any:
        run = get_run(requested, db_path=db_path, conn=conn)
        if (
            requested == run_id
            and run is not None
            and run.status == "paused"
            and not resumed
        ):
            resumed.append(True)
            response = client.post(f"/api/runs/{run_id}/resume")
            assert response.status_code == 200
        return run

    monkeypatch.setattr(runs, "get_run", interleaved_get)
    return resumed


def _enqueue_bootstrap_successor(
    task: Any,
    _state: dict[str, Any],
    _successor: str | None,
    successor_type: str,
    conn: Any,
) -> Any:
    return enqueue_task(
        task.run_id,
        successor_type,
        f"{successor_type}:after:{task.id}",
        inputs={"checkpoint_seq": 1},
        dependencies=(task.id,),
        conn=conn,
    )


def _replace_expired_bootstrap_lease(
    client: Any, run_id: str, original: Any, db_path: str
) -> Any:
    with db.transaction(db_path) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (original.id,),
        )
    assert store.claim_task("new-bootstrap", run_id=run_id) is None
    failed = store.get_task(original.id, db_path=db_path)
    assert failed is not None and failed.status == "failed"
    assert "may have accepted" in (failed.error or "")
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    replacement = store.claim_task("old-bootstrap", run_id=run_id)
    assert replacement is not None
    assert replacement.attempt == original.attempt + 1
    return replacement


@pytest.mark.asyncio
async def test_bootstrap_rechecks_pause_after_resume_before_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, run_id, task = _pause_during_bootstrap_prepare(
        monkeypatch, isolated_db
    )
    resumed = _resume_after_paused_snapshot(monkeypatch, client, run_id)

    result = await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    assert resumed == [True]
    assert result.get("status") != "paused"
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "queued"
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert (
        checkpoint is not None
        and checkpoint["stage"] == f"engine_task:{task.id}"
    )
    assert checkpoint["state"]["resume_successor"] == "engine.node.supervisor"
    assert lifecycle.complete_task(
        task.id, "bootstrap-worker", result, db_path=isolated_db
    )
    claim = store.claim_task(
        "supervisor-worker", run_id=run_id, db_path=isolated_db
    )
    assert claim is not None and claim.task_type == "engine.node.supervisor"
    assert len(store.list_tasks(run_id, db_path=isolated_db)) == 2


@pytest.mark.asyncio
async def test_bootstrap_pause_without_resume_commits_paused_checkpoint(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run_id, task = _pause_during_bootstrap_prepare(monkeypatch, isolated_db)

    result = await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    assert result["status"] == "paused"
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task_paused:{task.id}"
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "paused"
    assert len(store.list_tasks(run_id, db_path=isolated_db)) == 1


def test_resume_keeps_intake_safety_artifacts_for_leased_bootstrap(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, run_id, _task = _start_bootstrap(monkeypatch, isolated_db)
    records.add_safety_decision(
        NewSafetyDecision(
            run_id=run_id,
            stage="intake",
            decision="allow",
            reason="intake screen completed",
            matches=[],
        ),
        db_path=isolated_db,
    )
    store_events.append_event(
        run_id,
        "safety",
        {"event": "intake_decision_persisted"},
        db_path=isolated_db,
    )
    assert client.post(f"/api/runs/{run_id}/pause").status_code == 200

    resumed = client.post(f"/api/runs/{run_id}/resume")

    assert resumed.status_code == 200
    decisions = records.list_safety_decisions(run_id, db_path=isolated_db)
    assert [decision["reason"] for decision in decisions] == [
        "intake screen completed"
    ]
    assert any(
        event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
        for event in store_events.list_events(run_id, db_path=isolated_db)
    )
    assert any(
        event["type"] == "safety"
        and event["payload"].get("event") == "intake_decision_persisted"
        for event in store_events.list_events(run_id, db_path=isolated_db)
    )


def _forbid_contextual_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patch both wrapper and direct-import namespaces so accidental contextual
    # calls cannot evade the guard.

    async def _fail_if_called(*_: Any, **__: Any) -> Any:
        raise AssertionError(
            "offline-backed run escalated to the contextual safety model"
        )

    monkeypatch.setattr(safety, "screen_contextual", _fail_if_called)
    monkeypatch.setattr(
        engine_tasks, "screen_contextual", _fail_if_called, raising=False
    )


async def _advance_to_supervisor(
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    db_path: str,
) -> Any:
    bootstrap = engine_tasks.enqueue_bootstrap(run_id, db_path=db_path)
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    generator = _Generator(_task_state(run_id))
    _patch_generator(monkeypatch, generator, screen=True)
    result = await engine_tasks.execute_bootstrap(leased, db_path=db_path)
    assert lifecycle.complete_task(
        bootstrap.id, "worker", result, db_path=db_path
    )
    supervisor = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert supervisor is not None
    return supervisor


@pytest.mark.asyncio
async def test_bootstrap_commits_state_and_enqueues_supervisor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = seed_run("Task-level science")
    bootstrap = engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == bootstrap.id
    generator = _Generator(_task_state(run.id))
    _patch_generator(monkeypatch, generator, screen=True)

    result = await engine_tasks.execute_bootstrap(leased, db_path=isolated_db)
    assert lifecycle.complete_task(
        leased.id, "worker", result, db_path=isolated_db
    )

    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 1
    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert [task.task_type for task in tasks] == [
        "engine.bootstrap",
        "engine.node.supervisor",
        "engine.node.generate",
    ]
    assert [task.dependencies for task in tasks] == [
        (),
        (bootstrap.id,),
        (tasks[1].id,),
    ]


@pytest.mark.asyncio
async def test_bootstrap_never_escalates_an_offline_backed_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Offline bootstrap must not ask a contextual model whose uncertain verdict
    # could pause deterministic runs.
    run = seed_run(
        "Task-level science", llm_backend="offline", db_path=isolated_db
    )
    engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    _patch_generator(monkeypatch, _Generator(_task_state(run.id)))
    _forbid_contextual_escalation(monkeypatch)

    result = await engine_tasks.execute_bootstrap(leased, db_path=isolated_db)

    assert result.get("status") != "withheld"
    assert "checkpoint_seq" in result
    refreshed = runs.get_run(run.id, db_path=isolated_db)
    assert refreshed is not None and refreshed.status != "paused"


async def _drain_ranking_matches(
    run_id: str, db_path: str
) -> tuple[Any, list[int], int]:
    # Waves observe predecessor checkpoints sequentially; replay a match to
    # exercise idempotency.
    observed_sequences: list[int] = []
    committed = 0
    index = 0
    while True:
        match = store.claim_task(
            f"match-{index}", run_id=run_id, db_path=db_path
        )
        assert match is not None
        if match.task_type != engine_tasks_support.RANKING_MATCH_TASK:
            return match, observed_sequences, committed
        observed_sequences.append(int(match.inputs["checkpoint_seq"]))
        result = await engine_tasks_ranking.execute_ranking_match(
            match, db_path=db_path
        )
        if index == 0:
            replay = await engine_tasks_ranking.execute_ranking_match(
                match, db_path=db_path
            )
            assert replay["replayed"] is True
        committed = int(result["matches_committed"])
        assert lifecycle.complete_task(
            match.id, f"match-{index}", result, db_path=db_path
        )
        index += 1


async def _judge_with_telemetry(
    *_: Any, **kwargs: Any
) -> tuple[str, dict[str, Any]]:
    record_call("fixture-model", ModelCallStats(calls=1, prompt_tokens=5))
    return "a", {
        "decision_summary": "A is stronger",
        "confidence_level": "high",
        "debate_turns": int(kwargs["debate_turns"]),
        "debate_transcript": [],
        "judge_model": "fixture-model",
    }


@pytest.mark.asyncio
async def test_ranking_matches_are_separate_sequential_checkpointed_tasks(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from co_scientist.checkpoint import restore_workflow_state

    run = seed_run("Task-level science")
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=3,
            tournament_pairs=3,
            idempotency_key="ranking-node",
        ),
        isolated_db,
    )
    import co_scientist.agents.ranking.operations as ranking_module

    monkeypatch.setattr(ranking_module, "judge_matchup", _judge_with_telemetry)
    await _run_ranking_node(run.id, isolated_db)

    finalizer, observed, committed = await _drain_ranking_matches(
        run.id, isolated_db
    )
    assert observed == sorted(set(observed))
    assert committed == 3, "the whole round is judged exactly once"
    result = await engine_tasks_ranking.execute_ranking_finalize(
        finalizer, db_path=isolated_db
    )
    assert lifecycle.complete_task(
        finalizer.id,
        finalizer.lease_owner or "finalizer",
        result,
        db_path=isolated_db,
    )

    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    assert len(restored["tournament_matchups"]) == 3
    assert sum(item.total_matches for item in restored["hypotheses"]) == 6
    # Sequential match usage rides successor inputs until the final
    # checkpoint; intermediate commits omit metrics.
    usage = restored["metrics"].model_usage["ranking::fixture-model"]
    assert (usage["calls"], usage["prompt_tokens"]) == (3, 15)
    assert sum(
        task.task_type == engine_tasks_support.RANKING_MATCH_TASK
        for task in store.list_tasks(run.id, db_path=isolated_db)
    ) == len(observed)
    assert _milestones(run.id, db_path=isolated_db) == [
        "Tournament complete (iteration 0, 3 matches)"
    ]
    [event] = _task_events(run.id, "ranking", db_path=isolated_db)
    assert event["payload"]["successor"] == "orchestrator"


@pytest.mark.asyncio
async def test_inflight_pause_checkpoints_exact_successor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bootstrap already planned a successor; pause must not add another, and
    # resume reuses that row.
    run = seed_run("Task-level science")
    supervisor = await _advance_to_supervisor(run.id, monkeypatch, isolated_db)
    before_pause = store.list_tasks(run.id, db_path=isolated_db)

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        runs.update_run_status(run.id, StoreRunStatus.PAUSED)
        return state, "generate"

    _patch_task_node(monkeypatch, execute)
    paused = await engine_tasks.execute_node_task(
        supervisor, db_path=isolated_db
    )
    assert lifecycle.complete_task(
        supervisor.id, "worker", paused, db_path=isolated_db
    )
    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["state"]["resume_successor"] == "engine.node.generate"
    assert len(store.list_tasks(run.id, db_path=isolated_db)) == len(
        before_pause
    )

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )
    assert resumed.task_type == "engine.node.generate"
    assert resumed.id == before_pause[-1].id, "reuses the pre-planned row"


def _cancel_after_second_run_read(run_id: str, client: Any) -> Any:
    real_get_run = runs.get_run
    run_reads = 0

    def cancel_after_read(
        requested_run_id: str,
        db_path: str | None = None,
        conn: Any | None = None,
    ) -> Any:
        nonlocal run_reads
        run = real_get_run(requested_run_id, db_path=db_path, conn=conn)
        if requested_run_id == run_id:
            run_reads += 1
            if run_reads == 2:
                response = client.post(f"/api/runs/{run_id}/cancel")
                assert response.status_code == 200
        return run

    return cancel_after_read


@pytest.mark.asyncio
async def test_cancel_after_bootstrap_read_cannot_be_overwritten(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, run_id, task = _start_bootstrap(monkeypatch, isolated_db)
    real_get_run = runs.get_run
    monkeypatch.setattr(
        runs, "get_run", _cancel_after_second_run_read(run_id, client)
    )
    prepared: list[bool] = []

    async def prepare_without_providers(*_: Any, **__: Any) -> tuple[Any, ...]:
        prepared.append(True)
        return {}, object()

    async def emit_without_persisting(*_: Any, **__: Any) -> None:
        return None

    _stub_bootstrap_providers(monkeypatch)
    monkeypatch.setattr(
        engine_tasks_inputs,
        "_prepare_bootstrap_state",
        prepare_without_providers,
    )
    monkeypatch.setattr(
        engine_tasks_inputs,
        "_save_state_and_enqueue",
        lambda *_: (1, "successor"),
    )
    monkeypatch.setattr(
        engine_tasks_inputs,
        "make_emitter",
        lambda *_args, **_kwargs: emit_without_persisting,
    )

    result = await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    refreshed = real_get_run(run_id, db_path=isolated_db)
    assert refreshed is not None and refreshed.status == "cancelled"
    assert result.get("status") == "cancelled"
    assert prepared == []
    persisted = store.get_task(task.id, db_path=isolated_db)
    assert persisted is not None and persisted.status == "cancelled"


def _assert_no_intake_verdict_applied(run_id: str, db_path: str) -> list[Any]:
    assert [
        item
        for item in records.list_safety_decisions(run_id, db_path=db_path)
        if item["stage"] == "intake"
    ] == []
    events = store_events.list_events(run_id, db_path=db_path)
    assert not any(event["type"] == "safety.intake" for event in events)
    return events


async def _hold_intake_screen(
    monkeypatch: pytest.MonkeyPatch, task: Any, decision: str, db_path: str
) -> tuple[asyncio.Task[Any], asyncio.Event]:
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_screen(*_: Any, **__: Any) -> SafetyDecision:
        started.set()
        await release.wait()
        return SafetyDecision(
            stage="intake", decision=decision, reason=f"injected {decision}"
        )

    _install_runtime(monkeypatch).screen = delayed_screen
    bootstrap = asyncio.create_task(
        engine_tasks.execute_bootstrap(task, db_path=db_path)
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    return bootstrap, release


@pytest.mark.parametrize("decision", ["block", "hold"])
@pytest.mark.asyncio
async def test_cancel_during_bootstrap_safety_gate_keeps_cancelled_status(
    decision: str,
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, run_id, task = _start_bootstrap(monkeypatch, isolated_db)
    bootstrap, release = await _hold_intake_screen(
        monkeypatch, task, decision, isolated_db
    )
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
    cancel_seq = next(
        event["seq"]
        for event in store_events.list_events(run_id, db_path=isolated_db)
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    release.set()

    with pytest.raises(task_worker._LeaseLostError):
        await bootstrap

    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "cancelled"
    events = _assert_no_intake_verdict_applied(run_id, isolated_db)
    assert not any(
        event["type"] == "status"
        and event["seq"] > cancel_seq
        and event["payload"].get("status") in {"blocked", "paused"}
        for event in events
    )


@pytest.mark.parametrize("decision", ["block", "hold"])
@pytest.mark.asyncio
async def test_stale_bootstrap_lease_cannot_apply_intake_stop(
    decision: str,
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, run_id, original = _start_bootstrap(monkeypatch, isolated_db)
    bootstrap, release = await _hold_intake_screen(
        monkeypatch, original, decision, isolated_db
    )
    _replace_expired_bootstrap_lease(client, run_id, original, isolated_db)
    release.set()

    with pytest.raises(task_worker._LeaseLostError):
        await bootstrap

    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "queued"
    events = _assert_no_intake_verdict_applied(run_id, isolated_db)
    assert not any(
        event["type"] == "status"
        and event["payload"].get("status") in {"blocked", "paused"}
        for event in events
    )


@pytest.mark.asyncio
async def test_replaced_bootstrap_lease_cannot_prepare_paused_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, run_id, original = _start_bootstrap(monkeypatch, isolated_db)
    replacement = _replace_expired_bootstrap_lease(
        client, run_id, original, isolated_db
    )
    runs.update_run_status(run_id, StoreRunStatus.PAUSED, db_path=isolated_db)
    prepared: list[bool] = []

    async def fake_prepare(*_: Any, **__: Any) -> tuple[Any, ...]:
        prepared.append(True)
        return {}, object()

    _stub_bootstrap_providers(monkeypatch)
    monkeypatch.setattr(
        engine_tasks_inputs, "_prepare_bootstrap_state", fake_prepare
    )

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_bootstrap(original, db_path=isolated_db)

    assert prepared == []
    assert (
        runs.mark_bootstrap_running(
            run_id,
            replacement.id,
            replacement.lease_owner,
            replacement.attempt,
            db_path=isolated_db,
        )
        == StoreRunStatus.PAUSED.value
    )


_OWNER = {"X-Client-ID": "cancel-commit-owner"}


def _owned_running_run(db_path: str) -> tuple[Any, str]:
    client = make_client()
    created = _create_run(
        client,
        "Study a durable cancellation boundary",
        headers=_OWNER,
        tier="express",
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    runs.update_run_status(run_id, StoreRunStatus.RUNNING, db_path=db_path)
    return client, run_id


def _leased_task(
    run_id: str, task_type: str, key: str, db_path: str
) -> tuple[Any, int]:
    checkpoint_seq = _seed_checkpoint(
        run_id, _task_state(run_id), db_path=db_path
    )
    queued = enqueue_task(
        run_id,
        task_type,
        key,
        inputs={"checkpoint_seq": checkpoint_seq},
        db_path=db_path,
    )
    task = store.claim_task(
        "cancel-race-worker", run_id=run_id, db_path=db_path
    )
    assert task is not None and task.id == queued.id
    return task, checkpoint_seq


def _control_run(client: Any, run_id: str, verb: str, status: str) -> None:
    response = client.post(f"/api/runs/{run_id}/{verb}", headers=_OWNER)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == status


def _race_node_step(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    race: Callable[[], None],
) -> None:
    real = getattr(engine_tasks_node, name)

    async def raced(*args: Any, **kwargs: Any) -> Any:
        race()
        return await real(*args, **kwargs)

    monkeypatch.setattr(engine_tasks_node, name, raced)


def _prepare_node_without_providers(
    monkeypatch: pytest.MonkeyPatch,
    task: Any,
    checkpoint_seq: int,
    node: str,
    state: dict[str, Any],
    db_path: str,
) -> None:
    monkeypatch.setattr(
        engine_tasks_node,
        "_prepare_node_task",
        lambda *_: (state, TaskCommit(task, checkpoint_seq, db_path), node),
    )


@pytest.mark.asyncio
async def test_cancel_completed_after_node_status_check_blocks_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "cancel-race-node", isolated_db
    )
    _prepare_node_without_providers(
        monkeypatch,
        task,
        checkpoint_seq,
        "supervisor",
        _task_state(run_id),
        isolated_db,
    )

    async def execute_node(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        return state, "generate"

    _patch_task_node(monkeypatch, execute_node)
    _race_node_step(
        monkeypatch,
        "_commit_node_result",
        lambda: _control_run(client, run_id, "cancel", "cancelled"),
    )

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_node_task(task, db_path=isolated_db)

    latest = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [task.id]
    cancelled_task = store.get_task(task.id, db_path=isolated_db)
    assert cancelled_task is not None and cancelled_task.status == "cancelled"
    cancelled_run = runs.get_run(run_id, db_path=isolated_db)
    assert cancelled_run is not None and cancelled_run.status == "cancelled"


@pytest.mark.asyncio
async def test_pause_after_node_status_refresh_keeps_successor_unclaimable(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "pause-successor-race", isolated_db
    )
    _prepare_node_without_providers(
        monkeypatch,
        task,
        checkpoint_seq,
        "supervisor",
        _task_state(run_id),
        isolated_db,
    )

    async def execute_node(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        state["metrics"].llm_calls = 7
        return state, "generate"

    _patch_task_node(monkeypatch, execute_node)
    _race_node_step(
        monkeypatch,
        "_commit_node_result",
        lambda: _control_run(client, run_id, "pause", "paused"),
    )

    result = await engine_tasks.execute_node_task(task, db_path=isolated_db)

    assert result["status"] == "paused"
    assert lifecycle.complete_task(
        task.id, "cancel-race-worker", result, db_path=isolated_db
    )
    latest = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq + 1
    assert latest["stage"] == f"engine_task_paused:{task.id}"
    assert latest["state"]["resume_successor"] == "engine.node.generate"
    metrics = retrieval.get_run_metrics(run_id, db_path=isolated_db)
    assert metrics is not None and metrics["llm_calls"] == 7
    [completion] = _task_events(run_id, "supervisor", db_path=isolated_db)
    assert completion["payload"]["successor"] == "generate"
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [task.id]
    assert (
        store.claim_task("claim-check", run_id=run_id, db_path=isolated_db)
        is None
    )

    resumed = client.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    queued = [
        row
        for row in store.list_tasks(run_id, db_path=isolated_db)
        if row.status == "queued"
    ]
    assert [row.task_type for row in queued] == ["engine.node.generate"]


def test_pause_api_serializes_queued_revocation_with_node_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "pause-api-transaction", isolated_db
    )
    commit_finished = Event()
    commit_attempted = Event()
    commit_result: list[tuple[int, str | None]] = []
    commit_errors: list[BaseException] = []

    def commit_successor() -> None:
        try:
            commit_result.append(
                engine_tasks_support._save_state_and_enqueue(
                    TaskCommit(task, checkpoint_seq, isolated_db),
                    _task_state(run_id),
                    "generate",
                    pause_if_requested=True,
                )
            )
        except BaseException as exc:
            commit_errors.append(exc)
        finally:
            commit_finished.set()

    original_pause_tasks = lifecycle.pause_run_tasks
    original_transaction = db.transaction
    commit_thread: Thread | None = None

    @contextmanager
    def signal_commit_transaction(
        db_path: str | None = None,
    ) -> Iterator[Any]:
        commit_attempted.set()
        with original_transaction(db_path) as conn:
            yield conn

    def pause_tasks_then_race(
        target_run_id: str, *, db_path: str | None = None, conn: Any = None
    ) -> int:
        nonlocal commit_thread
        changed = original_pause_tasks(
            target_run_id, db_path=db_path, conn=conn
        )
        commit_attempted.clear()
        commit_thread = Thread(target=commit_successor)
        commit_thread.start()
        assert commit_attempted.wait(2), "commit did not reach its transaction"
        assert not commit_finished.wait(0.2), "commit escaped pause transaction"
        return changed

    monkeypatch.setattr(lifecycle, "pause_run_tasks", pause_tasks_then_race)
    monkeypatch.setattr(db, "transaction", signal_commit_transaction)
    response = client.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paused"
    assert commit_thread is not None
    commit_thread.join(timeout=5)
    assert not commit_thread.is_alive()
    assert not commit_errors
    assert commit_result == [(checkpoint_seq + 1, None)]
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task_paused:{task.id}"
    assert not any(
        row.status == "queued"
        for row in store.list_tasks(run_id, db_path=isolated_db)
    )


@pytest.mark.asyncio
async def test_cancel_before_review_fanout_transaction_blocks_enqueue(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.review", "cancel-review-fanout", isolated_db
    )
    state = {
        **_task_state(run_id),
        "hypotheses": [Hypothesis(text="A reviewable mechanism")],
    }
    _prepare_node_without_providers(
        monkeypatch, task, checkpoint_seq, "review", state, isolated_db
    )
    _race_node_step(
        monkeypatch,
        "_dispatch_node_fanout",
        lambda: _control_run(client, run_id, "cancel", "cancelled"),
    )

    with suppress(task_worker._LeaseLostError):
        await engine_tasks.execute_node_task(task, db_path=isolated_db)

    assert [
        row.task_type for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [task.task_type]
    latest = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq


def _commit_node(
    task: Any, seq: int, run_id: str, db_path: str
) -> tuple[int, str | None]:
    return engine_tasks_support._save_state_and_enqueue(
        TaskCommit(task, seq, db_path), _task_state(run_id), "generate"
    )


def _commit_exact(
    task: Any, seq: int, run_id: str, db_path: str
) -> tuple[int, str]:
    return engine_tasks_support._save_state_and_enqueue_exact(
        TaskCommit(task, seq, db_path),
        _task_state(run_id),
        ExactSuccessor(
            task_type="engine.ranking.match",
            inputs={"match_index": 2},
            idempotency_key="match:{checkpoint_seq}",
        ),
    )


def _commit_generation_plan(
    task: Any, seq: int, run_id: str, db_path: str
) -> Any:
    plan = _GenerationPlan(
        task_specs=[],
        inputs=_StrategyInputs(
            literature=None,
            reference_index=SimpleNamespace(text="", sources=[]),
        ),
        aggregate_spec=_AggregateSpec(
            task_type=engine_tasks_support.GENERATION_AGGREGATE_TASK,
            priority=81,
            key_prefix="generation",
        ),
    )
    envelope = {
        "last_event_seq": store_events.latest_event_seq(
            run_id, db_path=db_path
        ),
        "state": {},
    }
    return engine_tasks_fanout_generation._commit_generation_fanout(
        task, seq, envelope, plan, db_path
    )


def _re_lease_same_owner(run_id: str, stale: Any, db_path: str) -> None:
    with db.transaction(db_path) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (stale.id,),
        )
    assert (
        store.claim_task(
            stale.lease_owner, lease_seconds=60, run_id=run_id, db_path=db_path
        )
        is None
    )
    failed = store.get_task(stale.id, db_path=db_path)
    assert failed is not None and failed.status == "failed"
    assert "may have accepted" in (failed.error or "")
    assert lifecycle.retry_task(
        stale.id,
        reason="owner authorized replay after ambiguous lease expiry",
        db_path=db_path,
    )
    runs.update_run_status(run_id, StoreRunStatus.QUEUED, db_path=db_path)
    current = store.claim_task(
        stale.lease_owner, lease_seconds=60, run_id=run_id, db_path=db_path
    )
    assert current is not None and current.id == stale.id
    assert current.attempt == stale.attempt + 1


@pytest.mark.parametrize("cause", ["run-completed", "re-leased"])
@pytest.mark.parametrize(
    "commit", [_commit_node, _commit_exact, _commit_generation_plan]
)
def test_a_revoked_task_cannot_commit_at_any_boundary(
    isolated_db: str, commit: Callable[..., Any], cause: str
) -> None:
    _client, run_id = _owned_running_run(isolated_db)
    task, seq = _leased_task(
        run_id, "engine.node.generate", f"revoked-{cause}", isolated_db
    )
    if cause == "run-completed":
        runs.update_run_status(
            run_id, StoreRunStatus.COMPLETED, db_path=isolated_db
        )
    else:
        _re_lease_same_owner(run_id, task, isolated_db)

    with pytest.raises(task_worker._LeaseLostError):
        commit(task, seq, run_id, isolated_db)

    latest = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == seq
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [task.id]

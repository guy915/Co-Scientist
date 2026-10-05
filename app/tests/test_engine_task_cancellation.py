from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.constants import NOT_VIABLE_SCORE
from co_scientist.models import (
    Article,
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
from app.store import checkpoints, db, records, runs
from app.store import events as store_events
from app.store import hypotheses as store_hypotheses
from app.store import retrieval_calls as retrieval
from app.store import tasks as store
from app.store import tasks_lifecycle as lifecycle
from app.store.hypotheses import NewHypothesis
from app.store.models import RunRow
from app.store.models import RunStatus as StoreRunStatus
from app.store.records import NewReview, NewSafetyDecision
from tests._client import create_run as _create_run
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _add_fixture_review,
    _Generator,
    _install_plain_fake_judge,
    _install_runtime,
    _milestones,
    _patch_generator,
    _patch_task_node,
    _seed_checkpoint,
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


def _start_bootstrap(db_path: str) -> tuple[Any, str, Any]:
    client = make_client()
    created = _create_run(client, "Pause during bootstrap prepare")
    run_id = str(created.json()["id"])
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    task = store.claim_task("bootstrap-worker", run_id=run_id, db_path=db_path)
    assert task is not None
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


@pytest.mark.asyncio
async def test_bootstrap_rechecks_pause_after_resume_before_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id, task = _start_bootstrap(isolated_db)
    state = _task_state(run_id)
    generator = _PauseDuringPrepare(client, run_id, state)
    resumed = _resume_after_paused_snapshot(monkeypatch, client, run_id)

    async def no_intake(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(
        engine_tasks_inputs, "_screen_bootstrap_intake", no_intake
    )
    _patch_generator(monkeypatch, generator)
    monkeypatch.setattr(
        engine_tasks_inputs, "sync_engine_llm_backend", lambda *_: None
    )
    monkeypatch.setattr(
        engine_tasks_support,
        "_enqueue_node_portfolio",
        _enqueue_bootstrap_successor,
    )

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
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert len(tasks) == 2
    assert sum(item.task_type == "engine.bootstrap" for item in tasks) == 1
    assert any(item.task_type == "engine.node.supervisor" for item in tasks)
    assert lifecycle.complete_task(
        task.id, "bootstrap-worker", result, db_path=isolated_db
    )
    claim = store.claim_task(
        "supervisor-worker", run_id=run_id, db_path=isolated_db
    )
    assert claim is not None and claim.task_type == "engine.node.supervisor"


@pytest.mark.asyncio
async def test_bootstrap_pause_without_resume_commits_paused_checkpoint(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id, task = _start_bootstrap(isolated_db)
    generator = _PauseDuringPrepare(client, run_id, _task_state(run_id))

    async def no_intake(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(
        engine_tasks_inputs, "_screen_bootstrap_intake", no_intake
    )
    _patch_generator(monkeypatch, generator)
    monkeypatch.setattr(
        engine_tasks_inputs, "sync_engine_llm_backend", lambda *_: None
    )
    monkeypatch.setattr(
        engine_tasks_support,
        "_enqueue_node_portfolio",
        _enqueue_bootstrap_successor,
    )

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
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id, _task = _start_bootstrap(isolated_db)
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


def test_scientist_inputs_merge_into_engine_state_once(
    isolated_db: str,
) -> None:
    run = seed_run("Scientist loop")
    hypothesis_id = store_hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="Scientist idea",
            statement="A scientist-proposed mechanism",
            created_by_agent="scientist_manual",
            author="researcher",
        ),
        db_path=isolated_db,
    )
    records.add_review(
        NewReview(
            run_id=run.id,
            hypothesis_id=hypothesis_id,
            reviewer_agent="scientist",
            summary="Scientist verdict: oppose (by researcher)",
            critique="The proposed control cannot distinguish the mechanism.",
        ),
        db_path=isolated_db,
    )
    state = _task_state(run.id)

    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)

    merged = state["hypotheses"]
    assert [hypothesis.id for hypothesis in merged] == [hypothesis_id]
    assert merged[0].origin.value == "scientist_manual"
    assert len(merged[0].reviews) == 1
    assert merged[0].reviews[0].overall_score == NOT_VIABLE_SCORE
    assert "cannot distinguish" in merged[0].reviews[0].constructive_feedback


def test_scientist_input_reopens_completed_engine_run(isolated_db: str) -> None:
    run = seed_run("Continuation")
    checkpoint_seq = _seed_checkpoint(
        run.id,
        _task_state(run.id),
        stage="engine_task:final",
        db_path=isolated_db,
    )
    runs.update_run_status(
        run.id, StoreRunStatus.COMPLETED, db_path=isolated_db
    )

    task = engine_tasks.enqueue_scientist_continuation(
        run.id, 42, db_path=isolated_db
    )

    assert task is not None
    assert task.task_type == "engine.node.orchestrator"
    assert task.inputs["checkpoint_seq"] == checkpoint_seq
    assert task.priority == 100
    reopened = runs.get_run(run.id, db_path=isolated_db)
    assert reopened is not None and reopened.status == "queued"


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


@pytest.mark.asyncio
async def test_node_task_commits_once_and_schedules_successor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = seed_run("Task-level science")
    supervisor = await _advance_to_supervisor(run.id, monkeypatch, isolated_db)

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        state["supervisor_guidance"] = {"plan": "fixture"}
        return state, "generate"

    _patch_task_node(monkeypatch, execute)
    committed = await engine_tasks.execute_node_task(
        supervisor, db_path=isolated_db
    )
    assert lifecycle.complete_task(
        supervisor.id, "worker", committed, db_path=isolated_db
    )
    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 2
    assert [
        task.task_type for task in store.list_tasks(run.id, db_path=isolated_db)
    ] == [
        "engine.bootstrap",
        "engine.node.supervisor",
        "engine.node.generate",
    ]


def _seed_ranking_state(run_id: str, db_path: str) -> tuple[Any, _Generator]:
    state = _task_state(run_id)
    hypotheses = [
        Hypothesis(
            text=f"Mechanism {index} accelerates ATP recovery.",
            literature_grounding=(
                f"Mechanism {index} accelerates ATP recovery."
            ),
        )
        for index in range(3)
    ]
    for hypothesis in hypotheses:
        hypothesis.review_disposition = "viable"
        _add_fixture_review(hypothesis)
    state.update(
        {
            "hypotheses": hypotheses,
            "tournament_pairs": 3,
            "articles": [
                Article(
                    title=f"Energetics {index}",
                    abstract=(f"Mechanism {index} accelerates ATP recovery."),
                    source_id=f"PMID-{index}",
                )
                for index in range(3)
            ],
        }
    )
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = enqueue_task(
        run_id,
        f"{engine_tasks.NODE_TASK_PREFIX}ranking",
        "ranking-node",
        inputs={"checkpoint_seq": checkpoint_seq},
        db_path=db_path,
    )
    return node, _Generator(state)


def _patch_ranking_judge(
    monkeypatch: pytest.MonkeyPatch, generator: _Generator
) -> None:
    _patch_generator(monkeypatch, generator, restore=True)
    _install_plain_fake_judge(monkeypatch)


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


async def _finalize_and_assert_ranking(
    finalizer: Any,
    run_id: str,
    observed_sequences: list[int],
    db_path: str,
) -> None:
    from co_scientist.checkpoint import restore_workflow_state

    result = await engine_tasks_ranking.execute_ranking_finalize(
        finalizer, db_path=db_path
    )
    assert lifecycle.complete_task(
        finalizer.id,
        finalizer.lease_owner or "finalizer",
        result,
        db_path=db_path,
    )
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    assert len(restored["tournament_matchups"]) == 3
    assert sum(item.total_matches for item in restored["hypotheses"]) == 6
    tasks = store.list_tasks(run_id, db_path=db_path)
    assert sum(
        task.task_type == engine_tasks_support.RANKING_MATCH_TASK
        for task in tasks
    ) == len(observed_sequences)
    assert _milestones(run_id, db_path=db_path) == [
        "Tournament complete (iteration 0, 3 matches)"
    ]
    ranking_events = _task_events(run_id, "ranking", db_path=db_path)
    assert len(ranking_events) == 1
    assert ranking_events[0]["payload"]["successor"] == "orchestrator"


@pytest.mark.asyncio
async def test_ranking_matches_are_separate_sequential_checkpointed_tasks(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = seed_run("Task-level science")
    node, generator = _seed_ranking_state(run.id, isolated_db)
    _patch_ranking_judge(monkeypatch, generator)
    leased = store.claim_task("ranking", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id
    scheduled = await engine_tasks.execute_node_task(
        leased, db_path=isolated_db
    )
    assert lifecycle.complete_task(
        leased.id, "ranking", scheduled, db_path=isolated_db
    )

    finalizer, observed_sequences, committed = await _drain_ranking_matches(
        run.id, isolated_db
    )
    assert observed_sequences == sorted(observed_sequences)
    assert len(set(observed_sequences)) == len(observed_sequences)
    assert committed == 3, "the whole round is judged exactly once"

    await _finalize_and_assert_ranking(
        finalizer, run.id, observed_sequences, isolated_db
    )


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
    from app.config import settings

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    created = _create_run(client, "Cancel before bootstrap starts")
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    task = store.claim_task("bootstrap-worker", run_id=run_id)
    assert task is not None

    real_get_run = runs.get_run
    monkeypatch.setattr(
        runs, "get_run", _cancel_after_second_run_read(run_id, client)
    )
    prepared: list[bool] = []

    async def no_intake_work(*_: Any, **__: Any) -> None:
        return None

    async def prepare_without_providers(*_: Any, **__: Any) -> tuple[Any, ...]:
        prepared.append(True)
        return {}, object()

    async def emit_without_persisting(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(
        engine_tasks_inputs, "_screen_bootstrap_intake", no_intake_work
    )
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
    monkeypatch.setattr(
        engine_tasks_inputs, "sync_engine_llm_backend", lambda *_: None
    )

    result = await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    refreshed = real_get_run(run_id, db_path=isolated_db)
    assert refreshed is not None and refreshed.status == "cancelled"
    assert result.get("status") == "cancelled"
    assert prepared == []
    persisted = store.get_task(task.id, db_path=isolated_db)
    assert persisted is not None and persisted.status == "cancelled"


@pytest.mark.parametrize("decision", ["block", "hold"])
@pytest.mark.asyncio
async def test_cancel_during_bootstrap_safety_gate_keeps_cancelled_status(
    decision: str,
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings
    from app.safety.types import SafetyDecision

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    created = _create_run(client, "Cancel during safety screening")
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    task = store.claim_task("gate-worker", run_id=run_id)
    assert task is not None

    screening_started = asyncio.Event()
    release_screening = asyncio.Event()
    verdict = SafetyDecision(
        stage="intake",
        decision=decision,
        reason=f"injected {decision}",
    )

    async def delayed_screen(*_: Any, **__: Any) -> SafetyDecision:
        screening_started.set()
        await release_screening.wait()
        return verdict

    _install_runtime(monkeypatch).screen = delayed_screen
    bootstrap = asyncio.create_task(
        engine_tasks.execute_bootstrap(task, db_path=isolated_db)
    )
    await asyncio.wait_for(screening_started.wait(), timeout=5)
    cancelled = client.post(f"/api/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    cancel_seq = next(
        event["seq"]
        for event in store_events.list_events(run_id, db_path=isolated_db)
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    release_screening.set()

    with pytest.raises(task_worker._LeaseLostError):
        await bootstrap

    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "cancelled"
    assert [
        item
        for item in records.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "intake"
    ] == []
    events = store_events.list_events(run_id, db_path=isolated_db)
    assert not any(event["type"] == "safety.intake" for event in events)
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
    from app.config import settings
    from app.safety.types import SafetyDecision

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    created = _create_run(client, "Replace intake lease")
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    original = store.claim_task("old-bootstrap", run_id=run_id)
    assert original is not None

    screening_started = asyncio.Event()
    release_screening = asyncio.Event()

    async def delayed_screen(*_: Any, **__: Any) -> SafetyDecision:
        screening_started.set()
        await release_screening.wait()
        return SafetyDecision(stage="intake", decision=decision, reason="late")

    _install_runtime(monkeypatch).screen = delayed_screen
    bootstrap = asyncio.create_task(
        engine_tasks.execute_bootstrap(original, db_path=isolated_db)
    )
    await asyncio.wait_for(screening_started.wait(), timeout=5)
    with db.transaction(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (original.id,),
        )
    assert store.claim_task("new-bootstrap", run_id=run_id) is None
    failed = store.get_task(original.id, db_path=isolated_db)
    assert failed is not None and failed.status == "failed"
    assert "may have accepted" in (failed.error or "")
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    replacement = store.claim_task("old-bootstrap", run_id=run_id)
    assert replacement is not None
    assert replacement.attempt == original.attempt + 1
    release_screening.set()

    with pytest.raises(task_worker._LeaseLostError):
        await bootstrap

    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "queued"
    assert [
        item
        for item in records.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "intake"
    ] == []
    events = store_events.list_events(run_id, db_path=isolated_db)
    assert not any(event["type"] == "safety.intake" for event in events)
    assert not any(
        event["type"] == "status"
        and event["payload"].get("status") in {"blocked", "paused"}
        for event in events
    )


@pytest.mark.asyncio
async def test_replaced_bootstrap_lease_cannot_prepare_paused_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from app.store.models import RunStatus

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    created = _create_run(client, "Pause after lease replacement")
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    original = store.claim_task("old-paused-worker", run_id=run_id)
    assert original is not None
    with db.transaction(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (original.id,),
        )
    assert store.claim_task("current-paused-worker", run_id=run_id) is None
    failed = store.get_task(original.id, db_path=isolated_db)
    assert failed is not None and failed.status == "failed"
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    replacement = store.claim_task("old-paused-worker", run_id=run_id)
    assert replacement is not None
    assert replacement.attempt == original.attempt + 1
    runs.update_run_status(run_id, RunStatus.PAUSED, db_path=isolated_db)
    prepared: list[bool] = []
    synced: list[bool] = []

    async def no_intake_work(*_: Any, **__: Any) -> None:
        return None

    async def fake_prepare(*_: Any, **__: Any) -> tuple[Any, ...]:
        prepared.append(True)
        return {}, object()

    monkeypatch.setattr(
        engine_tasks_inputs, "_screen_bootstrap_intake", no_intake_work
    )
    monkeypatch.setattr(
        engine_tasks_inputs, "_prepare_bootstrap_state", fake_prepare
    )
    monkeypatch.setattr(
        engine_tasks_inputs,
        "sync_engine_llm_backend",
        lambda *_: synced.append(True),
    )

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_bootstrap(original, db_path=isolated_db)

    assert prepared == []
    assert synced == []
    assert (
        runs.mark_bootstrap_running(
            run_id,
            replacement.id,
            replacement.lease_owner,
            replacement.attempt,
            db_path=isolated_db,
        )
        == RunStatus.PAUSED.value
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


@pytest.mark.asyncio
async def test_cancel_completed_after_node_status_check_blocks_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, run_id = _owned_running_run(isolated_db)
    state = _task_state(run_id)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "cancel-race-node", isolated_db
    )

    monkeypatch.setattr(
        engine_tasks_node,
        "_prepare_node_task",
        lambda *_: (
            state,
            TaskCommit(task, checkpoint_seq, isolated_db),
            "supervisor",
        ),
    )

    async def execute_node(
        _name: str, node_state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        return {**node_state, "committed_after_execution": True}, "generate"

    from co_scientist import task_runtime

    monkeypatch.setattr(task_runtime, "execute_task_node", execute_node)

    commit_node_result = engine_tasks_node._commit_node_result

    async def cancel_then_commit(
        commit: TaskCommit,
        run: RunRow,
        node_name: str,
        committed: dict[str, Any],
        successor: str | None,
    ) -> dict[str, Any]:
        response = client.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"
        return await commit_node_result(
            commit, run, node_name, committed, successor
        )

    monkeypatch.setattr(
        engine_tasks_node, "_commit_node_result", cancel_then_commit
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
    state = _task_state(run_id)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "pause-successor-race", isolated_db
    )
    monkeypatch.setattr(
        engine_tasks_node,
        "_prepare_node_task",
        lambda *_: (
            state,
            TaskCommit(task, checkpoint_seq, isolated_db),
            "supervisor",
        ),
    )

    async def execute_node(
        _name: str, node_state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        node_state["metrics"].llm_calls = 7
        node_state["metrics"].hypothesis_count = 3
        return {**node_state, "committed_after_execution": True}, "generate"

    from co_scientist import task_runtime

    monkeypatch.setattr(task_runtime, "execute_task_node", execute_node)

    commit_node_result = engine_tasks_node._commit_node_result

    async def pause_then_commit(
        commit: TaskCommit,
        run: RunRow,
        node_name: str,
        committed: dict[str, Any],
        successor: str | None,
    ) -> dict[str, Any]:
        response = client.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "paused"
        return await commit_node_result(
            commit, run, node_name, committed, successor
        )

    monkeypatch.setattr(
        engine_tasks_node, "_commit_node_result", pause_then_commit
    )

    result = await engine_tasks.execute_node_task(task, db_path=isolated_db)

    saved_tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert not any(row.status == "queued" for row in saved_tasks), result
    assert result["status"] == "paused"
    assert lifecycle.complete_task(
        task.id, "cancel-race-worker", result, db_path=isolated_db
    )
    latest = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq + 1
    assert latest["stage"] == f"engine_task_paused:{task.id}"
    assert latest["state"]["resume_successor"] == "engine.node.generate"
    metrics = retrieval.get_run_metrics(run_id, db_path=isolated_db)
    assert metrics is not None
    assert metrics["llm_calls"] == 7
    assert metrics["hypothesis_count"] == 3
    [completion] = _task_events(run_id, "supervisor", db_path=isolated_db)
    assert completion["payload"] == {
        "task": "supervisor",
        "status": "completed",
        "checkpoint_seq": checkpoint_seq + 1,
        "successor": "generate",
        "activity": "planning",
    }
    saved_tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert [row.id for row in saved_tasks] == [task.id]
    assert (
        store.claim_task(
            "pause-race-claim-check", run_id=run_id, db_path=isolated_db
        )
        is None
    )

    resumed = client.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    queued = [
        row
        for row in store.list_tasks(run_id, db_path=isolated_db)
        if row.status == "queued"
    ]
    assert len(queued) == 1
    assert queued[0].task_type == "engine.node.generate"


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
    monkeypatch.setattr(
        engine_tasks_node,
        "_prepare_node_task",
        lambda *_: (
            state,
            TaskCommit(task, checkpoint_seq, isolated_db),
            "review",
        ),
    )

    enqueue_fanout = engine_tasks_node._dispatch_node_fanout

    async def cancel_then_enqueue(
        *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        response = client.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
        assert response.status_code == 200, response.text
        return await enqueue_fanout(*args, **kwargs)

    monkeypatch.setattr(
        engine_tasks_node, "_dispatch_node_fanout", cancel_then_enqueue
    )

    with suppress(task_worker._LeaseLostError):
        await engine_tasks.execute_node_task(task, db_path=isolated_db)

    task_types = [
        row.task_type for row in store.list_tasks(run_id, db_path=isolated_db)
    ]
    assert task_types == [task.task_type]
    latest = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq


def test_terminal_run_cannot_commit_an_exact_successor(
    isolated_db: str,
) -> None:
    _client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.ranking.match", "terminal-exact-task", isolated_db
    )
    runs.update_run_status(
        run_id, StoreRunStatus.COMPLETED, db_path=isolated_db
    )

    with pytest.raises(task_worker._LeaseLostError):
        engine_tasks_support._save_state_and_enqueue_exact(
            TaskCommit(task, checkpoint_seq, isolated_db),
            _task_state(run_id),
            ExactSuccessor(
                task_type="engine.ranking.match",
                inputs={"match_index": 2},
                idempotency_key="match:{checkpoint_seq}",
            ),
        )

    latest = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [task.id]
    still_leased = store.get_task(task.id, db_path=isolated_db)
    assert still_leased is not None and still_leased.status == "leased"


def test_old_same_owner_attempt_cannot_commit_after_re_lease(
    isolated_db: str,
) -> None:
    _client, run_id = _owned_running_run(isolated_db)
    stale_task, checkpoint_seq = _leased_task(
        run_id, "engine.node.supervisor", "same-owner-re-lease", isolated_db
    )
    assert stale_task.attempt == 1
    assert stale_task.lease_owner == "cancel-race-worker"

    with db.transaction(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (stale_task.id,),
        )
    assert (
        store.claim_task(
            "cancel-race-worker",
            lease_seconds=60,
            run_id=run_id,
            db_path=isolated_db,
        )
        is None
    )
    failed = store.get_task(stale_task.id, db_path=isolated_db)
    assert failed is not None and failed.status == "failed"
    assert "may have accepted" in (failed.error or "")
    assert lifecycle.retry_task(
        stale_task.id,
        reason="owner authorized replay after ambiguous lease expiry",
        db_path=isolated_db,
    )
    runs.update_run_status(run_id, StoreRunStatus.QUEUED, db_path=isolated_db)
    current_task = store.claim_task(
        "cancel-race-worker",
        lease_seconds=60,
        run_id=run_id,
        db_path=isolated_db,
    )
    assert current_task is not None and current_task.id == stale_task.id
    assert current_task.lease_owner == stale_task.lease_owner
    assert current_task.attempt == stale_task.attempt + 1

    with pytest.raises(task_worker._LeaseLostError):
        engine_tasks_support._save_state_and_enqueue(
            TaskCommit(stale_task, checkpoint_seq, isolated_db),
            _task_state(run_id),
            "generate",
        )

    latest = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq
    persisted_task = store.get_task(stale_task.id, db_path=isolated_db)
    assert persisted_task is not None and persisted_task.attempt == 2
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [stale_task.id]


def test_cancelled_generation_planner_cannot_enqueue_fanout(
    isolated_db: str,
) -> None:
    client, run_id = _owned_running_run(isolated_db)
    task, checkpoint_seq = _leased_task(
        run_id, "engine.node.generate", "cancel-generation-plan", isolated_db
    )
    response = client.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
    assert response.status_code == 200, response.text

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
            run_id, db_path=isolated_db
        ),
        "state": {},
    }

    with pytest.raises(task_worker._LeaseLostError):
        engine_tasks_fanout_generation._commit_generation_fanout(
            task, checkpoint_seq, envelope, plan, isolated_db
        )

    latest = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None and latest["seq"] == checkpoint_seq
    assert [
        row.id for row in store.list_tasks(run_id, db_path=isolated_db)
    ] == [task.id]

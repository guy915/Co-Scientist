"""Durable node-level engine task execution and checkpoint commit tests."""

import asyncio
import time
from typing import Any

import pytest
from co_scientist.models import ExecutionMetrics, Hypothesis, HypothesisReview

from app import engine_tasks, store, task_worker
from app.safety import screen_intake


def _task_state(run_id: str) -> dict[str, Any]:
    """Build the minimal serializable state used by task-runtime fixtures."""
    return {
        "run_id": run_id,
        "research_goal": "Task-level science",
        "model_name": "fixture",
        "supervisor_model_name": "fixture",
        "hypotheses": [],
        "articles": [],
        "messages": [],
        "metrics": ExecutionMetrics(),
        "mcp_available": False,
        "current_iteration": 0,
        "start_time": time.time(),
    }


class _Generator:
    tool_registry = None

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def prepare_task_state(self, *_: Any, **__: Any) -> dict[str, Any]:
        return self.state


async def _deterministic_screen(text: str, *_: Any, **__: Any) -> Any:
    return screen_intake(text)


@pytest.mark.asyncio
async def test_bootstrap_commits_state_and_enqueues_supervisor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = store.create_run("Task-level science", "standard", "engine", {})
    bootstrap = engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == bootstrap.id
    generator = _Generator(_task_state(run.id))
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "screen_contextual", _deterministic_screen
    )

    result = await engine_tasks.execute_bootstrap(leased, db_path=isolated_db)
    assert store.complete_task(leased.id, "worker", result, db_path=isolated_db)

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 1
    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert [task.task_type for task in tasks] == [
        "engine.bootstrap",
        "engine.node.supervisor",
    ]


@pytest.mark.asyncio
async def test_node_task_commits_once_and_schedules_successor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = store.create_run("Task-level science", "standard", "engine", {})
    bootstrap = engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    generator = _Generator(_task_state(run.id))
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "screen_contextual", _deterministic_screen
    )
    result = await engine_tasks.execute_bootstrap(leased, db_path=isolated_db)
    assert store.complete_task(
        bootstrap.id, "worker", result, db_path=isolated_db
    )
    supervisor = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert supervisor is not None

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        state["supervisor_guidance"] = {"plan": "fixture"}
        return state, "generate"

    import co_scientist.task_runtime as runtime

    monkeypatch.setattr(runtime, "execute_task_node", execute)
    committed = await engine_tasks.execute_node_task(
        supervisor, db_path=isolated_db
    )
    assert store.complete_task(
        supervisor.id, "worker", committed, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 2
    assert [
        task.task_type for task in store.list_tasks(run.id, db_path=isolated_db)
    ] == [
        "engine.bootstrap",
        "engine.node.supervisor",
        "engine.node.generate",
    ]


def test_orchestrator_priority_reaches_durable_successor(
    isolated_db: str,
) -> None:
    """The Supervisor's selected priority controls queue claim order."""
    run = store.create_run("Priority science", "standard", "engine", {})
    store.save_checkpoint(
        run.id,
        stage="seed",
        schema_version=1,
        last_event_seq=0,
        state={"provider": "engine"},
        db_path=isolated_db,
    )
    queued = store.enqueue_task(
        run.id,
        "engine.node.orchestrator",
        {"checkpoint_seq": 1},
        idempotency_key="orchestrator-priority",
        db_path=isolated_db,
    )
    task = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert task is not None and task.id == queued.id

    engine_tasks._save_state_and_enqueue(
        task,
        {**_task_state(run.id), "next_task_priority": 97},
        "generate",
        expected_checkpoint_seq=1,
        db_path=isolated_db,
    )

    successor = store.list_tasks(run.id, db_path=isolated_db)[-1]
    assert successor.task_type == "engine.node.generate"
    assert successor.priority == 97


@pytest.mark.asyncio
async def test_review_fanout_uses_independent_leases_and_one_aggregate_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parallel review children share one checkpoint and aggregate once."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    state["hypotheses"] = [Hypothesis(text="alpha"), Hypothesis(text="beta")]
    generator = _Generator(state)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: generator
    )
    monkeypatch.setattr(
        engine_tasks, "screen_contextual", _deterministic_screen
    )
    engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    await task_worker.run_once("bootstrap", run_id=run.id, db_path=isolated_db)
    supervisor = store.claim_task(
        "supervisor", run_id=run.id, db_path=isolated_db
    )
    assert supervisor is not None

    async def supervisor_to_review(
        _name: str, current: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        return current, "review"

    import co_scientist.nodes.review as review_module
    import co_scientist.task_runtime as runtime

    monkeypatch.setattr(runtime, "execute_task_node", supervisor_to_review)
    result = await engine_tasks.execute_node_task(
        supervisor, db_path=isolated_db
    )
    assert store.complete_task(
        supervisor.id, "supervisor", result, db_path=isolated_db
    )
    review_parent = store.claim_task(
        "parent", run_id=run.id, db_path=isolated_db
    )
    assert review_parent is not None
    parent_result = await engine_tasks.execute_node_task(
        review_parent, db_path=isolated_db
    )
    assert store.complete_task(
        review_parent.id, "parent", parent_result, db_path=isolated_db
    )

    async def fake_review(**kwargs: Any) -> HypothesisReview:
        return HypothesisReview(
            review_summary=f"reviewed {kwargs['hypothesis_text']}",
            scores={"scientific_soundness": 8, "novelty": 8},
            safety_ethical_concerns="none",
            detailed_feedback={},
            constructive_feedback="continue",
            overall_score=8.0,
        )

    monkeypatch.setattr(review_module, "review_single_hypothesis", fake_review)
    first = store.claim_task("child-a", run_id=run.id, db_path=isolated_db)
    second = store.claim_task("child-b", run_id=run.id, db_path=isolated_db)
    assert first is not None and second is not None
    assert first.task_type == second.task_type == engine_tasks.REVIEW_ITEM_TASK
    first_result, second_result = await asyncio.gather(
        engine_tasks.execute_review_item(first, db_path=isolated_db),
        engine_tasks.execute_review_item(second, db_path=isolated_db),
    )
    assert store.complete_task(
        first.id, "child-a", first_result, db_path=isolated_db
    )
    assert store.complete_task(
        second.id, "child-b", second_result, db_path=isolated_db
    )
    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    aggregate_result = await engine_tasks.execute_review_aggregate(
        aggregate, db_path=isolated_db
    )
    assert aggregate_result["successful_reviews"] == 2
    assert store.complete_task(
        aggregate.id, "aggregate", aggregate_result, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 3
    persisted = checkpoint["state"]["state"]["hypotheses"]
    assert [hypothesis["score"] for hypothesis in persisted] == [8.0, 8.0]


@pytest.mark.asyncio
async def test_review_aggregate_is_ready_after_isolated_child_failure(
    isolated_db: str,
) -> None:
    """An allowed failed dependency does not permanently strand aggregation."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    failed = store.enqueue_task(
        run.id,
        engine_tasks.REVIEW_ITEM_TASK,
        {},
        idempotency_key="failed-child",
        max_attempts=1,
        db_path=isolated_db,
    )
    aggregate = store.enqueue_task(
        run.id,
        engine_tasks.REVIEW_AGGREGATE_TASK,
        {},
        idempotency_key="aggregate",
        dependencies=(failed.id,),
        provenance={"allow_failed_dependencies": True},
        db_path=isolated_db,
    )
    leased = store.claim_task("child", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == failed.id
    assert store.fail_task(
        leased.id,
        "child",
        "provider failed",
        retryable=False,
        db_path=isolated_db,
    )

    ready = store.claim_task("aggregate", run_id=run.id, db_path=isolated_db)
    assert ready is not None and ready.id == aggregate.id


@pytest.mark.asyncio
async def test_verification_fanout_materializes_one_task_per_top_candidate(
    isolated_db: str,
) -> None:
    """Verification becomes multiple globally claimable specialist tasks."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    parent = store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}deep_verification",
        {"checkpoint_seq": 4},
        idempotency_key="verification-parent",
        db_path=isolated_db,
    )
    leased = store.claim_task("parent", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == parent.id
    state = _task_state(run.id)
    state["hypotheses"] = [
        Hypothesis(text=f"candidate-{index}", elo_rating=1000 + index)
        for index in range(5)
    ]

    result = engine_tasks._enqueue_verification_fanout(
        leased, state, 4, db_path=isolated_db
    )
    assert len(result["fanout_task_ids"]) == 3
    assert store.complete_task(leased.id, "parent", result, db_path=isolated_db)
    first = store.claim_task("verify-a", run_id=run.id, db_path=isolated_db)
    second = store.claim_task("verify-b", run_id=run.id, db_path=isolated_db)
    third = store.claim_task("verify-c", run_id=run.id, db_path=isolated_db)
    assert first is not None and second is not None and third is not None
    assert {first.task_type, second.task_type, third.task_type} == {
        engine_tasks.VERIFICATION_ITEM_TASK
    }


@pytest.mark.asyncio
async def test_verification_children_commit_through_single_aggregator(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verification results update state only at the aggregate boundary."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    state["hypotheses"] = [
        Hypothesis(text=f"candidate-{index}", elo_rating=1200 + index)
        for index in range(3)
    ]
    envelope = serialize_workflow_state(state, last_event_seq=0)
    checkpoint_seq = store.save_checkpoint(
        run.id,
        stage="fixture",
        schema_version=CHECKPOINT_VERSION,
        last_event_seq=0,
        state={"provider": "engine", **envelope},
    )
    node = store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}deep_verification",
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key="verification-node",
        db_path=isolated_db,
    )
    generator = _Generator(state)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: generator
    )
    leased_node = store.claim_task("node", run_id=run.id, db_path=isolated_db)
    assert leased_node is not None and leased_node.id == node.id
    scheduled = await engine_tasks.execute_node_task(
        leased_node, db_path=isolated_db
    )
    assert store.complete_task(
        leased_node.id, "node", scheduled, db_path=isolated_db
    )

    import co_scientist.nodes.deep_verification as verification_module

    async def fake_verify(*_: Any, **__: Any) -> dict[str, Any]:
        return {"probes": [{"question": "q"}], "verdict": "supported"}

    monkeypatch.setattr(verification_module, "_verify_one", fake_verify)
    children = [
        store.claim_task(f"child-{index}", run_id=run.id, db_path=isolated_db)
        for index in range(3)
    ]
    assert all(child is not None for child in children)
    child_results = await asyncio.gather(
        *[
            engine_tasks.execute_verification_item(child, db_path=isolated_db)
            for child in children
            if child is not None
        ]
    )
    for index, (child, result) in enumerate(
        zip(children, child_results, strict=True)
    ):
        assert child is not None
        assert store.complete_task(
            child.id, f"child-{index}", result, db_path=isolated_db
        )
    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    result = await engine_tasks.execute_verification_aggregate(
        aggregate, db_path=isolated_db
    )
    assert result["successful_verifications"] == 3
    assert store.complete_task(
        aggregate.id, "aggregate", result, db_path=isolated_db
    )
    latest = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert latest is not None
    restored = latest["state"]["state"]["hypotheses"]
    assert all(
        item["deep_verification_verdict"] == "supported" for item in restored
    )


@pytest.mark.asyncio
async def test_ranking_matches_are_separate_sequential_checkpointed_tasks(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every Elo match observes the checkpoint committed by its predecessor."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        restore_workflow_state,
        serialize_workflow_state,
    )

    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    hypotheses = [Hypothesis(text=f"idea-{index}") for index in range(3)]
    for hypothesis in hypotheses:
        hypothesis.review_disposition = "viable"
    state.update({"hypotheses": hypotheses, "tournament_pairs": 3})
    envelope = serialize_workflow_state(state, last_event_seq=0)
    checkpoint_seq = store.save_checkpoint(
        run.id,
        stage="fixture",
        schema_version=CHECKPOINT_VERSION,
        last_event_seq=0,
        state={"provider": "engine", **envelope},
    )
    node = store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}ranking",
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key="ranking-node",
        db_path=isolated_db,
    )
    generator = _Generator(state)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: generator
    )

    import co_scientist.nodes.ranking as ranking_module

    async def fake_judge(*_: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        turns = int(kwargs["debate_turns"])
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": turns,
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", fake_judge)
    leased = store.claim_task("ranking", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id
    scheduled = await engine_tasks.execute_node_task(
        leased, db_path=isolated_db
    )
    assert store.complete_task(
        leased.id, "ranking", scheduled, db_path=isolated_db
    )

    observed_sequences: list[int] = []
    for index in range(3):
        match = store.claim_task(
            f"match-{index}", run_id=run.id, db_path=isolated_db
        )
        assert (
            match is not None
            and match.task_type == engine_tasks.RANKING_MATCH_TASK
        )
        observed_sequences.append(int(match.inputs["checkpoint_seq"]))
        result = await engine_tasks.execute_ranking_match(
            match, db_path=isolated_db
        )
        if index == 0:
            replay = await engine_tasks.execute_ranking_match(
                match, db_path=isolated_db
            )
            assert replay["replayed"] is True
        assert store.complete_task(
            match.id, f"match-{index}", result, db_path=isolated_db
        )
    assert observed_sequences == sorted(observed_sequences)
    assert len(set(observed_sequences)) == 3

    finalizer = store.claim_task(
        "finalizer", run_id=run.id, db_path=isolated_db
    )
    assert finalizer is not None
    result = await engine_tasks.execute_ranking_finalize(
        finalizer, db_path=isolated_db
    )
    assert store.complete_task(
        finalizer.id, "finalizer", result, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    assert len(restored["tournament_matchups"]) == 3
    assert sum(item.total_matches for item in restored["hypotheses"]) == 6
    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert (
        sum(task.task_type == engine_tasks.RANKING_MATCH_TASK for task in tasks)
        == 3
    )


@pytest.mark.asyncio
async def test_worker_consumes_independent_specialist_task_chain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One run advances through separately committed and leased node tasks."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    generator = _Generator(_task_state(run.id))
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: generator
    )
    monkeypatch.setattr(
        engine_tasks, "screen_contextual", _deterministic_screen
    )

    successors = {
        "supervisor": "research_overview",
        "research_overview": None,
    }

    async def execute(
        name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        return state, successors[name]

    async def finalize(task: Any, **_: Any) -> dict[str, Any]:
        store.update_run_status(task.run_id, store.RunStatus.COMPLETED)
        return {"run_id": task.run_id, "status": "completed"}

    import co_scientist.task_runtime as runtime

    monkeypatch.setattr(runtime, "execute_task_node", execute)
    monkeypatch.setattr(engine_tasks, "execute_finalize", finalize)
    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert [task.task_type for task in tasks] == [
        "engine.bootstrap",
        "engine.node.supervisor",
        "engine.node.research_overview",
        "engine.finalize",
    ]
    assert all(task.status == "completed" for task in tasks)


@pytest.mark.asyncio
async def test_inflight_pause_checkpoints_exact_successor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A node finishing after pause commits state but enqueues no next work."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    bootstrap = engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    generator = _Generator(_task_state(run.id))
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "screen_contextual", _deterministic_screen
    )
    result = await engine_tasks.execute_bootstrap(leased, db_path=isolated_db)
    assert store.complete_task(
        bootstrap.id, "worker", result, db_path=isolated_db
    )
    supervisor = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert supervisor is not None

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        store.update_run_status(run.id, store.RunStatus.PAUSED)
        return state, "generate"

    import co_scientist.task_runtime as runtime

    monkeypatch.setattr(runtime, "execute_task_node", execute)
    paused = await engine_tasks.execute_node_task(
        supervisor, db_path=isolated_db
    )
    assert store.complete_task(
        supervisor.id, "worker", paused, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["state"]["resume_successor"] == "engine.node.generate"
    assert len(store.list_tasks(run.id, db_path=isolated_db)) == 2

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )
    assert resumed.task_type == "engine.node.generate"


@pytest.mark.asyncio
async def test_generation_strategies_are_independently_leased_and_aggregated(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Debate and assumptions generation share a plan but execute separately."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        restore_workflow_state,
        serialize_workflow_state,
    )
    from co_scientist.models import GenerationMethod

    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    state.update(
        {
            "supervisor_guidance": {"focus": "test"},
            "initial_hypotheses_count": 8,
            "enable_tool_calling_generation": False,
        }
    )
    envelope = serialize_workflow_state(state, last_event_seq=0)
    checkpoint_seq = store.save_checkpoint(
        run.id,
        stage="fixture",
        schema_version=CHECKPOINT_VERSION,
        last_event_seq=0,
        state={"provider": "engine", **envelope},
    )
    node = store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}generate",
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key="generation-node",
        db_path=isolated_db,
    )
    generator = _Generator(state)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: generator
    )

    import co_scientist.nodes.generation.assumptions as assumptions_module
    import co_scientist.nodes.generation.debate as debate_module

    async def fake_debate(
        **kwargs: Any,
    ) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
        hypotheses = [
            Hypothesis(
                text=f"debate-{index}",
                generation_method=GenerationMethod.DEBATE,
            )
            for index in range(int(kwargs["count"]))
        ]
        return hypotheses, [{"strategy": "debate"}]

    async def fake_assumptions(_state: Any, count: int) -> list[Hypothesis]:
        return [
            Hypothesis(
                text=f"assumption-{index}",
                generation_method=GenerationMethod.ASSUMPTIONS,
            )
            for index in range(count)
        ]

    monkeypatch.setattr(debate_module, "generate_with_debate", fake_debate)
    monkeypatch.setattr(
        assumptions_module, "generate_with_assumptions", fake_assumptions
    )
    leased = store.claim_task("planner", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id
    planned = await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    assert len(planned["fanout_task_ids"]) == 7
    assert store.complete_task(
        leased.id, "planner", planned, db_path=isolated_db
    )

    strategies = [
        store.claim_task(
            f"strategy-{index}", run_id=run.id, db_path=isolated_db
        )
        for index in range(7)
    ]
    assert all(item is not None for item in strategies)
    assert all(
        item is not None
        and item.task_type == engine_tasks.GENERATION_STRATEGY_TASK
        for item in strategies
    )
    strategy_results = await asyncio.gather(
        *[
            engine_tasks.execute_generation_strategy(item, db_path=isolated_db)
            for item in strategies
            if item is not None
        ]
    )
    for index, (item, result) in enumerate(
        zip(strategies, strategy_results, strict=True)
    ):
        assert item is not None
        assert store.complete_task(
            item.id, f"strategy-{index}", result, db_path=isolated_db
        )
    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    aggregated = await engine_tasks.execute_generation_aggregate(
        aggregate, db_path=isolated_db
    )
    assert aggregated["hypotheses_generated"] == 8
    assert store.complete_task(
        aggregate.id, "aggregate", aggregated, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    methods = {
        hypothesis.generation_method for hypothesis in restored["hypotheses"]
    }
    assert methods == {GenerationMethod.DEBATE, GenerationMethod.ASSUMPTIONS}
    successor = store.claim_task("review", run_id=run.id, db_path=isolated_db)
    assert successor is not None
    assert successor.task_type == f"{engine_tasks.NODE_TASK_PREFIX}review"


@pytest.mark.asyncio
async def test_mature_reflection_modes_are_independent_durable_tasks(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Observation, full, simulation, and recurrent modes lease separately."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        restore_workflow_state,
        serialize_workflow_state,
    )

    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    fresh = Hypothesis(text="fresh")
    fresh.review_disposition = "viable"
    mature = Hypothesis(text="mature")
    mature.review_disposition = "viable"
    mature.enrichments.update({"full": {}, "simulation": {}})
    mature.reflection_notes = "prior observation"
    state.update(
        {
            "hypotheses": [fresh, mature],
            "articles_with_reasoning": "retrieved observations",
            "current_iteration": 2,
        }
    )
    envelope = serialize_workflow_state(state, last_event_seq=0)
    checkpoint_seq = store.save_checkpoint(
        run.id,
        stage="fixture",
        schema_version=CHECKPOINT_VERSION,
        last_event_seq=0,
        state={"provider": "engine", **envelope},
    )
    node = store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}comprehensive_reflection",
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key="mature-reflection-node",
        db_path=isolated_db,
    )
    generator = _Generator(state)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: generator
    )

    import co_scientist.nodes.comprehensive_reflection as reflection_module
    import co_scientist.nodes.reflection as observation_module

    async def fake_review(
        _state: Any, _hypothesis: Any, mode: Any
    ) -> tuple[Any, dict[str, Any]]:
        return mode, {"verdict": f"{mode.value}-complete"}

    async def fake_observation(**_: Any) -> dict[str, Any]:
        return {"classification": "missing_piece", "reasoning": "explains x"}

    monkeypatch.setattr(reflection_module, "_run_review", fake_review)
    monkeypatch.setattr(
        observation_module, "analyze_single_hypothesis", fake_observation
    )
    leased = store.claim_task("planner", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id
    planned = await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    assert len(planned["fanout_task_ids"]) == 4
    assert store.complete_task(
        leased.id, "planner", planned, db_path=isolated_db
    )
    items = [
        store.claim_task(f"mode-{index}", run_id=run.id, db_path=isolated_db)
        for index in range(4)
    ]
    assert all(item is not None for item in items)
    results = await asyncio.gather(
        *[
            engine_tasks.execute_mature_reflection_item(
                item, db_path=isolated_db
            )
            for item in items
            if item is not None
        ]
    )
    assert {result["review_mode"] for result in results} == {
        "observation",
        "full",
        "simulation",
        "recurrent",
    }
    for index, (item, result) in enumerate(zip(items, results, strict=True)):
        assert item is not None
        assert store.complete_task(
            item.id, f"mode-{index}", result, db_path=isolated_db
        )
    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    aggregated = await engine_tasks.execute_mature_reflection_aggregate(
        aggregate, db_path=isolated_db
    )
    assert aggregated["successful_reviews"] == 4
    assert store.complete_task(
        aggregate.id, "aggregate", aggregated, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    restored_fresh, restored_mature = restored["hypotheses"]
    assert {"observation", "full", "simulation"} <= set(
        restored_fresh.enrichments
    )
    assert restored_mature.enrichments["recurrent_review_iteration"] == 2
    successor = store.claim_task("safety", run_id=run.id, db_path=isolated_db)
    assert successor is not None
    assert (
        successor.task_type == f"{engine_tasks.NODE_TASK_PREFIX}safety_screen"
    )

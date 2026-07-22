"""Review and verification fan-out mechanics for the durable engine executor.

Independent child leases committing through a single aggregate.
"""

import asyncio
from typing import Any

import pytest
from co_scientist.models import (
    Article,
    Hypothesis,
    HypothesisReview,
)

from app import engine_tasks, store, task_worker
from tests._engine_tasks_helpers import (
    _deterministic_screen,
    _Generator,
    _seed_checkpoint,
    _task_state,
)


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
        engine_tasks, "screen_with_escalation", _deterministic_screen
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

    import co_scientist.agents.reflection.review as review_module
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
    # The review fan-out aggregate -- one of the five node types the fan-out
    # architecture previously left silent on the event stream -- now emits
    # its own scientific_task completion, same as the generic node path.
    events = store.list_events(run.id, db_path=isolated_db)
    review_events = [e for e in events if e["payload"].get("task") == "review"]
    assert len(review_events) == 1
    assert (
        review_events[0]["payload"]["successor"] == "comprehensive_reflection"
    )


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
    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    state["hypotheses"] = [
        Hypothesis(text=f"candidate-{index}", elo_rating=1200 + index)
        for index in range(3)
    ]
    checkpoint_seq = _seed_checkpoint(run.id, state)
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

    import co_scientist.agents.reflection.deep_verification as verification

    async def fake_verify(*_: Any, **__: Any) -> dict[str, Any]:
        return {
            "probes": [{"question": "q"}],
            "verdict": "supported",
            "retrieval_queries": ["probe query"],
            "retrieved_articles": [
                Article(
                    title="Probe evidence",
                    source_id="probe-1",
                    abstract="Direct targeted support.",
                    used_in_analysis=True,
                ).to_dict()
            ],
            "verification_llm_calls": 2,
        }

    monkeypatch.setattr(verification, "_verify_one", fake_verify)
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
    assert latest["state"]["state"]["articles"][-1]["source_id"] == "probe-1"
    assert restored[0]["enrichments"]["deep_verification"][
        "retrieval_queries"
    ] == ["probe query"]
    milestones = [
        message
        for message in store.list_messages(run.id, db_path=isolated_db)
        if message.kind == "milestone"
    ]
    assert [message.content for message in milestones] == [
        "3 hypotheses verified"
    ]
    events = store.list_events(run.id, db_path=isolated_db)
    verification_events = [
        e for e in events if e["payload"].get("task") == "deep_verification"
    ]
    assert len(verification_events) == 1
    assert verification_events[0]["payload"]["successor"] == "ranking"

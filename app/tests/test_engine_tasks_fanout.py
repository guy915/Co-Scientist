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
    _Generator,
    _milestones,
    _patch_generator,
    _patch_task_node,
    _seed_checkpoint,
    _task_events,
    _task_state,
)


async def _fake_review(**kwargs: Any) -> HypothesisReview:
    return HypothesisReview(
        review_summary=f"reviewed {kwargs['hypothesis_text']}",
        scores={"scientific_soundness": 8, "novelty": 8},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="continue",
        overall_score=8.0,
    )


async def _advance_to_review_parent(
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    generator: _Generator,
    db_path: str,
) -> None:
    """Bootstrap, route supervisor->review, and fan out the review parent."""
    _patch_generator(monkeypatch, generator, restore=True, screen=True)
    engine_tasks.enqueue_bootstrap(run_id, db_path=db_path)
    await task_worker.run_once("bootstrap", run_id=run_id, db_path=db_path)
    supervisor = store.claim_task("supervisor", run_id=run_id, db_path=db_path)
    assert supervisor is not None

    async def supervisor_to_review(
        _name: str, current: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        return current, "review"

    _patch_task_node(monkeypatch, supervisor_to_review)
    result = await engine_tasks.execute_node_task(supervisor, db_path=db_path)
    assert store.complete_task(
        supervisor.id, "supervisor", result, db_path=db_path
    )
    review_parent = store.claim_task("parent", run_id=run_id, db_path=db_path)
    assert review_parent is not None
    parent_result = await engine_tasks.execute_node_task(
        review_parent, db_path=db_path
    )
    assert store.complete_task(
        review_parent.id, "parent", parent_result, db_path=db_path
    )


async def _run_review_children_and_aggregate(run_id: str, db_path: str) -> None:
    """Lease both review children in parallel and commit one aggregate."""
    first = store.claim_task("child-a", run_id=run_id, db_path=db_path)
    second = store.claim_task("child-b", run_id=run_id, db_path=db_path)
    assert first is not None and second is not None
    assert first.task_type == second.task_type == engine_tasks.REVIEW_ITEM_TASK
    first_result, second_result = await asyncio.gather(
        engine_tasks.execute_review_item(first, db_path=db_path),
        engine_tasks.execute_review_item(second, db_path=db_path),
    )
    assert store.complete_task(
        first.id, "child-a", first_result, db_path=db_path
    )
    assert store.complete_task(
        second.id, "child-b", second_result, db_path=db_path
    )
    aggregate = store.claim_task("aggregate", run_id=run_id, db_path=db_path)
    assert aggregate is not None
    aggregate_result = await engine_tasks.execute_review_aggregate(
        aggregate, db_path=db_path
    )
    assert aggregate_result["successful_reviews"] == 2
    assert store.complete_task(
        aggregate.id, "aggregate", aggregate_result, db_path=db_path
    )


@pytest.mark.asyncio
async def test_review_fanout_uses_independent_leases_and_one_aggregate_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parallel review children share one checkpoint and aggregate once."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    state["hypotheses"] = [Hypothesis(text="alpha"), Hypothesis(text="beta")]
    await _advance_to_review_parent(
        run.id, monkeypatch, _Generator(state), isolated_db
    )

    import co_scientist.agents.reflection.review as review_module

    monkeypatch.setattr(review_module, "review_single_hypothesis", _fake_review)
    await _run_review_children_and_aggregate(run.id, isolated_db)

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 3
    persisted = checkpoint["state"]["state"]["hypotheses"]
    assert [hypothesis["score"] for hypothesis in persisted] == [8.0, 8.0]
    # The review fan-out aggregate -- one of the five node types the fan-out
    # architecture previously left silent on the event stream -- now emits
    # its own scientific_task completion, same as the generic node path.
    review_events = _task_events(run.id, "review", db_path=isolated_db)
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
        store.NewTask(
            run_id=run.id,
            task_type=engine_tasks.REVIEW_ITEM_TASK,
            inputs={},
            idempotency_key="failed-child",
            max_attempts=1,
        ),
        db_path=isolated_db,
    )
    aggregate = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=engine_tasks.REVIEW_AGGREGATE_TASK,
            inputs={},
            idempotency_key="aggregate",
            dependencies=(failed.id,),
            provenance={"allow_failed_dependencies": True},
        ),
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
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}deep_verification",
            inputs={"checkpoint_seq": 4},
            idempotency_key="verification-parent",
        ),
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


async def _fake_verify(*_: Any, **__: Any) -> dict[str, Any]:
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


async def _advance_verification_node(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    """Seed a 3-candidate deep_verification node and fan it out."""
    state = _task_state(run_id)
    state["hypotheses"] = [
        Hypothesis(text=f"candidate-{index}", elo_rating=1200 + index)
        for index in range(3)
    ]
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}deep_verification",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="verification-node",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)
    leased_node = store.claim_task("node", run_id=run_id, db_path=db_path)
    assert leased_node is not None and leased_node.id == node.id
    scheduled = await engine_tasks.execute_node_task(
        leased_node, db_path=db_path
    )
    assert store.complete_task(
        leased_node.id, "node", scheduled, db_path=db_path
    )


async def _run_verification_children_and_aggregate(
    run_id: str, db_path: str
) -> None:
    """Lease the three verification children and commit one aggregate."""
    children = [
        store.claim_task(f"child-{index}", run_id=run_id, db_path=db_path)
        for index in range(3)
    ]
    assert all(child is not None for child in children)
    child_results = await asyncio.gather(
        *[
            engine_tasks.execute_verification_item(child, db_path=db_path)
            for child in children
            if child is not None
        ]
    )
    for index, (child, result) in enumerate(
        zip(children, child_results, strict=True)
    ):
        assert child is not None
        assert store.complete_task(
            child.id, f"child-{index}", result, db_path=db_path
        )
    aggregate = store.claim_task("aggregate", run_id=run_id, db_path=db_path)
    assert aggregate is not None
    result = await engine_tasks.execute_verification_aggregate(
        aggregate, db_path=db_path
    )
    assert result["successful_verifications"] == 3
    assert store.complete_task(
        aggregate.id, "aggregate", result, db_path=db_path
    )


def _assert_verification_committed(run_id: str, db_path: str) -> None:
    """Pin the aggregate-boundary commit: verdicts, evidence, milestone."""
    latest = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert latest is not None
    restored = latest["state"]["state"]["hypotheses"]
    assert all(
        item["deep_verification_verdict"] == "supported" for item in restored
    )
    assert latest["state"]["state"]["articles"][-1]["source_id"] == "probe-1"
    assert restored[0]["enrichments"]["deep_verification"][
        "retrieval_queries"
    ] == ["probe query"]
    assert _milestones(run_id, db_path=db_path) == ["3 hypotheses verified"]
    verification_events = _task_events(
        run_id, "deep_verification", db_path=db_path
    )
    assert len(verification_events) == 1
    assert verification_events[0]["payload"]["successor"] == "ranking"


def _assert_fingerprints_survive_the_checkpoint(
    run_id: str, db_path: str
) -> None:
    """Every committed verification records what it was produced from.

    The durable path is the only one production takes, so a fingerprint
    missing here means no leader is ever recognized as current and deep
    verification re-runs on every cycle for the life of the run. It has to
    survive the checkpoint round-trip to be worth anything on resume.
    """
    from co_scientist.agents.reflection.deep_verification import (
        verification_fingerprint,
    )
    from co_scientist.models import Hypothesis

    latest = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert latest is not None
    state = latest["state"]["state"]
    for payload in state["hypotheses"]:
        # Round-tripped through the checkpoint, not the in-memory object.
        hypothesis = Hypothesis.from_dict(payload)
        assert hypothesis.deep_verification_fingerprint == (
            verification_fingerprint(hypothesis, state["model_name"])
        )


@pytest.mark.asyncio
async def test_verification_children_commit_through_single_aggregator(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verification results update state only at the aggregate boundary."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    await _advance_verification_node(run.id, monkeypatch, isolated_db)

    import co_scientist.agents.reflection.deep_verification as verification

    monkeypatch.setattr(verification, "_verify_one", _fake_verify)
    await _run_verification_children_and_aggregate(run.id, isolated_db)

    _assert_verification_committed(run.id, isolated_db)
    _assert_fingerprints_survive_the_checkpoint(run.id, isolated_db)

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from co_scientist.agents import reflection as _operations_reflection
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from co_scientist.models import Article, Hypothesis, HypothesisReview

import app.engine_tasks.fanout as engine_tasks_fanout_items
import app.engine_tasks.fanout as items
from app import engine_tasks, task_worker
from app.config import settings
from app.engine_tasks import fanout as engine_tasks_fanout
from app.engine_tasks import fanout_aggregates as _recheck_reflection
from app.engine_tasks import fanout_aggregates as engine_tasks_fanout_aggregates
from app.engine_tasks import node as engine_tasks_node
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.fanout import _mature_reflection_specs, _maturity_specs
from app.engine_tasks.fanout_aggregates import _apply_review_items
from app.engine_tasks.support import MATURE_REFLECTION_ITEM_TASK
from app.store import checkpoints, runs
from app.store import retrieval_calls as retrieval
from app.store import tasks as store
from app.store import tasks_lifecycle as lifecycle
from app.store.models import RunStatus, ScientificTask
from app.store.tasks import NewTask
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _drain_ranking_matches,
    _Generator,
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
    assert lifecycle.complete_task(
        supervisor.id, "supervisor", result, db_path=db_path
    )
    review_parent = store.claim_task("parent", run_id=run_id, db_path=db_path)
    assert review_parent is not None
    parent_result = await engine_tasks.execute_node_task(
        review_parent, db_path=db_path
    )
    assert lifecycle.complete_task(
        review_parent.id, "parent", parent_result, db_path=db_path
    )


async def _run_review_children_and_aggregate(run_id: str, db_path: str) -> None:
    first = store.claim_task("child-a", run_id=run_id, db_path=db_path)
    second = store.claim_task("child-b", run_id=run_id, db_path=db_path)
    assert first is not None and second is not None
    assert (
        first.task_type
        == second.task_type
        == engine_tasks_support.REVIEW_ITEM_TASK
    )
    first_result, second_result = await asyncio.gather(
        engine_tasks_fanout_items.execute_review_item(first, db_path=db_path),
        engine_tasks_fanout_items.execute_review_item(second, db_path=db_path),
    )
    assert lifecycle.complete_task(
        first.id, "child-a", first_result, db_path=db_path
    )
    assert lifecycle.complete_task(
        second.id, "child-b", second_result, db_path=db_path
    )
    aggregate = store.claim_task("aggregate", run_id=run_id, db_path=db_path)
    assert aggregate is not None
    aggregate_result = (
        await engine_tasks_fanout_aggregates.execute_review_aggregate(
            aggregate, db_path=db_path
        )
    )
    assert aggregate_result["successful_reviews"] == 2
    assert lifecycle.complete_task(
        aggregate.id, "aggregate", aggregate_result, db_path=db_path
    )


@pytest.mark.asyncio
async def test_review_fanout_uses_independent_leases_and_one_aggregate_commit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    state["hypotheses"] = [Hypothesis(text="alpha"), Hypothesis(text="beta")]
    await _advance_to_review_parent(
        run.id, monkeypatch, _Generator(state), isolated_db
    )

    import co_scientist.agents.reflection.review as review_module

    monkeypatch.setattr(review_module, "review_single_hypothesis", _fake_review)
    await _run_review_children_and_aggregate(run.id, isolated_db)

    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 3
    persisted = checkpoint["state"]["state"]["hypotheses"]
    assert [hypothesis["score"] for hypothesis in persisted] == [8.0, 8.0]
    review_events = _task_events(run.id, "review", db_path=isolated_db)
    assert len(review_events) == 1
    assert (
        review_events[0]["payload"]["successor"] == "comprehensive_reflection"
    )


@pytest.mark.asyncio
async def test_review_fanout_created_during_pause_waits_for_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    original_dispatch = engine_tasks_node._dispatch_node_fanout

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "Paused review fan-out"}
        )
        assert created.status_code == 200, created.text
        run_id = str(created.json()["id"])
        runs.update_run_status(run_id, RunStatus.RUNNING, db_path=isolated_db)
        state = _task_state(run_id)
        state["hypotheses"] = [
            Hypothesis(text="alpha"),
            Hypothesis(text="beta"),
        ]

        async def pause_during_dispatch(
            task: Any,
            node_state: dict[str, Any],
            node_name: str,
            checkpoint_seq: int,
            db_path: str | None,
        ) -> dict[str, Any] | None:
            if node_name == "review":
                paused = client.post(f"/api/runs/{run_id}/pause")
                assert paused.status_code == 200, paused.text
                assert paused.json()["status"] == "paused"
            return await original_dispatch(
                task, node_state, node_name, checkpoint_seq, db_path
            )

        monkeypatch.setattr(
            engine_tasks_node, "_dispatch_node_fanout", pause_during_dispatch
        )
        await _advance_to_review_parent(
            run_id, monkeypatch, _Generator(state), isolated_db
        )

        tasks = store.list_tasks(run_id, db_path=isolated_db)
        review_work = [
            task
            for task in tasks
            if task.task_type
            in {
                engine_tasks_support.REVIEW_ITEM_TASK,
                engine_tasks_support.REVIEW_AGGREGATE_TASK,
            }
        ]
        assert len(review_work) == 3
        saved_run = runs.get_run(run_id, db_path=isolated_db)
        assert saved_run is not None and saved_run.status == "paused"
        assert (
            store.claim_task(
                "before-resume", run_id=run_id, db_path=isolated_db
            )
            is None
        )

        resumed = client.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        claimed = [
            store.claim_task(
                f"after-resume-{index}", run_id=run_id, db_path=isolated_db
            )
            for index in range(2)
        ]
        assert all(item is not None for item in claimed)
        assert {item.task_type for item in claimed if item is not None} == {
            engine_tasks_support.REVIEW_ITEM_TASK
        }


@pytest.mark.asyncio
async def test_review_aggregate_is_ready_after_isolated_child_failure(
    isolated_db: str,
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    failed = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=engine_tasks_support.REVIEW_ITEM_TASK,
            inputs={},
            idempotency_key="failed-child",
            max_attempts=1,
        ),
        db_path=isolated_db,
    )
    aggregate = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=engine_tasks_support.REVIEW_AGGREGATE_TASK,
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


# Preserve rate-park and call-budget exception types through review handlers to
# worker outcome policy.


PARK = LLMRateLimitParkError(1788825600.0, "message_per_day")
OVER_BUDGET = LLMCallBudgetExceededError(2501, 2500)


def _seed_mature_review_item(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> ScientificTask:
    state = _task_state(run_id)
    hypothesis = Hypothesis(text="a mechanism worth reviewing")
    hypothesis.review_disposition = "viable"
    state["hypotheses"] = [hypothesis]
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=MATURE_REFLECTION_ITEM_TASK,
            inputs={
                "checkpoint_seq": checkpoint_seq,
                "hypothesis_id": hypothesis.id,
                "review_mode": "full",
            },
            idempotency_key="control-flow-item",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)
    leased = store.claim_task("item", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


def _install_failing_review(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    # Inject failures inside the review provider seam; replacing the whole
    # handler would hide swallowed parks.
    import co_scientist.agents.reflection.comprehensive_reflection as comp
    from co_scientist.agents.reflection.review_evidence import _ReviewEvidence

    async def _evidence(*_: Any, **__: Any) -> _ReviewEvidence:
        return _ReviewEvidence([], [], [], None)

    async def _observations(*_: Any, **__: Any) -> str | None:
        return None

    async def _call(*_: Any, **__: Any) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(comp, "_review_evidence_for", _evidence)
    monkeypatch.setattr(comp, "_observations_for", _observations)
    monkeypatch.setattr(comp, "call_llm_json", _call)


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
async def test_a_control_flow_error_leaves_the_item_unchanged(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    # Workers dispatch by exception type; wrapping parks or budget errors as
    # RuntimeError changes retry outcomes.
    run = runs.create_run("Task-level science", "extended", "engine", {})
    leased = _seed_mature_review_item(run.id, monkeypatch, isolated_db)
    _install_failing_review(monkeypatch, error)

    with pytest.raises(type(error)):
        await engine_tasks_fanout_items.execute_mature_reflection_item(
            leased, db_path=isolated_db
        )


async def test_an_ordinary_provider_failure_is_still_a_retryable_failure(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "extended", "engine", {})
    leased = _seed_mature_review_item(run.id, monkeypatch, isolated_db)
    _install_failing_review(monkeypatch, ValueError("unparseable answer"))

    with pytest.raises(RuntimeError):
        await engine_tasks_fanout_items.execute_mature_reflection_item(
            leased, db_path=isolated_db
        )


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
def test_a_control_flow_error_escapes_the_ranking_wave(
    error: Exception,
) -> None:
    # gather must propagate parks or waves commit incomplete rounds against an
    # unchanged provider cap.
    from co_scientist.agents.ranking import RankingJudgement

    from app.engine_tasks.ranking import _surviving_judgements

    verdict = RankingJudgement("a", {"decision_summary": "A is stronger"}, 2)

    with pytest.raises(type(error)):
        _surviving_judgements(["pair-0", "pair-1"], [verdict, error])


def test_an_ordinary_judge_failure_still_leaves_its_wave_siblings() -> None:
    from co_scientist.agents.ranking import RankingJudgement

    from app.engine_tasks.ranking import _surviving_judgements

    verdict = RankingJudgement("a", {"decision_summary": "A is stronger"}, 2)

    survived = _surviving_judgements(
        ["pair-0", "pair-1"], [verdict, RuntimeError("judge refused")]
    )

    assert survived.pairs == ["pair-0"]
    assert survived.judgements == [verdict]


def _dispositions_blocking_review() -> HypothesisReview:
    return HypothesisReview(
        review_summary="unsound",
        scores={"scientific_soundness": 2, "novelty": 8},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="rework",
        overall_score=3.0,
    )


def _dispositions_blocked_hypothesis() -> Hypothesis:
    hypothesis = Hypothesis(
        text="alpha", reviews=[_dispositions_blocking_review()]
    )
    hypothesis.review_disposition = "inaccurate"
    return hypothesis


def test_aggregate_reopens_an_idea_a_deeper_review_cleared() -> None:
    hypothesis = _dispositions_blocked_hypothesis()
    hypothesis.enrichments["full"] = {"verdict": "sound"}

    successful, failed, _ = _apply_review_items(
        {hypothesis.id: hypothesis}, [], None
    )

    assert (successful, failed) == (0, 0)
    assert hypothesis.is_rankable()


def test_aggregate_leaves_the_evidence_gate_s_disposition_alone() -> None:
    # The evidence gate owns displaced dispositions; re-deriving
    # evidence_blocked elsewhere strands recovery.
    hypothesis = _dispositions_blocked_hypothesis()
    hypothesis.review_disposition = "evidence_blocked"
    hypothesis.enrichments["full"] = {"verdict": "sound"}

    _apply_review_items({hypothesis.id: hypothesis}, [], None)

    assert hypothesis.review_disposition == "evidence_blocked"


def test_aggregate_keeps_a_hypothesis_no_review_can_grade_untouched() -> None:
    hypothesis = Hypothesis(text="beta")

    _apply_review_items({hypothesis.id: hypothesis}, [], None)

    assert hypothesis.review_disposition is None


def test_aggregate_reads_the_run_s_criteria_when_re_deriving() -> None:
    hypothesis = Hypothesis(
        text="gamma",
        reviews=[
            HypothesisReview(
                review_summary="weak experiment",
                scores={"scientific_soundness": 8, "testability": 1},
                safety_ethical_concerns="none",
                detailed_feedback={},
                constructive_feedback="design a test",
                overall_score=5.0,
            )
        ],
    )
    criteria: list[Any] = ["Discriminating experimental design"]

    _apply_review_items({hypothesis.id: hypothesis}, [], None, criteria)

    assert not hypothesis.is_rankable()


# Isolate matchup faults so retrying one failure does not discard or re-judge
# paid sibling comparisons.


def _install_judge_failing_once(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    import co_scientist.agents.ranking.operations as ranking_module

    box = {"calls": 0}

    async def fake_judge(*_: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        box["calls"] += 1
        if box["calls"] == 1:
            raise RuntimeError("judge provider refused this matchup")
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": int(kwargs["debate_turns"]),
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", fake_judge)
    return box


@pytest.mark.asyncio
async def test_one_failed_matchup_leaves_its_wave_siblings_committed(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=6,
            tournament_pairs=8,
            idempotency_key="ranking-isolation",
        ),
        isolated_db,
    )
    box = _install_judge_failing_once(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)
    await _drain_ranking_matches(run.id, isolated_db)

    rounds = int(scheduled["tournament_rounds"])
    assert box["calls"] == rounds, "siblings of the failed matchup were lost"
    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    committed = checkpoint["state"]["state"]["pending_ranking_matchups"]
    assert len(committed) == rounds - 1
    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert [task.status for task in tasks if task.status == "failed"] == []


# Durable maturity selection must follow the engine rule rather than repeat
# already successful reviews.


def _hypothesis(**enrichments: Any) -> Hypothesis:
    hypothesis = Hypothesis(id="h1", text="a mechanism")
    hypothesis.enrichments.update(enrichments)
    return hypothesis


def test_a_fresh_hypothesis_is_owed_both() -> None:
    assert _maturity_specs(_hypothesis(), 0) == [
        ("h1", "full"),
        ("h1", "simulation"),
    ]


def test_a_succeeded_simulation_is_not_re_enqueued() -> None:
    # Checkpoint sequences make later tool-loop rows new work even though
    # iteration repeats the phase.
    hypothesis = _hypothesis(simulation={"verdict": "breaks_down"})

    for iteration in (0, 1, 2):
        assert _maturity_specs(hypothesis, iteration) == [("h1", "full")]


def test_a_mature_hypothesis_gets_its_recurrent_review() -> None:
    assert _maturity_specs(_hypothesis(full={"verdict": "sound"}), 1) == [
        ("h1", "recurrent")
    ]


def _restore_item(monkeypatch: pytest.MonkeyPatch, mode: str = "full") -> Any:
    idea = Hypothesis(id="idea", text="Scientific claim")
    state = {"hypotheses": [idea], "articles_with_reasoning": "Literature"}
    monkeypatch.setattr(
        items, "_restore_item_checkpoint", lambda *args, **kwargs: (state, 7)
    )
    return SimpleNamespace(
        inputs={"hypothesis_id": idea.id, "review_mode": mode}
    )


@pytest.mark.asyncio
async def test_verification_keeps_raw_payload_and_defers_issuance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _restore_item(monkeypatch)
    raw = {"verdict": "holds", "sub_assumptions": list(range(30))}
    operation = AsyncMock(return_value=raw)
    monkeypatch.setattr(_operations_reflection, "verify_hypothesis", operation)
    result = await items.execute_verification_item(task)
    assert result["verification"] is raw
    assert result["checkpoint_seq"] == 7
    assert operation.await_args is not None
    assert not operation.await_args.args[1].enrichments


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "executor,operation",
    [
        (items.execute_verification_item, "verify_hypothesis"),
        (items.execute_mature_reflection_item, "review_hypothesis"),
    ],
)
@pytest.mark.parametrize(
    "error",
    [LLMRateLimitParkError(9999, "cap"), LLMCallBudgetExceededError(2, 1)],
)
async def test_public_item_task_control_errors_reach_worker(
    monkeypatch: pytest.MonkeyPatch,
    executor: Any,
    operation: str,
    error: Exception,
) -> None:
    task = _restore_item(monkeypatch)
    monkeypatch.setattr(
        _operations_reflection, operation, AsyncMock(side_effect=error)
    )
    with pytest.raises(type(error)) as caught:
        await executor(task)
    assert caught.value is error


@pytest.mark.asyncio
async def test_verification_none_becomes_durable_item_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _restore_item(monkeypatch)
    monkeypatch.setattr(
        _operations_reflection,
        "verify_hypothesis",
        AsyncMock(return_value=None),
    )
    with pytest.raises(RuntimeError, match="deep verification failed for idea"):
        await items.execute_verification_item(task)


@pytest.mark.asyncio
async def test_observation_rejects_missing_literature_before_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = AsyncMock()
    monkeypatch.setattr(_operations_reflection, "observe_hypothesis", operation)
    with pytest.raises(RuntimeError, match="no literature context"):
        await items._run_observation_reflection({}, Hypothesis(text="claim"))
    operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_durable_observation_uses_single_item_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indices: list[tuple[int, int]] = []

    async def observe(
        state: Any,
        hypothesis: Any,
        *,
        hypothesis_index: int = 1,
        total_count: int = 1,
    ) -> dict[str, Any]:
        indices.append((hypothesis_index, total_count))
        return {"classification": "neutral"}

    task = _restore_item(monkeypatch, "observation")
    monkeypatch.setattr(_operations_reflection, "observe_hypothesis", observe)
    result = await items.execute_mature_reflection_item(task)
    assert result["review"] == {"classification": "neutral"}
    assert result["research_ledger"] is None
    assert indices == [(1, 1)]


@pytest.mark.asyncio
async def test_durable_mature_review_keeps_ledger_beside_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _restore_item(monkeypatch)
    review, ledger = {"verdict": "sound"}, {"threads": 4}
    monkeypatch.setattr(
        _operations_reflection,
        "review_hypothesis",
        AsyncMock(
            return_value=_operations_reflection.ReviewRun(
                _operations_reflection.ReviewType.FULL, review, ledger
            )
        ),
    )
    result = await items.execute_mature_reflection_item(task)
    assert result["review"] is review
    assert result["research_ledger"] is ledger
    assert "research_ledger" not in result["review"]


# Blocked ideas get one recurrent recheck; record attempts even on failure so
# later cycles cannot refund it.


def _patch_item(
    monkeypatch: pytest.MonkeyPatch, inputs: dict[str, Any], status: str
) -> None:

    class _Item:
        def __init__(self) -> None:
            self.inputs = inputs
            self.status = status
            self.result: dict[str, Any] | None = None

    monkeypatch.setattr(
        _recheck_reflection,
        "_require_item_task",
        lambda item_id, db_path, kind="": _Item(),
    )


def _recheck_blocking_review() -> HypothesisReview:
    return HypothesisReview(
        review_summary="unsound",
        scores={"scientific_soundness": 2, "novelty": 8},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="rework",
        overall_score=3.0,
    )


def _recheck_blocked_hypothesis(text: str = "alpha") -> Hypothesis:
    hypothesis = Hypothesis(text=text, reviews=[_recheck_blocking_review()])
    hypothesis.review_disposition = "inaccurate"
    return hypothesis


def _state(hypotheses: list[Hypothesis]) -> dict[str, Any]:
    return {"hypotheses": hypotheses, "current_iteration": 0}


def test_the_fanout_schedules_one_recheck_per_blocked_idea() -> None:
    pool = [_recheck_blocked_hypothesis(f"idea {index}") for index in range(20)]

    specs = _mature_reflection_specs(_state(pool))

    assert [spec.hypothesis_id for spec in specs] == [h.id for h in pool]
    assert all(spec.recheck for spec in specs)
    assert {spec.review_mode for spec in specs} == {"recurrent"}


def test_a_failed_recheck_item_still_records_its_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hypothesis = _recheck_blocked_hypothesis()
    _patch_item(
        monkeypatch,
        {"hypothesis_id": hypothesis.id, "recheck": True},
        status="failed",
    )

    applied = _recheck_reflection._apply_mature_reflection_items(
        {hypothesis.id: hypothesis}, ["item-1"], 0, None
    )

    assert applied.failed == 1
    assert _mature_reflection_specs(_state([hypothesis])) == []


def test_a_cascade_item_records_no_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hypothesis = _recheck_blocked_hypothesis()
    _patch_item(
        monkeypatch,
        {"hypothesis_id": hypothesis.id, "review_mode": "full"},
        status="failed",
    )

    _recheck_reflection._apply_mature_reflection_items(
        {hypothesis.id: hypothesis}, ["item-1"], 0, None
    )

    assert len(_mature_reflection_specs(_state([hypothesis]))) == 1


def test_the_cascade_still_owns_the_viable_ideas() -> None:
    viable = Hypothesis(text="cleared")
    viable.review_disposition = "viable"

    specs = _mature_reflection_specs(
        _state([viable, _recheck_blocked_hypothesis()])
    )

    assert [(spec.review_mode, spec.recheck) for spec in specs] == [
        ("full", False),
        ("simulation", False),
        ("recurrent", True),
    ]


def _lease_verification_parent(run_id: str, db_path: str) -> Any:
    parent = store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}deep_verification",
            inputs={"checkpoint_seq": 4},
            idempotency_key="verification-parent",
        ),
        db_path=db_path,
    )
    leased = store.claim_task("parent", run_id=run_id, db_path=db_path)
    assert leased is not None and leased.id == parent.id
    return leased


@pytest.mark.asyncio
async def test_verification_fanout_materializes_one_task_per_unverified_idea(
    isolated_db: str,
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    leased = _lease_verification_parent(run.id, isolated_db)
    state = _task_state(run.id)
    state["hypotheses"] = [
        Hypothesis(text=f"candidate-{index}", elo_rating=1000 + index)
        for index in range(5)
    ]

    result = engine_tasks_fanout._enqueue_verification_fanout(
        leased, state, 4, db_path=isolated_db
    )
    assert len(result["fanout_task_ids"]) == 5
    assert lifecycle.complete_task(
        leased.id, "parent", result, db_path=isolated_db
    )
    claimed = [
        store.claim_task(f"verify-{index}", run_id=run.id, db_path=isolated_db)
        for index in range(5)
    ]
    assert all(item is not None for item in claimed)
    assert {item.task_type for item in claimed if item is not None} == {
        engine_tasks_support.VERIFICATION_ITEM_TASK
    }


@pytest.mark.asyncio
async def test_a_resumed_run_fans_out_only_the_ideas_still_owed_one(
    isolated_db: str,
) -> None:
    # Once-ever verification markers must survive checkpoints or restarts
    # re-fund the whole pool.
    run = runs.create_run("Task-level science", "standard", "engine", {})
    leased = _lease_verification_parent(run.id, isolated_db)
    state = _task_state(run.id)
    verified = Hypothesis(text="already verified")
    verified.enrichments["deep_verification_issued"] = True
    fresh = Hypothesis(text="an evolution child")
    state["hypotheses"] = [
        Hypothesis.from_dict(verified.to_dict()),
        Hypothesis.from_dict(fresh.to_dict()),
    ]

    result = engine_tasks_fanout._enqueue_verification_fanout(
        leased, state, 4, db_path=isolated_db
    )

    assert len(result["fanout_task_ids"]) == 1
    assert lifecycle.complete_task(
        leased.id, "parent", result, db_path=isolated_db
    )
    item = store.claim_task("verify", run_id=run.id, db_path=isolated_db)
    assert item is not None
    assert item.inputs["hypothesis_id"] == state["hypotheses"][1].id


@pytest.mark.asyncio
async def test_a_pool_with_nothing_left_to_verify_advances_into_ranking(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Empty fan-outs still need an immediately claimable aggregate that commits
    # and advances the run.
    run = runs.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    hypotheses = [Hypothesis(text=f"verified-{index}") for index in range(3)]
    for hypothesis in hypotheses:
        hypothesis.enrichments["deep_verification_issued"] = True
    state["hypotheses"] = hypotheses
    checkpoint_seq = _seed_checkpoint(run.id, state)
    node = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}deep_verification",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="verification-node",
        ),
        db_path=isolated_db,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)
    leased_node = store.claim_task("node", run_id=run.id, db_path=isolated_db)
    assert leased_node is not None and leased_node.id == node.id
    scheduled = await engine_tasks.execute_node_task(
        leased_node, db_path=isolated_db
    )
    assert scheduled["fanout_task_ids"] == []
    assert lifecycle.complete_task(
        leased_node.id, "node", scheduled, db_path=isolated_db
    )

    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    result = (
        await engine_tasks_fanout_aggregates.execute_verification_aggregate(
            aggregate, db_path=isolated_db
        )
    )

    assert result["successful_verifications"] == 0
    assert result["failed_verifications"] == 0
    assert lifecycle.complete_task(
        aggregate.id, "aggregate", result, db_path=isolated_db
    )
    successor = store.get_task(result["successor_task_id"], db_path=isolated_db)
    assert successor is not None
    assert successor.task_type == (f"{engine_tasks.NODE_TASK_PREFIX}ranking")


async def _fake_verify(*_: Any, **__: Any) -> dict[str, Any]:
    return {
        "probes": [{"question": "q"}],
        "verdict": "holds",
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
    state = _task_state(run_id)
    state["hypotheses"] = [
        Hypothesis(text=f"candidate-{index}", elo_rating=1200 + index)
        for index in range(3)
    ]
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = store.enqueue_task(
        NewTask(
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
    assert lifecycle.complete_task(
        leased_node.id, "node", scheduled, db_path=db_path
    )


async def _run_verification_children_and_aggregate(
    run_id: str, db_path: str, before_aggregate: Any | None = None
) -> None:
    children = [
        store.claim_task(f"child-{index}", run_id=run_id, db_path=db_path)
        for index in range(3)
    ]
    assert all(child is not None for child in children)
    child_results = await asyncio.gather(
        *[
            engine_tasks_fanout_items.execute_verification_item(
                child, db_path=db_path
            )
            for child in children
            if child is not None
        ]
    )
    for index, (child, result) in enumerate(
        zip(children, child_results, strict=True)
    ):
        assert child is not None
        assert lifecycle.complete_task(
            child.id, f"child-{index}", result, db_path=db_path
        )
    aggregate = store.claim_task("aggregate", run_id=run_id, db_path=db_path)
    assert aggregate is not None
    if before_aggregate is not None:
        before_aggregate()
    result = (
        await engine_tasks_fanout_aggregates.execute_verification_aggregate(
            aggregate, db_path=db_path
        )
    )
    assert result["successful_verifications"] == 3
    assert lifecycle.complete_task(
        aggregate.id, "aggregate", result, db_path=db_path
    )


def _assert_verifications_are_marked_once_ever(
    run_id: str, db_path: str
) -> None:
    # Aggregate boundaries see the whole family and persist attempt markers even
    # when items fail.
    latest = checkpoints.get_latest_checkpoint(run_id, db_path=db_path)
    assert latest is not None
    restored = latest["state"]["state"]["hypotheses"]
    assert all(
        item["enrichments"]["deep_verification_issued"] for item in restored
    )


def _assert_verification_committed(run_id: str, db_path: str) -> None:
    latest = checkpoints.get_latest_checkpoint(run_id, db_path=db_path)
    assert latest is not None
    restored = latest["state"]["state"]["hypotheses"]
    assert all(
        item["deep_verification_verdict"] == "holds" for item in restored
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
    # Verification fingerprints must survive checkpoints or every later cycle
    # repeats the same paid work.
    from co_scientist.agents.reflection.deep_verification import (
        verification_fingerprint,
    )
    from co_scientist.models import Hypothesis

    latest = checkpoints.get_latest_checkpoint(run_id, db_path=db_path)
    assert latest is not None
    state = latest["state"]["state"]
    for payload in state["hypotheses"]:
        hypothesis = Hypothesis.from_dict(payload)
        assert hypothesis.deep_verification_fingerprint == (
            verification_fingerprint(hypothesis, state["model_name"])
        )


@pytest.mark.asyncio
async def test_verification_children_commit_through_single_aggregator(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    await _advance_verification_node(run.id, monkeypatch, isolated_db)

    import co_scientist.agents.reflection as reflection

    monkeypatch.setattr(reflection, "verify_hypothesis", _fake_verify)
    await _run_verification_children_and_aggregate(run.id, isolated_db)

    _assert_verification_committed(run.id, isolated_db)
    _assert_fingerprints_survive_the_checkpoint(run.id, isolated_db)
    _assert_verifications_are_marked_once_ever(run.id, isolated_db)


@pytest.mark.asyncio
async def test_verification_aggregate_pauses_and_resumes_to_ranking(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "Paused verification aggregate"}
        )
        assert created.status_code == 200, created.text
        run_id = str(created.json()["id"])
        runs.update_run_status(run_id, RunStatus.RUNNING, db_path=isolated_db)
        await _advance_verification_node(run_id, monkeypatch, isolated_db)
        checkpoint_before = checkpoints.get_latest_checkpoint(
            run_id, db_path=isolated_db
        )
        assert checkpoint_before is not None
        import co_scientist.agents.reflection as reflection

        monkeypatch.setattr(reflection, "verify_hypothesis", _fake_verify)

        def pause() -> None:
            response = client.post(f"/api/runs/{run_id}/pause")
            assert response.status_code == 200, response.text

        await _run_verification_children_and_aggregate(
            run_id, isolated_db, before_aggregate=pause
        )

        checkpoint = checkpoints.get_latest_checkpoint(
            run_id, db_path=isolated_db
        )
        assert checkpoint is not None
        assert checkpoint["seq"] == checkpoint_before["seq"] + 1
        saved_run = runs.get_run(run_id, db_path=isolated_db)
        assert saved_run is not None and saved_run.status == "paused"
        state = checkpoint["state"]["state"]
        assert all(
            hypothesis["deep_verification_verdict"] == "holds"
            for hypothesis in state["hypotheses"]
        )
        assert state["articles"][-1]["source_id"] == "probe-1"
        metrics = retrieval.get_run_metrics(run_id, db_path=isolated_db)
        assert metrics is not None and metrics["llm_calls"] == 6
        verification_items = [
            task
            for task in store.list_tasks(run_id, db_path=isolated_db)
            if task.task_type == engine_tasks_support.VERIFICATION_ITEM_TASK
        ]
        assert len(verification_items) == 3
        assert all(
            task.status == "completed" and task.result
            for task in verification_items
        )
        [event] = _task_events(run_id, "deep_verification", db_path=isolated_db)
        assert event["payload"]["successor"] == "ranking"
        ranking_tasks = [
            task
            for task in store.list_tasks(run_id, db_path=isolated_db)
            if task.task_type == f"{engine_tasks.NODE_TASK_PREFIX}ranking"
        ]
        assert len(ranking_tasks) == 1
        assert (
            store.claim_task(
                "before-resume", run_id=run_id, db_path=isolated_db
            )
            is None
        )

        resumed = client.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        successor = store.claim_task(
            "after-resume", run_id=run_id, db_path=isolated_db
        )
        assert successor is not None
        assert successor.task_type == f"{engine_tasks.NODE_TASK_PREFIX}ranking"


@pytest.mark.asyncio
async def test_failed_verification_items_record_explicit_unverified(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Failed verification is explicitly unverified with stale fingerprints;
    # spend its once-ever marker anyway.
    run = runs.create_run("Task-level science", "standard", "engine", {})
    await _advance_verification_node(run.id, monkeypatch, isolated_db)

    for index in range(3):
        item = store.claim_task(
            f"child-{index}", run_id=run.id, db_path=isolated_db
        )
        assert item is not None
        assert store.fail_task(
            item.id,
            f"child-{index}",
            "provider failed",
            retryable=False,
            db_path=isolated_db,
        )

    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    result = (
        await engine_tasks_fanout_aggregates.execute_verification_aggregate(
            aggregate, db_path=isolated_db
        )
    )
    assert result["successful_verifications"] == 0
    assert result["failed_verifications"] == 3
    assert lifecycle.complete_task(
        aggregate.id, "aggregate", result, db_path=isolated_db
    )

    latest = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert latest is not None
    restored = latest["state"]["state"]["hypotheses"]
    assert all(
        item["deep_verification_verdict"] == "unverified" for item in restored
    )
    assert all(item["deep_verification_probes"] == [] for item in restored)
    assert all(
        item["deep_verification_fingerprint"] is None for item in restored
    )
    assert all(
        item["enrichments"]["deep_verification_issued"] for item in restored
    )

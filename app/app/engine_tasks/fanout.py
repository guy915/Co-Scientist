"""Durable fan-out scheduling for review, verification, and reflection."""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, NamedTuple

import app.store as store
from app.engine_tasks.fanout_aggregates import (
    _AggregateSpec,
    _enqueue_aggregate_task,
)
from app.engine_tasks.support import (
    GENERATION_AGGREGATE_TASK,
    GENERATION_STRATEGY_TASK,
    MATURE_REFLECTION_AGGREGATE_TASK,
    MATURE_REFLECTION_ITEM_TASK,
    REVIEW_AGGREGATE_TASK,
    REVIEW_ITEM_TASK,
    VERIFICATION_AGGREGATE_TASK,
    VERIFICATION_ITEM_TASK,
    _restore_item_checkpoint,
    _save_exact_checkpoint,
    assert_task_commit_allowed,
)
from app.store import ScientificTask


def _hypothesis_for_item(
    task: ScientificTask, state: dict[str, Any]
) -> tuple[str, Any]:
    """Resolve the item task's target hypothesis from restored state."""
    hypothesis_id = str(task.inputs["hypothesis_id"])
    hypothesis = next(
        (item for item in state["hypotheses"] if item.id == hypothesis_id),
        None,
    )
    if hypothesis is None:
        raise ValueError(
            f"hypothesis {hypothesis_id} is absent from checkpoint"
        )
    return hypothesis_id, hypothesis


async def execute_review_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Review one hypothesis without mutating the shared workflow checkpoint."""
    from co_scientist.agents.reflection.review import (
        ReviewContext,
        review_single_hypothesis,
    )
    from co_scientist.llm import scoped_telemetry

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="review item"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    context = ReviewContext.from_state(state)
    with scoped_telemetry("review") as telemetry:
        review = await review_single_hypothesis(
            hypothesis_text=hypothesis.text,
            context=context,
            hypothesis_index=int(task.inputs["hypothesis_index"]),
        )
    return {
        "hypothesis_id": hypothesis_id,
        "review": dataclasses.asdict(review),
        "model_usage": telemetry.snapshot(),
        "checkpoint_seq": expected_seq,
    }


async def execute_verification_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Deep-verify one hypothesis without mutating the workflow checkpoint."""
    from co_scientist.agents.reflection import verify_hypothesis
    from co_scientist.llm import scoped_telemetry

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="verification item"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    with scoped_telemetry("deep_verification") as telemetry:
        result = await verify_hypothesis(state, hypothesis)
    if result is None:
        raise RuntimeError(f"deep verification failed for {hypothesis_id}")
    return {
        "hypothesis_id": hypothesis_id,
        "verification": result,
        "model_usage": telemetry.snapshot(),
        "checkpoint_seq": expected_seq,
    }


async def _run_observation_reflection(
    state: dict[str, Any], hypothesis: Any
) -> Any:
    """Run the observation-mode reflection against retrieved literature."""
    from co_scientist.agents.reflection import observe_hypothesis

    if not state.get("articles_with_reasoning"):
        raise RuntimeError("observation review has no literature context")
    return await observe_hypothesis(state, hypothesis)


async def execute_mature_reflection_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute one disclosed mature Reflection mode for one hypothesis."""
    from co_scientist.agents.reflection import ReviewType, review_hypothesis
    from co_scientist.llm import scoped_telemetry

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="mature reflection"
    )
    hypothesis_id, hypothesis = _hypothesis_for_item(task, state)
    mode = ReviewType(str(task.inputs["review_mode"]))
    with scoped_telemetry("comprehensive_reflection") as telemetry:
        ledger: dict[str, Any] | None = None
        if mode is ReviewType.OBSERVATION:
            result = await _run_observation_reflection(state, hypothesis)
        else:
            _, result, ledger = await review_hypothesis(state, hypothesis, mode)
    if result is None:
        raise RuntimeError(f"{mode.value} review failed for {hypothesis_id}")
    return {
        "hypothesis_id": hypothesis_id,
        "review_mode": mode.value,
        "review": result,
        # Beside the review rather than inside it: the aggregate hands
        # this to the run's state, while the review goes to the
        # hypothesis. A ledger stamped on the review would ride into
        # every later checkpoint through enrichments.
        "research_ledger": ledger,
        "model_usage": telemetry.snapshot(),
        "checkpoint_seq": expected_seq,
    }


@dataclass(frozen=True)
class _StrategyInputs:
    """Read-only generation inputs every strategy task is scheduled with.

    Attributes:
        literature: Retrieved articles with reasoning, for lit-backed debate.
        reference_index: The run's citation reference index.
    """

    literature: Any
    reference_index: Any


@dataclass(frozen=True)
class _GenerationPlan:
    """The fan-out's shape, decided before any durable row is written.

    Attributes:
        task_specs: (strategy, count, index, total) spec per durable
            strategy task. Debate strategies get one task per hypothesis,
            so index is the debate's position and total the family's whole
            batch size (the diversity-angle denominator, finding E14);
            other strategies run as one task where index is 0 and total
            equals count.
        inputs: Literature and reference index every strategy task reads.
        aggregate_spec: Spec for the aggregate that folds the strategies in.
    """

    task_specs: list[tuple[str, int, int, int]]
    inputs: _StrategyInputs
    aggregate_spec: _AggregateSpec


def _generation_task_specs(
    strategy_counts: dict[str, int],
) -> list[tuple[str, int, int, int]]:
    """Return (strategy, count, index, total) specs per durable task.

    Debate strategies get one task per hypothesis so debates run
    independently; every other strategy gets a single task producing its
    whole count. ``total`` carries the strategy's whole batch size to
    every task: the engine assigns each debate a diversity angle from its
    index modulo the batch, and a per-debate task that only knew its own
    count of 1 could never diverge from its siblings (finding E14).

    Splitting the non-debate strategies per hypothesis was tried and
    reverted. It looked like it should help -- uniform items let the worker
    cohort fill instead of waiting on one oversized task -- but a measured
    production express run spent 145s per generate cycle against a 137s
    baseline, so it bought no wall time. It is not cost-neutral either: the
    tools drafting call emits its whole count in one response, so N tasks
    means N drafting calls where there was one, and N concurrent writers
    against the single SQLite writer where there were fewer. Re-measure the
    strategy's internal draft/validate loops before trying this again.
    """
    debate_strategies = {"debate_lit", "debate_only"}
    return [
        (strategy, 1, index, count)
        for strategy, count in strategy_counts.items()
        if strategy in debate_strategies
        for index in range(count)
    ] + [
        (strategy, count, 0, count)
        for strategy, count in strategy_counts.items()
        if strategy not in debate_strategies and count > 0
    ]


def _enqueue_generation_strategy_tasks(
    task: ScientificTask,
    planned_seq: int,
    task_specs: Sequence[tuple[str, int, int, int]],
    inputs: _StrategyInputs,
    conn: sqlite3.Connection,
) -> list[ScientificTask]:
    """Enqueue one durable task per planned generation strategy.

    Args:
        task: The generation node task scheduling the fan-out.
        planned_seq: Checkpoint sequence the plan committed at.
        task_specs: (strategy, count, index, total) spec per durable task.
        inputs: Literature and reference index every strategy reads.
        conn: Open connection of the caller's transaction.

    Returns:
        The enqueued per-strategy tasks, in spec order.
    """
    return [
        store.enqueue_task(
            store.NewTask(
                run_id=task.run_id,
                task_type=GENERATION_STRATEGY_TASK,
                inputs={
                    "checkpoint_seq": planned_seq,
                    "strategy": strategy,
                    "count": count,
                    "strategy_index": index,
                    # The strategy's whole batch size, so a per-debate
                    # task can angle its debate against the full sibling
                    # set (finding E14). Tasks enqueued before this input
                    # existed simply run without a diversity angle.
                    "debate_total": total,
                    "literature": inputs.literature,
                    "reference_text": inputs.reference_index.text,
                    "reference_sources": inputs.reference_index.sources,
                },
                idempotency_key=f"generation:{strategy}:{planned_seq}:{index}:{count}",
                priority=87,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "generation_strategy": strategy,
                    "strategy_index": index,
                },
            ),
            conn=conn,
        )
        for strategy, count, index, total in task_specs
    ]


def _generation_aggregate_spec(counts: Any) -> _AggregateSpec:
    """Return the generation family's aggregate spec, carrying its counts."""
    return _AggregateSpec(
        task_type=GENERATION_AGGREGATE_TASK,
        priority=81,
        key_prefix="generation",
        extra_inputs={"counts": dataclasses.asdict(counts)},
    )


async def _plan_generation_fanout(state: dict[str, Any]) -> _GenerationPlan:
    """Prepare the generation inputs and decide the fan-out's shape.

    Runs entirely before the transaction, so the provider work the
    preparation does never happens while the SQLite write lock is held.

    Args:
        state: Workflow state the generation node was entered with.

    Returns:
        The per-strategy task specs, their shared inputs, and the
        aggregate spec carrying the planned counts.
    """
    from co_scientist.agents.generation import prepare_generation

    plan = await prepare_generation(state)
    return _GenerationPlan(
        task_specs=_generation_task_specs(plan.counts.strategy_counts),
        inputs=_StrategyInputs(plan.literature, plan.reference_index),
        aggregate_spec=_generation_aggregate_spec(plan.counts),
    )


def _commit_generation_fanout(
    task: ScientificTask,
    checkpoint_seq: int,
    envelope: dict[str, Any],
    plan: _GenerationPlan,
    db_path: str | None,
) -> tuple[int, list[ScientificTask], ScientificTask]:
    """Write the plan checkpoint and every fan-out row in one transaction.

    Args:
        task: The generation node task scheduling the fan-out.
        checkpoint_seq: Checkpoint sequence the plan was built against.
        envelope: Serialized workflow state to checkpoint.
        plan: The fan-out shape from ``_plan_generation_fanout``.
        db_path: Optional override for the SQLite database path.

    Returns:
        The committed checkpoint sequence, the per-strategy tasks in spec
        order, and the aggregate task.
    """
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        planned_seq = _save_exact_checkpoint(
            task,
            envelope,
            checkpoint_seq,
            conn,
            changed_message="checkpoint changed during generation planning",
        )
        items = _enqueue_generation_strategy_tasks(
            task,
            planned_seq,
            plan.task_specs,
            plan.inputs,
            conn,
        )
        aggregate = _enqueue_aggregate_task(
            task,
            items,
            planned_seq,
            conn,
            plan.aggregate_spec,
        )
    return planned_seq, items, aggregate


async def _enqueue_generation_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Commit generation planning and enqueue each enabled strategy."""
    from co_scientist.checkpoint import serialize_workflow_state

    plan = await _plan_generation_fanout(state)
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    planned_seq, items, aggregate = _commit_generation_fanout(
        task, checkpoint_seq, envelope, plan, db_path
    )
    return {
        "checkpoint_seq": planned_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "generate",
    }


@dataclass(frozen=True)
class _StrategyRunInputs:
    """Per-task inputs one generation strategy executes against.

    Attributes:
        reference_index: The run's citation reference index.
        literature: Retrieved literature synthesis, debate_lit only.
        debate_index: This task's position in the strategy's parallel
            debate batch (finding E14); None predates the wiring.
        debate_total: The debate batch's whole size; see debate_index.
    """

    reference_index: Any
    literature: Any
    debate_index: int | None = None
    debate_total: int | None = None


async def _run_debate_strategy(
    state: dict[str, Any],
    strategy: str,
    count: int,
    inputs: _StrategyRunInputs,
) -> tuple[list[Any], list[dict[str, Any]], int]:
    """Run one debate strategy task and return its hypotheses/transcripts.

    The task carries its position and batch size within the strategy's
    parallel debates (finding E14), which the engine turns into a
    distinct diversity angle per task.
    """
    from co_scientist.agents.generation.citations import ReferenceIndex
    from co_scientist.agents.generation.debate import (
        DebateBatchPosition,
        generate_with_debate,
    )

    literature = inputs.literature if strategy == "debate_lit" else None
    debate_reference = (
        inputs.reference_index
        if strategy == "debate_lit"
        else ReferenceIndex(text="", sources={})
    )
    batch_position = None
    if inputs.debate_index is not None and inputs.debate_total is not None:
        batch_position = DebateBatchPosition(
            inputs.debate_index, inputs.debate_total
        )
    # The app's mypy config skips following co_scientist imports, so the
    # engine's declared return type arrives here as Any; restate it on the
    # binding rather than passing an unchecked value on (mirrors
    # _checkpoint_and_advance's next_task_type cast in the sibling module).
    result: tuple[
        list[Any], list[dict[str, Any]], int
    ] = await generate_with_debate(
        state=state,
        count=count,
        articles_with_reasoning=literature,
        reference_index=debate_reference,
        batch_position=batch_position,
    )
    return result


async def _run_generation_strategy(
    state: dict[str, Any],
    strategy: str,
    count: int,
    inputs: _StrategyRunInputs,
) -> tuple[list[Any], list[dict[str, Any]], int]:
    """Execute one generation strategy and return its hypotheses/transcripts.

    Every branch returns ``(hypotheses, transcripts, llm_calls)``:
    ``llm_calls`` is the real LLM completions the strategy spent (finding
    L3), and every leaf strategy function already reports it -- only the
    non-debate branches have no transcripts, so they pair their
    ``(hypotheses, llm_calls)`` return with an empty transcript list here.
    """
    from co_scientist.agents.generation.assumptions import (
        generate_with_assumptions,
    )
    from co_scientist.agents.generation.literature_tools import (
        generate_with_tools,
    )

    if strategy == "tools":
        hypotheses, llm_calls = await generate_with_tools(
            state, count, inputs.reference_index
        )
        return hypotheses, [], llm_calls
    if strategy in {"debate_lit", "debate_only"}:
        return await _run_debate_strategy(state, strategy, count, inputs)
    if strategy == "assumptions":
        # Preserve the durable path's existing assumptions contract: it
        # omits the plan's literature and reference index. The graph
        # coordinator supplies both. Sharing dispatch would change its
        # grounding; planning/finalization can be shared independently.
        hypotheses, llm_calls = await generate_with_assumptions(state, count)
        return hypotheses, [], llm_calls
    raise ValueError(f"unsupported generation strategy: {strategy}")


async def execute_generation_strategy(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute one generation strategy against a read-only plan checkpoint.

    A debate task is one debate of the strategy's parallel batch; the
    batch total defaults to the pre-E14 shape (a lone debate with no
    siblings to diverge from) when the input predates the wiring.

    ``skills_used`` is which third-party data sources this strategy's
    science-skill commands reached, so the report can attribute them;
    see ``co_scientist.skills``. Empty without skills installed.
    """
    from co_scientist.agents.generation.citations import ReferenceIndex
    from co_scientist.llm import scoped_telemetry
    from co_scientist.skills import scoped_skill_usage

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="generation strategy"
    )
    strategy = str(task.inputs["strategy"])
    count = int(task.inputs["count"])
    inputs = _StrategyRunInputs(
        reference_index=ReferenceIndex(
            text=str(task.inputs.get("reference_text") or ""),
            sources=dict(task.inputs.get("reference_sources") or {}),
        ),
        literature=task.inputs.get("literature"),
        debate_index=int(task.inputs.get("strategy_index") or 0),
        debate_total=int(task.inputs.get("debate_total") or count),
    )
    with (
        scoped_telemetry("generate") as telemetry,
        scoped_skill_usage() as skills,
    ):
        hypotheses, transcripts, llm_calls = await _run_generation_strategy(
            state, strategy, count, inputs
        )
    return {
        "strategy": strategy,
        "hypotheses": [hypothesis.to_dict() for hypothesis in hypotheses],
        "transcripts": transcripts,
        "llm_calls": llm_calls,
        "model_usage": telemetry.snapshot(),
        "skills_used": skills.snapshot(),
        "checkpoint_seq": expected_seq,
    }


def _enqueue_review_item_tasks(
    task: ScientificTask,
    unreviewed: Sequence[Any],
    checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> list[ScientificTask]:
    """Enqueue one review-item task per unreviewed hypothesis."""
    return [
        store.enqueue_task(
            store.NewTask(
                run_id=task.run_id,
                task_type=REVIEW_ITEM_TASK,
                inputs={
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis.id,
                    "hypothesis_index": index,
                },
                idempotency_key=f"review:item:{checkpoint_seq}:{hypothesis.id}",
                priority=85,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "specialist": "reflection.initial",
                },
            ),
            conn=conn,
        )
        for index, hypothesis in enumerate(unreviewed)
    ]


_REVIEW_AGGREGATE_SPEC = _AggregateSpec(
    task_type=REVIEW_AGGREGATE_TASK, priority=80, key_prefix="review"
)


def _create_fanout_tasks(
    enqueue_items: Callable[[sqlite3.Connection], list[ScientificTask]],
    task: ScientificTask,
    checkpoint_seq: int,
    spec: _AggregateSpec,
    db_path: str | None,
) -> tuple[list[ScientificTask], ScientificTask]:
    """Enqueue a family's item tasks and its aggregate in one transaction.

    Args:
        enqueue_items: Enqueues the family's per-item tasks on the open
            connection and returns them in order.
        task: The node task scheduling the fan-out.
        checkpoint_seq: Checkpoint sequence the fan-out is planned at.
        spec: The aggregate's per-family task type, priority, and key.
        db_path: Optional override for the SQLite database path.

    Returns:
        A tuple of (item tasks, aggregate task).
    """
    with store.transaction(db_path) as conn:
        assert_task_commit_allowed(task, conn)
        items = enqueue_items(conn)
        aggregate = _enqueue_aggregate_task(
            task, items, checkpoint_seq, conn, spec
        )
    return items, aggregate


def _enqueue_review_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Materialize one independently leasable task per unreviewed hypothesis.

    **This is the canonical mirror of the published review chaining
    (FIX-9).** ``02-generation.md`` L24-26 and ``01-supervisor.md`` L34-38
    create one ``Reflection / ReviewHypothesis`` task per new hypothesis
    and add each to the global task queue; ``03-reflection.md`` L12 then
    fetches that hypothesis by id. This function is that step: one queue
    row per hypothesis, keyed and leased independently, which is also what
    production runs.

    The LangGraph engine's ``review_node`` reviews the whole batch behind
    one synchronous barrier instead. That divergence is deliberate and
    reference-only: for a pool of five it is a single comparative call
    against five, on a path with no production cost pressure to justify
    the 5x. Neither side is drifting -- the decision is that the durable
    path owns the mirror, so changes to per-hypothesis chaining belong
    here, not there.
    """
    from co_scientist.models import has_peer_review

    unreviewed = [
        hypothesis
        for hypothesis in state["hypotheses"]
        if not has_peer_review(hypothesis)
    ]
    items, aggregate = _create_fanout_tasks(
        partial(_enqueue_review_item_tasks, task, unreviewed, checkpoint_seq),
        task,
        checkpoint_seq,
        _REVIEW_AGGREGATE_SPEC,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "review",
    }


def _enqueue_verification_item_tasks(
    task: ScientificTask,
    selected: Sequence[Any],
    checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> list[ScientificTask]:
    """Enqueue one deep-verification task per selected hypothesis."""
    return [
        store.enqueue_task(
            store.NewTask(
                run_id=task.run_id,
                task_type=VERIFICATION_ITEM_TASK,
                inputs={
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis.id,
                },
                idempotency_key=f"verification:item:{checkpoint_seq}:{hypothesis.id}",
                priority=88,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "specialist": "reflection.deep_verification",
                },
            ),
            conn=conn,
        )
        for hypothesis in selected
    ]


_VERIFICATION_AGGREGATE_SPEC = _AggregateSpec(
    task_type=VERIFICATION_AGGREGATE_TASK,
    priority=82,
    key_prefix="verification",
)


def _enqueue_verification_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Materialize one leasable deep-verification task per idea."""
    from co_scientist.agents.reflection import select_hypotheses_to_verify

    selected = select_hypotheses_to_verify(
        state["hypotheses"], state["model_name"]
    )
    items, aggregate = _create_fanout_tasks(
        partial(
            _enqueue_verification_item_tasks, task, selected, checkpoint_seq
        ),
        task,
        checkpoint_seq,
        _VERIFICATION_AGGREGATE_SPEC,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "deep_verification",
    }


def _maturity_specs(hypothesis: Any, iteration: int) -> list[tuple[str, str]]:
    """Return full/simulation/recurrent specs by enrichment maturity.

    Delegates to the engine's rule rather than restating it. This was a
    second copy, and a copy of a scheduling rule is a copy that will one
    day disagree: both copies carried the same defect (re-issuing a
    simulation review that had already succeeded, whenever the full
    review had not), and fixing it in one place would have left the
    durable path -- the one production actually runs -- still paying for
    it.
    """
    from co_scientist.agents.reflection.review_gate import reviews_needed

    return [
        (hypothesis.id, review.value)
        for review in reviews_needed(hypothesis, iteration)
    ]


class _ReflectionSpec(NamedTuple):
    """One reflection item this fan-out will materialize.

    Attributes:
        hypothesis_id: The hypothesis the review runs against.
        review_mode: The ``ReviewType`` value to issue.
        recheck: Whether this is a blocked idea's one recheck for the run
            rather than part of the mature cascade. Carried into the
            item's inputs so the aggregate can record the attempt even
            when the item never completed.
    """

    hypothesis_id: str
    review_mode: str
    recheck: bool = False


def _viable_specs(
    hypothesis: Any, iteration: int, literature: Any
) -> list[_ReflectionSpec]:
    """Return the cascade specs due for one viable hypothesis."""
    specs: list[_ReflectionSpec] = []
    if literature and not hypothesis.reflection_notes:
        specs.append(_ReflectionSpec(hypothesis.id, "observation"))
    return specs + [
        _ReflectionSpec(hypothesis_id, review_mode)
        for hypothesis_id, review_mode in _maturity_specs(hypothesis, iteration)
    ]


def _recheck_specs(state: dict[str, Any]) -> list[_ReflectionSpec]:
    """Return the one recurrent review each blocked idea is still owed.

    The cascade above selects on ``viable``, so nothing in it can ever
    reach an idea the initial review gate blocked -- which leaves the
    derived disposition (FIX-4) with no later verdict to derive from. The
    engine owns both bounds (once per hypothesis for the whole run, and a
    run-wide ceiling), read off the pool so they survive a checkpoint
    round trip and a resume.
    """
    from co_scientist.agents.reflection.review_gate import (
        RECHECK_REVIEW_TYPE,
        recheck_targets,
    )

    return [
        _ReflectionSpec(hypothesis.id, RECHECK_REVIEW_TYPE.value, True)
        for hypothesis in recheck_targets(state["hypotheses"])
    ]


def _mature_reflection_specs(state: dict[str, Any]) -> list[_ReflectionSpec]:
    """Return the reflection specs due: the cascade, then the rechecks."""
    iteration = int(state.get("current_iteration", 0))
    literature = state.get("articles_with_reasoning")
    specs: list[_ReflectionSpec] = []
    for hypothesis in state["hypotheses"]:
        if hypothesis.review_disposition == "viable":
            specs += _viable_specs(hypothesis, iteration, literature)
    return specs + _recheck_specs(state)


def _enqueue_mature_reflection_item_tasks(
    task: ScientificTask,
    specs: Sequence[_ReflectionSpec],
    checkpoint_seq: int,
    conn: sqlite3.Connection,
) -> list[ScientificTask]:
    """Enqueue one durable task per maturity-appropriate reflection spec."""
    return [
        store.enqueue_task(
            store.NewTask(
                run_id=task.run_id,
                task_type=MATURE_REFLECTION_ITEM_TASK,
                inputs={
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": spec.hypothesis_id,
                    "review_mode": spec.review_mode,
                    "recheck": spec.recheck,
                },
                idempotency_key=f"reflection:{spec.review_mode}:{checkpoint_seq}:{spec.hypothesis_id}",
                priority=86,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "reflection_mode": spec.review_mode,
                },
            ),
            conn=conn,
        )
        for spec in specs
    ]


_MATURE_REFLECTION_AGGREGATE_SPEC = _AggregateSpec(
    task_type=MATURE_REFLECTION_AGGREGATE_TASK,
    priority=80,
    key_prefix="reflection",
)


def _enqueue_mature_reflection_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Schedule maturity-appropriate Reflection modes as durable tasks."""
    specs = _mature_reflection_specs(state)
    items, aggregate = _create_fanout_tasks(
        partial(
            _enqueue_mature_reflection_item_tasks, task, specs, checkpoint_seq
        ),
        task,
        checkpoint_seq,
        _MATURE_REFLECTION_AGGREGATE_SPEC,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "comprehensive_reflection",
    }

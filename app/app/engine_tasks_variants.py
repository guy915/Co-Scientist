"""Durable task executors for computational discovery.

A discovery run evolves a program instead of a hypothesis, so its tasks
work against the ``code_variants`` tables rather than a workflow
checkpoint. Three types cover the loop:

``propose``
    Ask the model for a child of one parent variant, and record it.
``evaluate``
    Run one variant's cascade in the run's workspace and score it.
``aggregate``
    Read the generation's results and enqueue the next round.

**Evaluation never raises on a bad program.** Our retry rule makes every
exception except ``UnsupportedTaskError`` a retryable failure, so a
variant that crashes -- which is the expected case, not the exceptional
one -- would otherwise burn its whole retry budget re-running identical
failing code, three times, and then strand the run. ``evaluate_variant``
already returns every outcome as a result; this module's job is not to
undo that by raising around it.
"""

from __future__ import annotations

import logging
from typing import Any

from app import discovery_report, store
from app.discovery_execution import evaluate_confined
from app.discovery_spec import evaluator_spec
from app.engine_tasks_support import SupersededTaskError
from app.store import RunStatus, ScientificTask

logger = logging.getLogger(__name__)

VARIANT_PROPOSE_TASK = "engine.fanout.variant.propose"
VARIANT_EVALUATE_TASK = "engine.fanout.variant.evaluate"
VARIANT_AGGREGATE_TASK = "engine.fanout.variant.aggregate"


def _run_config(run_id: str, db_path: str | None) -> dict[str, Any]:
    """Reads a run's stored config, or raises if the run is gone."""
    run = store.get_run(run_id, db_path=db_path)
    if run is None:
        raise SupersededTaskError(f"run {run_id} no longer exists")
    return dict(run.config or {})


def _variant_for_task(
    task: ScientificTask, db_path: str | None
) -> dict[str, Any]:
    """Resolves the variant a task targets.

    A missing variant is superseded rather than failed, and the ordinary
    reason for one is a rejected proposal: an evaluation is enqueued
    alongside its proposal, so when the patch does not apply the
    evaluation arrives with nothing to evaluate. That is a normal
    outcome, not an error, and it is not fixed by retrying -- nor is the
    other cause, a run whose derived data was cleared underneath it.
    """
    variant_id = str(task.inputs["variant_id"])
    variant = store.get_code_variant(variant_id, db_path=db_path)
    if variant is None:
        raise SupersededTaskError(
            f"variant {variant_id} was never recorded; its proposal was "
            f"most likely rejected"
        )
    return variant


def _behaviour_of(variant: dict[str, Any], result: Any) -> dict[str, Any]:
    """Measures the variant's behaviour for the archive.

    The raw measurement, not the cell it lands in: under an adaptive or
    CVT grid the cell depends on the whole population, so it is derived
    when selection runs rather than frozen here.
    """
    from co_scientist.agents.code_evolve import describe

    behaviour: dict[str, Any] = describe(
        dict(variant["source"]),
        operator=variant.get("operator"),
        metrics=dict(result.metrics),
    )
    return behaviour


def _to_evaluation(
    result: Any, behaviour: dict[str, Any]
) -> store.VariantEvaluation:
    """Converts an engine EvaluationResult into its stored form."""
    return store.VariantEvaluation(
        status=str(result.status.value),
        fitness=result.fitness,
        objective_values=list(result.objective_values),
        behaviour=behaviour,
        duration_seconds=sum(stage.duration_seconds for stage in result.stages),
        stages=[
            {
                "name": stage.name,
                "status": str(stage.status.value),
                "exit_code": stage.exit_code,
                "duration_seconds": stage.duration_seconds,
            }
            for stage in result.stages
        ],
        metrics=dict(result.metrics),
        artifacts=dict(result.artifacts),
    )


def _variant_message(
    variant: dict[str, Any], result: Any, direction: str
) -> str:
    """One line naming what this attempt did, for the reader's timeline.

    Carried on the event as ``message`` because that is the key every
    consumer already reads -- the live activity row, the stage log, the
    SSE console. Without it each attempt renders as the bare word
    "Discovery", which is a heartbeat rather than a narrative.
    """
    from app.discovery_report import measured

    move = (variant["operator"] or "seed").replace("_", " ")
    if result.fitness is None:
        return f"Attempt {variant['ordinal']} ({move}) {result.status.value}"
    return (
        f"Attempt {variant['ordinal']} ({move}) scored "
        f"{measured(result.fitness, direction)}"
    )


def _record_evaluation(
    run_id: str,
    variant: dict[str, Any],
    result: Any,
    direction: str,
    db_path: str | None,
) -> None:
    """Persists one evaluation, then narrates it -- in that order."""
    store.record_variant_evaluation(
        str(variant["id"]),
        _to_evaluation(result, _behaviour_of(variant, result)),
        db_path=db_path,
    )
    logger.info(
        "Variant %s scored %s (%s)",
        variant["ordinal"],
        result.fitness,
        result.status.value,
    )
    _announce_variant(run_id, variant, result, direction, db_path)


def _announce_variant(
    run_id: str,
    variant: dict[str, Any],
    result: Any,
    direction: str,
    db_path: str | None,
) -> None:
    """Records one evaluated variant as a run event.

    Without this a discovery run streams nothing at all: the loop is
    three durable tasks and none of them emitted, so the live activity
    log sat empty for the whole run and a search that was working looked
    identical to one that had stalled. An evaluated variant is the right
    unit -- it is minutes of work, not a poll tick, so this is nowhere
    near the per-tick write stream that starves the single writer.

    Best effort: a run must not fail because its narration did.
    """
    try:
        store.append_event(
            run_id,
            "discovery",
            {
                "message": _variant_message(variant, result, direction),
                "ordinal": variant["ordinal"],
                "generation": variant["generation"],
                "operator": variant["operator"] or "seed",
                "status": result.status.value,
                "fitness": result.fitness,
            },
            db_path=db_path,
        )
    except Exception:
        logger.exception("Could not record variant %s", variant["ordinal"])


async def execute_variant_evaluate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Runs one variant's evaluation cascade and records the result.

    Returns:
        The variant's id, status and fitness, for the aggregate to read.
        A variant that crashed returns just as normally as one that
        scored -- ``status`` is what tells them apart.
    """
    from co_scientist.code_eval import EvaluationRequest
    from co_scientist.workspace import open_variant_workspace

    variant = _variant_for_task(task, db_path)
    config = _run_config(task.run_id, db_path)
    spec = evaluator_spec(config)
    # The variant's own directory, never the run's: evaluations run
    # concurrently, and two of them writing their programs to the same
    # paths would each run partly the other's code. Both would return a
    # plausible number attributed to the wrong variant, and nothing in
    # either result would show it.
    session = open_variant_workspace(task.run_id, str(variant["id"]))
    result = await evaluate_confined(
        session, EvaluationRequest(spec=spec, files=dict(variant["source"]))
    )
    _record_evaluation(
        task.run_id,
        variant,
        result,
        spec.objectives[0].direction.value,
        db_path,
    )
    return {
        "variant_id": variant["id"],
        "ordinal": variant["ordinal"],
        "status": result.status.value,
        "fitness": result.fitness,
    }


def _parent_context(
    task: ScientificTask, db_path: str | None
) -> tuple[dict[str, Any] | None, Any]:
    """Loads the parent variant and the engine-side view of it."""
    from co_scientist.agents.code_evolve import ParentVariant

    parent_id = task.inputs.get("parent_variant_id")
    if parent_id is None:
        return None, ParentVariant(source={})
    parent = store.get_code_variant(str(parent_id), db_path=db_path)
    if parent is None:
        raise SupersededTaskError(f"parent variant {parent_id} is gone")
    return parent, ParentVariant(
        source=dict(parent["source"]),
        status=str(parent["status"]),
        fitness=parent["fitness"],
        metrics=dict(parent.get("metrics") or {}),
        artifacts=dict(parent.get("artifacts") or {}),
        ordinal=int(parent["ordinal"]),
    )


def _seed_variant(
    task: ScientificTask, config: dict[str, Any], db_path: str | None
) -> dict[str, Any]:
    """Records the starting program without asking the model for it.

    A run's first variant is given, not proposed: there is nothing to
    derive it from, and putting it through the proposal path would spend
    an LLM call to reproduce a program we already have -- badly, since
    the prompt would be showing the model an empty parent.
    """
    from app.engine_tasks_variants_schedule import inherited_sources

    starting = inherited_sources(config, db_path=db_path)
    # A run that inherits an archive has one seed task per program it
    # carries forward; the index names which. Clamped rather than
    # indexed blindly, because the previous run can lose a variant
    # between the generation being enqueued and this task running.
    index = min(
        int(task.inputs.get("seed_index", 0)), len(starting.sources) - 1
    )
    variant_id = store.add_code_variant(
        store.NewCodeVariant(
            run_id=task.run_id,
            variant_id=task.id,
            source=starting.sources[index],
            rationale=(
                "Carried forward from an earlier run's archive."
                if starting.inherited
                else "Starting program, as configured for the run."
            ),
            created_by_agent="discovery.seed",
        ),
        db_path=db_path,
    )
    return {"variant_id": variant_id, "operator": None, "seed": True}


def _completion_spec(model_name: str) -> Any:
    """Builds the completion spec for a proposal call.

    The budget goes through ``thinking_safe_max_tokens`` because a
    proposal is a long-form answer -- a whole patch envelope -- behind a
    chain of thought that is billed against the same allowance. Sized for
    the answer alone, the reasoning consumes all of it and the call comes
    back empty, having been paid for in full.
    """
    from co_scientist.llm_types import CompletionSpec

    from app.config import thinking_safe_max_tokens

    return CompletionSpec(
        model_name=model_name,
        max_tokens=thinking_safe_max_tokens(model_name, 8_000),
    )


def _record_child(
    task: ScientificTask,
    parent_row: dict[str, Any],
    proposal: Any,
    db_path: str | None,
) -> dict[str, Any]:
    """Stores an accepted proposal as a child of its parent."""
    variant_id = store.add_code_variant(
        store.NewCodeVariant(
            run_id=task.run_id,
            variant_id=task.id,
            source=proposal.source,
            parent_id=str(parent_row["id"]),
            generation=int(parent_row["generation"]) + 1,
            operator=proposal.operator.value,
            rationale=proposal.rationale,
            diff=proposal.patch,
        ),
        db_path=db_path,
    )
    return {
        "variant_id": variant_id,
        "operator": proposal.operator.value,
        "changed": list(proposal.changed),
    }


async def execute_variant_propose(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Derives one child variant from one parent and records it.

    The child's id is the task's own id, so a retry that already wrote a
    variant re-derives the same row rather than minting a second one --
    the idempotency key cannot change while the run makes no progress,
    and a duplicated variant would be indistinguishable from a real one.

    Returns:
        The new variant's id, or a rejection. A patch that does not apply
        is reported, not raised: it is an ordinary outcome of asking for
        an exact-context edit, and raising would spend the task's retry
        budget re-asking a question whose answer will not change.
    """
    from co_scientist.agents.code_evolve import (
        ProposalRejectedError,
        propose_variant,
        select_operator,
    )
    from co_scientist.workspace import open_variant_workspace

    from app.config import settings

    config = _run_config(task.run_id, db_path)
    parent_row, parent = _parent_context(task, db_path)
    if parent_row is None:
        return _seed_variant(task, config, db_path)

    operator = select_operator(parent_failed=parent.failed)
    session = open_variant_workspace(task.run_id, task.id)
    try:
        proposal = await propose_variant(
            session,
            parent,
            operator=operator,
            evaluator=evaluator_spec(config),
            spec=_completion_spec(settings.model_name),
        )
    except ProposalRejectedError as exc:
        logger.info("Variant proposal rejected: %s", exc)
        return {"variant_id": None, "rejected": str(exc)}

    return _record_child(task, parent_row, proposal, db_path)


def _next_generation_parents(
    variants: list[dict[str, Any]], config: dict[str, Any]
) -> list[str | None]:
    """Chooses one parent per child of the next generation.

    One parent per child, drawn from the diversity archive rather than
    cycled through a fixed top-k: the archive already spends part of the
    generation on the strongest elites and part on a uniform draw across
    occupied niches, so a separate "how many distinct parents" knob would
    only be able to contradict it.
    """
    from app.engine_tasks_variants_schedule import (
        DEFAULT_CHILDREN_PER_GENERATION,
        budget_value,
        select_parents,
    )

    children = budget_value(
        config, "children_per_generation", DEFAULT_CHILDREN_PER_GENERATION
    )
    parents = select_parents(variants, children, config=config)
    return [str(parent["id"]) for parent in parents]


def _finish_run(
    run_id: str,
    summary: dict[str, Any],
    variants: list[dict[str, Any]],
    coverage: tuple[int, float],
    db_path: str | None,
) -> None:
    """Publishes the run's report and marks it completed.

    In that order, and both here: the report is what moves the run out
    of ``running`` in the reader's terms, and a run left running forever
    is indistinguishable from one that is stuck -- to the reader and to
    the recovery sweep that re-schedules interrupted runs on boot.
    Publishing is best effort inside ``discovery_report.publish``, so a
    report that cannot be built still leaves a completed run rather than
    a failing task that retries the whole finished search.
    """
    logger.info(
        "Discovery run %s finished after generation %s (best %s)",
        run_id,
        summary["generation"],
        summary["best_fitness"],
    )
    discovery_report.publish(run_id, variants, coverage, db_path=db_path)
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=db_path)


async def execute_variant_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Reads a generation's results and enqueues the next one.

    Returns:
        What the generation achieved and whether the run continues.
        Reaching the generation budget is a normal ending, not a
        failure, and is reported as ``continued: False``.
    """
    from app.engine_tasks_variants_schedule import (
        DEFAULT_MAX_GENERATIONS,
        archive_summary,
        budget_value,
        enqueue_generation,
        freeze_grid_if_ready,
    )

    config = _run_config(task.run_id, db_path)
    generation = int(task.inputs.get("generation", 0))
    variants = store.list_code_variants(task.run_id, db_path=db_path)
    # Before selecting: once the run has enough variants to tessellate,
    # fix the cells so they stop moving underneath it.
    config = freeze_grid_if_ready(task.run_id, variants, config, db_path)
    best = store.best_code_variant(task.run_id, db_path=db_path)
    summary: dict[str, Any] = {
        "generation": generation,
        "variants_so_far": len(variants),
        "best_fitness": None if best is None else best["fitness"],
        "best_variant_id": None if best is None else best["id"],
    }

    limit = budget_value(config, "max_generations", DEFAULT_MAX_GENERATIONS)
    parents = _next_generation_parents(variants, config)
    if generation + 1 >= limit or not parents:
        coverage = archive_summary(variants, config)
        _finish_run(task.run_id, summary, variants, coverage, db_path)
        return {**summary, "continued": False}

    with store.transaction(db_path) as conn:
        enqueued = enqueue_generation(
            task.run_id, generation + 1, parents, conn=conn
        )
    return {**summary, "continued": True, "enqueued": enqueued}

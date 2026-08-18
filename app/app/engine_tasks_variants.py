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

from app import store
from app.discovery_spec import evaluator_spec
from app.engine_tasks_support import SupersededTaskError
from app.store import ScientificTask

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

    A missing variant is superseded rather than failed: the row can only
    be gone because the run was deleted or its derived data cleared, and
    neither is fixed by retrying.
    """
    variant_id = str(task.inputs["variant_id"])
    variant = store.get_code_variant(variant_id, db_path=db_path)
    if variant is None:
        raise SupersededTaskError(f"variant {variant_id} no longer exists")
    return variant


def _to_evaluation(result: Any) -> store.VariantEvaluation:
    """Converts an engine EvaluationResult into its stored form."""
    return store.VariantEvaluation(
        status=str(result.status.value),
        fitness=result.fitness,
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


async def execute_variant_evaluate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Runs one variant's evaluation cascade and records the result.

    Returns:
        The variant's id, status and fitness, for the aggregate to read.
        A variant that crashed returns just as normally as one that
        scored -- ``status`` is what tells them apart.
    """
    from co_scientist.code_eval import EvaluationRequest, evaluate_variant
    from co_scientist.workspace import open_run_workspace

    variant = _variant_for_task(task, db_path)
    spec = evaluator_spec(_run_config(task.run_id, db_path))
    session = open_run_workspace(task.run_id)
    result = await evaluate_variant(
        session,
        EvaluationRequest(spec=spec, files=dict(variant["source"])),
    )
    store.record_variant_evaluation(
        str(variant["id"]), _to_evaluation(result), db_path=db_path
    )
    logger.info(
        "Variant %s scored %s (%s)",
        variant["ordinal"],
        result.fitness,
        result.status.value,
    )
    return {
        "variant_id": variant["id"],
        "ordinal": variant["ordinal"],
        "status": result.status.value,
        "fitness": result.fitness,
    }

"""Scheduling the generations of a discovery run.

Where ``engine_tasks_variants`` executes one unit of work, this module
decides what work exists. Split apart because the scheduling rules --
how many children, bred from which parents, and when to stop -- are the
part worth reading on their own, and because the executors are the part
that has to stay boringly exception-free.

The chain is fixed and enqueued in one pass per generation: a propose
task, an evaluate task depending on it, and one aggregate depending on
every evaluate. Enqueuing the evaluate up front rather than reactively
from the proposal is what lets the variant id be the propose task's own
id -- known before the proposal runs, and stable across its retries.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from app import store
from app.discovery_spec import (
    discovery_config,
    evaluator_spec,
)
from app.discovery_spec import (
    is_discovery_run as is_discovery_run,
)
from app.engine_tasks_variants import (
    VARIANT_AGGREGATE_TASK,
    VARIANT_EVALUATE_TASK,
    VARIANT_PROPOSE_TASK,
)
from app.store import ScientificTask

logger = logging.getLogger(__name__)

# Defaults for a discovery run's budget. Deliberately small: a
# generation is a full LLM call plus a subprocess per child, and the
# cost is the product of these two numbers with the run's own iteration.
DEFAULT_MAX_GENERATIONS = 8
DEFAULT_CHILDREN_PER_GENERATION = 4
DEFAULT_PARENTS_PER_GENERATION = 2


def budget_value(config: dict[str, Any] | None, key: str, fallback: int) -> int:
    """Reads one positive integer from the run's discovery block.

    A malformed or non-positive value falls back rather than raising:
    unlike the evaluator spec, a bad budget has an obviously correct
    default, so refusing the run over one would be stricter without
    being safer.
    """
    raw = (discovery_config(config) or {}).get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return fallback
    return raw


def select_parents(
    variants: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Chooses which variants the next generation breeds from.

    Scored variants come first, best last-attempt-wins-ties order; then
    unscored ones, most recent first, because a failure is only worth
    breeding from while its error is still the one blocking progress.

    Failures are included at all -- rather than filtered out as useless
    parents -- because the repair operator turns one into a working
    program, and a generation in which everything failed would otherwise
    have nothing to breed from and end the run at its first bad round.
    """
    scored = sorted(
        (v for v in variants if v["fitness"] is not None),
        key=lambda v: (-float(v["fitness"]), int(v["ordinal"])),
    )
    unscored = sorted(
        (v for v in variants if v["fitness"] is None),
        key=lambda v: -int(v["ordinal"]),
    )
    return (scored + unscored)[:limit]


def _enqueue_child(
    run_id: str,
    parent_id: str | None,
    slot: str,
    conn: sqlite3.Connection,
) -> ScientificTask:
    """Enqueues one propose task and the evaluate that follows it."""
    propose = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=VARIANT_PROPOSE_TASK,
            inputs={"parent_variant_id": parent_id},
            idempotency_key=f"variant:propose:{slot}",
            priority=80,
            provenance={"specialist": "discovery.propose"},
        ),
        conn=conn,
    )
    return store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=VARIANT_EVALUATE_TASK,
            # The proposal writes its variant under its own task id, so
            # this is knowable before the proposal has run.
            inputs={"variant_id": propose.id},
            idempotency_key=f"variant:evaluate:{slot}",
            priority=75,
            dependencies=(propose.id,),
            provenance={"specialist": "discovery.evaluate"},
        ),
        conn=conn,
    )


def _enqueue_aggregate(
    run_id: str,
    generation: int,
    dependencies: list[str],
    conn: sqlite3.Connection,
) -> ScientificTask:
    """Enqueues the round's aggregate, gated on every evaluation."""
    return store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=VARIANT_AGGREGATE_TASK,
            inputs={"generation": generation},
            idempotency_key=f"variant:aggregate:{generation}",
            priority=70,
            dependencies=tuple(dependencies),
            provenance={"specialist": "discovery.aggregate"},
        ),
        conn=conn,
    )


def enqueue_generation(
    run_id: str,
    generation: int,
    parents: list[str | None],
    *,
    conn: sqlite3.Connection,
) -> int:
    """Enqueues one generation's proposals, evaluations and aggregate.

    Args:
        run_id: The run.
        generation: The generation being created, counting from zero.
        parents: One entry per child, naming its parent variant. None
            means the seed program, which is recorded rather than
            proposed.
        conn: The transaction to enqueue within, so a generation appears
            whole or not at all -- a half-enqueued round leaves an
            aggregate waiting on evaluations nobody scheduled.

    Returns:
        How many children were enqueued.
    """
    evaluations = [
        _enqueue_child(run_id, parent, f"{generation}:{index}", conn).id
        for index, parent in enumerate(parents)
    ]
    _enqueue_aggregate(run_id, generation, evaluations, conn)
    logger.info(
        "Discovery generation %s enqueued %s children for run %s",
        generation,
        len(evaluations),
        run_id,
    )
    return len(evaluations)


def enqueue_discovery_bootstrap(
    run_id: str, *, db_path: str | None = None
) -> None:
    """Starts a discovery run at its seed program."""
    with store.transaction(db_path) as conn:
        enqueue_generation(run_id, 0, [None], conn=conn)


async def bootstrap_discovery(
    run: store.RunRow, emit: Any, db_path: str | None
) -> dict[str, Any]:
    """Starts a discovery run at its seed program.

    The evaluator spec is built here, before anything is enqueued, so a
    misconfigured run fails at its first task with a message naming the
    problem -- rather than enqueueing a generation whose every variant
    then fails identically for a reason no single result explains.
    """
    spec = evaluator_spec(run.config)
    enqueue_discovery_bootstrap(run.id, db_path=db_path)
    await emit(
        "scientific_task",
        {"task": "bootstrap", "status": "completed", "mode": "discovery"},
    )
    return {
        "mode": "discovery",
        "objective": spec.objective.metric,
        "direction": spec.objective.direction.value,
        "stages": [stage.name for stage in spec.stages],
    }

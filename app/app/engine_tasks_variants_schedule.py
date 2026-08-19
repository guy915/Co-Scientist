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


def _archive_entries(variants: list[dict[str, Any]]) -> list[Any]:
    """Rebuilds the archive's view of a run from stored rows.

    Behaviour is read back raw; the cell it lands in is computed by the
    grid, because under an adaptive or CVT strategy a variant's cell
    depends on every other variant and cannot be frozen at write time.
    """
    from co_scientist.agents.code_evolve import ArchiveEntry

    return [
        ArchiveEntry(
            variant_id=str(v["id"]),
            fitness=v["fitness"],
            objective_values=tuple(v.get("objective_values") or [v["fitness"]]),
            behaviour=dict(v.get("behaviour") or {}),
            ordinal=int(v["ordinal"]),
        )
        for v in variants
    ]


def select_parents(
    variants: list[dict[str, Any]],
    count: int,
    *,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Chooses which variants the next generation breeds from.

    Delegates the strategy to the engine's MAP-Elites archive: parents
    come from the best variant *of each kind* rather than from the top of
    one ranked list. Selecting by score alone is what made a run polish
    a single basin for its whole budget -- the best few variants of a
    generation are usually near-copies, so breeding from them produces
    more of the same while the score creeps up and nothing looks wrong.

    Variants that never scored are kept in the pool. The repair operator
    turns one into a working program, and a generation in which
    everything failed would otherwise have nothing to breed from and end
    the run at its first bad round.
    """
    from co_scientist.agents.code_evolve import select_parents as choose

    from app.discovery_spec import grid

    by_id = {str(v["id"]): v for v in variants}
    chosen = choose(_archive_entries(variants), count, grid=grid(config))
    return [by_id[entry.variant_id] for entry in chosen]


def freeze_grid_if_ready(
    run_id: str,
    variants: list[dict[str, Any]],
    config: dict[str, Any],
    db_path: str | None = None,
) -> dict[str, Any]:
    """Fixes the run's tessellation once it has enough variants to.

    Until a CVT grid is frozen every read re-clusters, so a variant can
    change cells because a later one arrived: cell ids cannot be
    compared across generations and the occupied-cell count can go
    *down*. Freezing writes the centroids into the run config, after
    which assignment is nearest-centroid and nothing already placed
    moves again.

    Done here, in the aggregate, because it is the one task per
    generation -- a per-variant freeze would race, and several workers
    would each write a different tessellation over the same run.

    Returns:
        The run config, updated in place when a freeze happened.
    """
    from co_scientist.agents.code_evolve import freeze, projection_to_json

    from app.discovery_spec import DISCOVERY_CONFIG_KEY, grid

    current = grid(config)
    frozen = freeze([v.get("behaviour") or {} for v in variants], current)
    if frozen.projection == current.projection:
        return config
    block = dict(config.get(DISCOVERY_CONFIG_KEY) or {})
    block["grid"] = {
        **(block.get("grid") or {}),
        "strategy": frozen.strategy.value,
        "cells": frozen.cells,
        # The whole projection, not just the centroids: the scaling and
        # one-hot layout are derived from the population too, so storing
        # centroids alone would let the coordinate system drift
        # underneath them and re-label old variants anyway.
        "projection": projection_to_json(frozen.projection),
    }
    updated = {**config, DISCOVERY_CONFIG_KEY: block}
    store.set_run_config(run_id, updated, db_path=db_path)
    logger.info(
        "Discovery run %s froze its archive at %s cells",
        run_id,
        len(frozen.projection.centroids),
    )
    return updated


def archive_summary(
    variants: list[dict[str, Any]], config: dict[str, Any] | None
) -> tuple[int, float]:
    """How many archive cells a run reached, and how evenly.

    Both numbers, because either alone misleads: a high cell count can
    still be a collapsed run if almost every variant shares one cell,
    and a high evenness over two cells is not coverage. See
    ``grid.coverage`` for the measure.
    """
    from co_scientist.agents.code_evolve import archive_coverage

    from app.discovery_spec import grid

    scored = [v for v in variants if v.get("behaviour")]
    if not scored:
        return 0, 0.0
    occupied, evenness = archive_coverage(
        _archive_entries(scored), grid=grid(config)
    )
    return int(occupied), float(evenness)


def pareto_variant_ids(variants: list[dict[str, Any]]) -> set[str]:
    """The variants no other variant dominates across every objective.

    With one objective this is the joint best; with several it is the set
    of real trades, which is what a multi-objective run's reader needs to
    see instead of a single "winner" that is only best on axis one.
    """
    from co_scientist.code_eval import pareto_front

    scored = [v for v in variants if v["fitness"] is not None]
    values = [
        tuple(v.get("objective_values") or [v["fitness"]]) for v in scored
    ]
    return {str(scored[index]["id"]) for index in pareto_front(values)}


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

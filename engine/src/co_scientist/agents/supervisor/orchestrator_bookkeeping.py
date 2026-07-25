"""Orchestrator bookkeeping carried between scheduling decisions.

Holds the state the loop point carries forward itself rather than reading
from the workflow: the proximity/pool anchors, the rank-stability counter,
the last work task, and the settlement allowance that bounds how long owed
tournament coverage may override a budget ceiling. The decision node stays
in ``orchestrator.py`` and the observable statistics in
``orchestrator_stats.py``; ``orchestrator.py`` re-exports these names for
compatibility.
"""

from __future__ import annotations

from typing import Any

from co_scientist.models import Hypothesis
from co_scientist.scheduling import (
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    policy,
)


def _init_bookkeeping(hypotheses: list[Hypothesis]) -> dict[str, Any]:
    """Seed orchestrator bookkeeping on the first loop-point decision.

    Anchors the pool sizes to the post-initial-generation pool so the first
    decision sees no proximity backlog and a yield tie — which, with the last
    work task treated as the initial GENERATE, evolves the leaders first
    (matching the established first-iteration behavior) before later cycles
    alternate into generation.
    """
    pool_size = len(hypotheses)
    return {
        # Sentinel so the first decision's Elo comparison never counts as
        # "stable" (there is no prior cycle to be stable against).
        "prev_top_elo": None,
        "rank_stable_cycles": 0,
        "pool_at_last_proximity": pool_size,
        "pool_at_last_decision": pool_size,
        "last_work_task": TaskType.GENERATE.value,
        # None until a settlement episode opens: the override may fire, and
        # the allowance is sized from the backlog observed at that moment.
        # Both fields return to None whenever the backlog clears.
        "settlement_allowance": None,
        "unmatched_at_last_settlement": None,
    }


def _is_settlement_rank(
    stats: SchedulerStats, decision: SupervisorDecision
) -> bool:
    """Return whether this decision is a ranking round that settles coverage.

    Re-derived by running the policy's own owed-coverage check against the
    same stats rather than inferred from ``next_task``: a RANK is a
    settlement round only when that check asked for one. Inferring it from
    "RANK while anything is unmatched" charged ordinary calibration ranking
    to the allowance, which drained an episode before it began.

    The check is a pure function of ``stats`` with no I/O, so re-running it
    is exact and cheap, and the policy stays free of any settlement state of
    its own.
    """
    return (
        decision.next_task is TaskType.RANK
        and policy._check_owed_coverage(stats) is not None
    )


def _initial_settlement_allowance(stats: SchedulerStats) -> int:
    """Return the most settlement rounds that could ever be useful.

    One round covers at most two unmatched hypotheses, and the pool admits
    only so many distinct pairings, so the allowance is the smaller of the
    two. Mirrors ``ranking_lifecycle._coverage_floor``, which bounds the
    rounds an individual tournament schedules for the same reason.
    """
    rankable = stats.rankable_count
    max_pairs = rankable * (rankable - 1) // 2
    return min((stats.unmatched_rankable_count + 1) // 2, max_pairs)


def _settled_allowance(
    book: dict[str, Any],
    stats: SchedulerStats,
    decision: SupervisorDecision,
) -> tuple[int | None, int | None]:
    """Return the (allowance, last-unmatched) pair for the next decision.

    The allowance is scoped to a *settlement episode*, not to the run. An
    episode opens on the first round the owed-coverage check requests and
    closes when the backlog reaches zero, at which point both fields return
    to None so a later backlog re-arms from what it actually owes.

    Within an episode the counter is initialised once, is charged on every
    settlement round whether or not the round helped, floors at zero, and is
    never increased -- so an episode fires finitely often. A new episode can
    open only after the backlog reached zero, which is to say only after
    settlement succeeded, so the run still reaches a terminal decision.
    """
    if _is_settlement_rank(stats, decision):
        allowance = book.get("settlement_allowance")
        if allowance is None:
            allowance = _initial_settlement_allowance(stats)
        return (
            max(0, int(allowance) - 1),
            stats.unmatched_rankable_count,
        )
    if stats.unmatched_rankable_count == 0:
        # Episode over: nothing is owed, so the counter re-arms.
        return None, None
    return (
        book.get("settlement_allowance"),
        book.get("unmatched_at_last_settlement"),
    )


def _next_bookkeeping(
    book: dict[str, Any],
    stats: SchedulerStats,
    decision: SupervisorDecision,
) -> dict[str, Any]:
    """Compute the bookkeeping to carry into the next decision.

    Updates the rank-stability counter and previous top Elo, resets the
    proximity anchor after a proximity task, remembers the pool size and the
    last *work* task (generate/evolve) so the next decision can measure yield
    and break ties, and advances the settlement-episode allowance that bounds
    how long owed tournament coverage may override a budget ceiling (see
    :func:`_settled_allowance`).
    """
    updated = dict(book)
    updated["prev_top_elo"] = stats.top_elo
    updated["rank_stable_cycles"] = stats.rank_stable_cycles
    updated["pool_at_last_decision"] = stats.pool_size
    if decision.next_task is TaskType.PROXIMITY:
        updated["pool_at_last_proximity"] = stats.pool_size
    if decision.next_task in (TaskType.GENERATE, TaskType.EVOLVE):
        updated["last_work_task"] = decision.next_task.value
    allowance, last_unmatched = _settled_allowance(book, stats, decision)
    updated["settlement_allowance"] = allowance
    updated["unmatched_at_last_settlement"] = last_unmatched
    return updated

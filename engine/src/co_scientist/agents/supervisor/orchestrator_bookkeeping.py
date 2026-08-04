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

from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor
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


def _initial_settlement_allowance(hypotheses: list[Hypothesis]) -> int:
    """Return the most settlement rounds that could ever be useful.

    Delegates to ``ranking_lifecycle._coverage_floor`` rather than restating
    it: one round covers at most two owed matches and the pool admits only so
    many distinct pairings, which is the same arithmetic over the same pool
    that bounds the rounds an individual tournament schedules.

    A near-copy that read the scheduler's zero-match count instead agreed with
    the floor only at the extremes. The floor sums what each rankable idea
    still owes against ``TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS``, so ten ideas
    sitting at one match each owed the tournament five rounds and the
    orchestrator none -- and the orchestrator's is the number that decides how
    long settlement may run.
    """
    return _coverage_floor(hypotheses)


def _settled_allowance(
    book: dict[str, Any],
    stats: SchedulerStats,
    decision: SupervisorDecision,
    hypotheses: list[Hypothesis],
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

    Note the two quantities in play. Whether an episode is open or closed
    follows the scheduler's own owed-coverage check, which asks whether any
    rankable idea has *no* match at all; how many rounds the open episode may
    spend follows the tournament's coverage floor over the same pool, which
    asks how many matches every rankable idea still owes. The first is a
    trigger and the second a size, so they are deliberately different
    questions -- but the size must be the tournament's, or the orchestrator
    stops funding rounds the tournament is still asking for.
    """
    if _is_settlement_rank(stats, decision):
        allowance = book.get("settlement_allowance")
        if allowance is None:
            allowance = _initial_settlement_allowance(hypotheses)
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
    hypotheses: list[Hypothesis],
) -> dict[str, Any]:
    """Compute the bookkeeping to carry into the next decision.

    Updates the rank-stability counter and previous top Elo, resets the
    proximity anchor after a proximity task, remembers the pool size and the
    last *work* task (generate/evolve) so the next decision can measure yield
    and break ties, and advances the settlement-episode allowance that bounds
    how long owed tournament coverage may override a budget ceiling (see
    :func:`_settled_allowance`).

    Args:
        book: Orchestrator bookkeeping from before this decision.
        stats: The statistics this decision was made from.
        decision: The scheduling decision just taken.
        hypotheses: The pool ``stats`` was computed from, read for the
            tournament coverage a fresh settlement episode is sized from.

    Returns:
        The bookkeeping to carry into the next decision.
    """
    updated = dict(book)
    updated["prev_top_elo"] = stats.top_elo
    updated["rank_stable_cycles"] = stats.rank_stable_cycles
    updated["pool_at_last_decision"] = stats.pool_size
    if decision.next_task is TaskType.PROXIMITY:
        updated["pool_at_last_proximity"] = stats.pool_size
    if decision.next_task in (TaskType.GENERATE, TaskType.EVOLVE):
        updated["last_work_task"] = decision.next_task.value
    allowance, last_unmatched = _settled_allowance(
        book, stats, decision, hypotheses
    )
    updated["settlement_allowance"] = allowance
    updated["unmatched_at_last_settlement"] = last_unmatched
    return updated

"""Stagnation is answered with evolution before it stops the run (FIX-7).

Listing 01 L55-58 states the response to a leaderboard that has stopped
improving: ``IF hypothesis quality has stopped improving THEN CREATE new
Task (Agent: Evolution, Action: "EvolveTopHypotheses")``. Ours answered
the *transition* into stagnation that way (``_tie_break``) but answered
standing stagnation by terminating -- ``_check_convergence`` sits above
the generate/evolve fall-through, so at two stable cycles the run stopped
whether or not evolution had ever been given the episode.

These are control-flow-shape assertions: the same stats decide
differently on the one bit that says whether evolution has had its turn,
and the wait is bounded by the iteration budget directly below.
"""

from __future__ import annotations

from co_scientist.scheduling import (
    Budget,
    TaskType,
    TerminationReason,
    decide_next_task,
)
from tests._scheduling import healthy_stats


def test_stagnation_evolves_before_it_terminates() -> None:
    """A settled leaderboard evolution has not answered is not converged."""
    stats = healthy_stats(
        rank_stable_cycles=2, iteration=2, evolved_since_stable=False
    )
    decision = decide_next_task(
        stats, Budget(max_iterations=4), convergence_cycles=2
    )
    assert not decision.terminate
    assert decision.next_task is TaskType.EVOLVE


def test_stagnation_terminates_once_evolution_has_answered_it() -> None:
    """The same stats converge on the one bit that changed."""
    stats = healthy_stats(
        rank_stable_cycles=2, iteration=2, evolved_since_stable=True
    )
    decision = decide_next_task(
        stats, Budget(max_iterations=4), convergence_cycles=2
    )
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.CONVERGED


def test_the_extra_evolve_cycle_cannot_outlive_the_iteration_budget() -> None:
    """What bounds the wait: the check directly below convergence.

    Blocking convergence defers rather than loops -- a run that has spent
    its iterations still stops, and reports ``completed`` rather than
    ``converged``, which is the honest reason.
    """
    stats = healthy_stats(
        rank_stable_cycles=5, iteration=4, evolved_since_stable=False
    )
    decision = decide_next_task(
        stats, Budget(max_iterations=4), convergence_cycles=2
    )
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.COMPLETED

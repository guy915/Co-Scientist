"""The Supervisor's published ``WHILE`` guard, armed per tier (FIX-1).

Listing 01 (``01-supervisor.md`` L17) runs its main loop ``WHILE
NumberOfIdeas < MaxIdeas AND NumberOfMatchesPerIdea < MaxMatchesPerIdea``.
Both predicates were implemented (``scheduling.policy_checks``) and both
were ``None`` on every production run, because the tier table never
carried them and ``engine_adapter.opts`` forwarded only ``max_llm_calls``.

These tests assert the *shape of the control flow*, not the numbers: for
every tier, a run that has just done the work that tier is configured for
must still be schedulable. Sizing either ceiling at or below the tier's
own steady state is the trap -- the run would terminate immediately after
its first tournament with a ``max_matches_per_idea`` reason, which reads
as a converged run rather than as a misconfigured ceiling.
"""

from __future__ import annotations

import pytest
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    TaskType,
    TerminationReason,
)
from co_scientist.scheduling.policy import decide_next_task
from co_scientist.scheduling.policy_cadence import (
    RESEARCH_OVERVIEW_MIN_LLM_CALLS,
)

from app import run_modes
from app.engine_adapter.opts import _generator_kwargs

_TIERS = ("express", "standard", "extended", "ultra")


def _tier_budget(tier: str) -> Budget:
    """Build the engine ``Budget`` a run of ``tier`` actually reaches."""
    cfg = run_modes.resolved_run_config({"tier": tier})
    kwargs = _generator_kwargs(cfg, "offline/test", None, None)
    return Budget(
        max_iterations=int(kwargs["max_iterations"]),
        **kwargs["options"].budget,
    )


def _steady_state_coverage(cfg: dict[str, int]) -> float:
    """Average matches per idea the tier's own tournament budget buys.

    Each judged match increments the tally of both participants, so a
    tournament of ``tournament_pairs`` matches contributes ``2 *
    tournament_pairs`` participations, spread over the ideas that existed
    when it ran -- the initial pool, which is the smallest denominator the
    run ever divides by and therefore the highest coverage it can report.
    """
    return (
        2.0
        * cfg["tournament_pairs"]
        * cfg["max_iterations"]
        / (cfg["initial_hypotheses_count"])
    )


def _worked_stats(cfg: dict[str, int]) -> SchedulerStats:
    """Stats for a run that has done exactly the work its tier configures."""
    pool = cfg["initial_hypotheses_count"] + (
        cfg["evolution_max_count"] * cfg["max_iterations"]
    )
    return SchedulerStats(
        pool_size=pool,
        reviewed_count=pool,
        unreviewed_count=0,
        rankable_count=cfg["initial_hypotheses_count"],
        match_coverage=_steady_state_coverage(cfg),
        total_matches=2 * cfg["tournament_pairs"] * cfg["max_iterations"],
        iteration=0,
    )


@pytest.mark.parametrize("tier", _TIERS)
def test_tier_arms_the_published_while_guard(tier: str) -> None:
    """Both predicates the listing names reach the engine's Budget."""
    budget = _tier_budget(tier)
    assert budget.max_ideas is not None
    assert budget.max_matches_per_idea is not None


@pytest.mark.parametrize("tier", _TIERS)
def test_ceilings_sit_above_the_tier_own_steady_state(tier: str) -> None:
    """A tier's ceilings must not bind on the work that tier configures.

    The arithmetic half of the trap: ``max_matches_per_idea`` at or below
    the tier average is spent by the first tournament, and ``max_ideas`` at
    or below the pool the tier is configured to grow is spent by its last
    evolution round -- both strictly, since each ceiling fires on equality.
    """
    cfg = run_modes.RUN_TIER_DEFAULTS[tier]
    budget = _tier_budget(tier)
    assert budget.max_matches_per_idea is not None
    assert budget.max_matches_per_idea > _steady_state_coverage(cfg)
    assert budget.max_ideas is not None
    assert budget.max_ideas > cfg["initial_hypotheses_count"] + (
        cfg["evolution_max_count"] * cfg["max_iterations"]
    )


@pytest.mark.parametrize("tier", _TIERS)
def test_first_tournament_does_not_terminate_the_run(tier: str) -> None:
    """The control-flow half: the run is still schedulable after its work.

    An undersized ceiling does not error -- ``_budget_termination`` sits
    above every productive check, so the run simply stops and reports
    ``max_matches_per_idea``/``max_ideas``. This asserts the decision the
    scheduler actually makes, which is what a pinned constant cannot.
    """
    cfg = run_modes.RUN_TIER_DEFAULTS[tier]
    decision = decide_next_task(_worked_stats(cfg), _tier_budget(tier))
    assert decision.termination_reason not in {
        TerminationReason.MAX_MATCHES_PER_IDEA,
        TerminationReason.MAX_IDEAS,
    }
    assert decision.next_task is not TaskType.TERMINATE


def test_periodic_overview_gate_reads_extended_and_up_only() -> None:
    """FIX-6's cost gate against this project's own tier table.

    ``RESEARCH_OVERVIEW_MIN_LLM_CALLS`` docstrings itself as "exactly
    extended's ``max_llm_calls``", a claim that lives in the engine
    package and can drift silently from this project's own tier table --
    nothing else binds the two. This pins the arithmetic that makes the
    engine's cadence check read as "extended and ultra, never express or
    standard": the gate must sit strictly above standard's ceiling and at
    or below extended's, so retuning either tier without this test would
    only be caught by reading generated run costs after the fact.
    """
    assert (
        run_modes.RUN_TIER_DEFAULTS["standard"]["max_llm_calls"]
        < RESEARCH_OVERVIEW_MIN_LLM_CALLS
        <= run_modes.RUN_TIER_DEFAULTS["extended"]["max_llm_calls"]
    )

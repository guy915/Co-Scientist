"""The two periodic checks: system-wide feedback, and the overview.

Split from ``policy_checks`` on that module's size cap, and split
together because they are one subject: listing 01's two "IF enough time
has passed" branches (L60-63 and L65-69), each made observable as a
cadence over the iteration counter rather than a wall clock. Both are
maintenance, so both sit below every required transition and above
convergence; ``policy._ordered_checks`` is where that order lives.
``policy_checks`` re-exports both names, so the policy's own imports and
every existing caller are unchanged.
"""

from __future__ import annotations

from typing import Final

from co_scientist.scheduling.models import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
)

RESEARCH_OVERVIEW_MIN_LLM_CALLS: Final = 7000
"""Smallest declared run ceiling that funds a periodic overview firing.

Exactly the extended tier's ``max_llm_calls`` (``app.run_modes``), so the
gate reads "extended and ultra". Unlike meta-review's companion -- one
ordinary call -- the overview is the largest prompt in the system and the
caller most likely to climb the budget-escalation ladder, so a firing is
budgeted at one call plus up to two escalation retries. Express (1200)
runs a single iteration and would fire it before it had a second cycle to
feed; standard (2500) buys one extra cycle for it to feed, which is not
worth three calls at the overview's size.
"""

RESEARCH_OVERVIEW_CADENCE_CYCLES: Final = 2
"""Work cycles between periodic firings.

Two rather than one so a firing is separated from the next by a full
generate-and-rank round: an overview drafted from a pool that has not
changed since the last one tells generation nothing new. At this cadence
extended (3 iterations) fires once and ultra (4) at most twice.
"""


def _check_meta_review_cadence(
    stats: SchedulerStats,
) -> SupervisorDecision | None:
    """Step 9: synthesize system-wide feedback periodically (listing 01 L61).

    The listing's "IF enough time has passed" made observable as two
    conditions, both required. A work cycle must have completed since the
    last firing -- the iteration counter, not the decision counter, so a
    ranking wave cannot buy two firings (one before it, one after it
    returns with new matches). And there must be new critique material to
    synthesize: reviews written or tournament participations played since
    the last firing.

    That second condition is also what makes this step terminate. Meta-
    review is not a work task, so it never advances the iteration counter
    and the first condition alone would hold for every remaining loop
    point; a firing that consumed the material it was scheduled for cannot
    immediately re-fire on the same material.

    Placed below every required transition and above convergence: it is
    maintenance, so real work outranks it, but a converging run should
    still hand the terminal overview a current critique rather than the
    one it held two cycles ago.

    Disabled outright when ``meta_review_enabled`` is False (an ablation
    arm running with no meta-review cadence): returning None here suppresses
    both this ordered-check step and the companion form, since
    ``policy._due_companions`` calls this same function. The EVOLVE branch
    still enters the meta_review node, so this removes periodic feedback,
    not the node.
    """
    if not stats.meta_review_enabled:
        return None
    if stats.iterations_since_meta_review < 1:
        return None
    if stats.feedback_since_meta_review < 1:
        return None
    return SupervisorDecision(
        next_task=TaskType.META_REVIEW,
        reason=(
            f"{stats.feedback_since_meta_review} new review(s)/match(es) "
            f"over {stats.iterations_since_meta_review} cycle(s) since the "
            "last system-wide feedback; synthesize it"
        ),
    )


def _check_research_overview_cadence(
    stats: SchedulerStats, budget: Budget
) -> SupervisorDecision | None:
    """Step 10: synthesize an interim overview periodically (L65-69).

    The paper describes the research overview as generated periodically
    and names it as one of the system's two self-improvement channels;
    ours ran once, at termination, with no edge back into generation
    (FIX-6). A firing here returns to the loop point and leaves an
    ``interim_overview`` the next generate cycle reads as context.

    Gated by cost as well as by cadence, which is what separates it from
    meta-review's step directly above: that companion is one ordinary
    call, this is the largest prompt in the system and up to two
    escalation retries behind it, so only a tier declaring at least
    ``RESEARCH_OVERVIEW_MIN_LLM_CALLS`` buys it.

    Terminates for the same reason meta-review's does, by the same
    mechanism: the overview is not a work task and never advances the
    iteration counter itself, so the anchor
    (``orchestrator_bookkeeping._research_overview_anchor``) is reset as
    the decision is taken and the gap reads zero on the very next loop
    point.
    """
    ceiling = budget.max_llm_calls
    if ceiling is None or ceiling < RESEARCH_OVERVIEW_MIN_LLM_CALLS:
        return None
    if stats.iterations_since_research_overview < (
        RESEARCH_OVERVIEW_CADENCE_CYCLES
    ):
        return None
    return SupervisorDecision(
        next_task=TaskType.SYNTHESIZE,
        reason=(
            f"{stats.iterations_since_research_overview} work cycle(s) "
            "since the last research overview; synthesize an interim one "
            "for the next generation cycle"
        ),
    )

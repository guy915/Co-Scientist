"""What each run tier is willing to spend on research.

``co_scientist.research`` reads no tier and no config on purpose, so
somebody has to translate "this is an extended run" into ceilings. This
is that somebody, and it lives here rather than in the app so the
numbers stay next to the loop they bound and can be tested offline.

Only the two deep tiers research at all. Not a soft default: the loop
opens a thread per question and reads documents per thread, so switching
it on for every run multiplies an express run's whole cost by a factor
its ceiling was never sized for. The tiers that already buy depth
elsewhere are the ones that can afford it here.

The numbers below are what the arithmetic in ``budget.py`` turns into a
thread count: extended runs 4 + 2 = 6 threads, ultra 6 + 3 + 2 = 11.
Read them as a ceiling a caller can quote before spending anything, not
as a target.

A review's budget is a second, much smaller table. The literature review
researches once per run; a review researches once per hypothesis, so its
cost is a product and the ceiling has to bound both factors -- the work
per hypothesis *and* how many hypotheses are researched at all. A
per-hypothesis budget alone does not bound anything: that is the shape
that turned a proportionate per-run relevance pass into 299 LLM calls
when three agents started calling it per hypothesis, per cycle.
"""

from __future__ import annotations

from collections.abc import Sequence

from co_scientist.research import ResearchBudget

# Tier -> (depth, breadth, hits per question). Absent means no research.
_TIER_CEILINGS: dict[str, tuple[int, int, int]] = {
    "extended": (2, 4, 4),
    "ultra": (3, 6, 5),
}

# Threads in flight at once. Bounded well below the thread count because
# each thread is a fan of searches plus a read plus two model calls, and
# the sources throttle a burst long before this engine runs out of loop.
_CONCURRENCY = 3


def budget_for_tier(tier: str, sources: Sequence[str]) -> ResearchBudget | None:
    """Resolve one run tier's research ceilings.

    Args:
        tier: Normalized run tier (``express``, ``standard``,
            ``extended``, ``ultra``).
        sources: Search sources the run has enabled, in preference
            order, as the retrieval port names them.

    Returns:
        The budget for this tier, or None when the tier does not buy
        research -- which a caller reads as "skip it", not as an error.
        A tier that would research but has no source enabled also gets
        None, since a budget with no source is not constructible and an
        empty registry is a configuration state, not a failure.
    """
    ceilings = _TIER_CEILINGS.get(tier)
    if ceilings is None or not sources:
        return None
    depth, breadth, hits = ceilings
    return ResearchBudget(
        depth=depth,
        breadth=breadth,
        concurrency=_CONCURRENCY,
        hits_per_question=hits,
        sources=tuple(sources),
    )


def tier_researches(tier: str) -> bool:
    """Whether this tier buys any research at all.

    The one authority on the question, so a caller deciding whether to
    warn about missing tools does not grow a second copy of the tier
    list beside this one.

    Args:
        tier: Normalized run tier.

    Returns:
        True when the tier has ceilings here.
    """
    return tier in _TIER_CEILINGS


# Tier -> (depth, breadth, hits) for ONE reviewed hypothesis. Deliberately
# below the run-level table: this is asked per hypothesis, so a level here
# costs as much as the whole literature-review phase does over the run.
_REVIEW_CEILINGS: dict[str, tuple[int, int, int]] = {
    "extended": (2, 2, 3),
    "ultra": (2, 3, 4),
}

# How many of a run's hypotheses a tier researches during review, best
# ranked first. The other factor in the product, and the reason a run's
# total is quotable: at most this many times the budget's own thread
# ceiling -- 3 x 4 = 12 threads on extended, 5 x 5 = 25 on ultra. The
# breadth floor is why a level never halves to one: 2 + 2 and 3 + 2.
_REVIEW_HYPOTHESES: dict[str, int] = {
    "extended": 3,
    "ultra": 5,
}


def review_budget_for_tier(
    tier: str, sources: Sequence[str]
) -> ResearchBudget | None:
    """Resolve what one reviewed hypothesis may spend on research.

    Args:
        tier: Normalized run tier.
        sources: Search sources the run has enabled, in preference order.

    Returns:
        The per-hypothesis budget, or None when this tier does not
        research reviews or the run has no source to search.
    """
    ceilings = _REVIEW_CEILINGS.get(tier)
    if ceilings is None or not sources:
        return None
    depth, breadth, hits = ceilings
    return ResearchBudget(
        depth=depth,
        breadth=breadth,
        concurrency=_CONCURRENCY,
        hits_per_question=hits,
        sources=tuple(sources),
    )


def reviewed_hypothesis_limit(tier: str) -> int:
    """How many hypotheses this tier researches during review.

    Args:
        tier: Normalized run tier.

    Returns:
        The cap, or 0 when the tier does not research reviews at all --
        which a caller reads as "research nothing here".
    """
    return _REVIEW_HYPOTHESES.get(tier, 0)

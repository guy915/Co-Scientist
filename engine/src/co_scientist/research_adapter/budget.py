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

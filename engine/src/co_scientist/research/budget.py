"""How much research a request may buy, and how it narrows.

Depth and breadth are separate ceilings, and breadth decays as the
search descends: each level runs half as wide as the one above it, with
a floor. Total work is therefore fixed by arithmetic before the first
call is made, and the search spends its budget wide first and narrow
later -- broad coverage where nothing is known yet, focus where a thread
has already earned it.

The alternative, letting a model decide how many threads to open and how
long to keep going, is what most published deep-research systems do. It
is rejected here for one measured reason: agentic tool-calling is
already the largest single line in this host's token budget, and an
unbounded loop on top of it has no ceiling anyone can quote in advance.

Nothing here reads a run tier, an env var or a config file. A caller
resolves its own ceilings and hands them over; that is what keeps this
package assignable to any agent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# Below this, halving stops. A one-question level is not research, it is
# a single lookup, and the descent may as well end instead.
DEFAULT_BREADTH_FLOOR = 2


@dataclass(frozen=True)
class ResearchBudget:
    """Ceilings for one research request.

    Attributes:
        depth: Levels of follow-up remaining, counting this one.
        breadth: Questions this level may open.
        concurrency: Threads that may run at once.
        hits_per_question: Documents read per question, across all
            sources.
        sources: Source names to search, in preference order. Opaque
            strings; the retrieval port decides what they mean.
        breadth_floor: Breadth never decays below this.
        reserved_slots: ``(source, places)`` pairs guaranteeing a source
            that many of each question's documents before the rest are
            filled in source order. Empty by default, which is the
            preference-order behaviour on its own.

    Raises:
        ValueError: If any ceiling is below one, no source is named, or a
            reservation is unfillable (see :meth:`_check_reservations`).
    """

    depth: int = 2
    breadth: int = 4
    concurrency: int = 2
    hits_per_question: int = 4
    sources: tuple[str, ...] = ()
    breadth_floor: int = DEFAULT_BREADTH_FLOOR
    reserved_slots: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        """Reject a budget that cannot describe any work."""
        for name in ("depth", "breadth", "concurrency", "hits_per_question"):
            value = getattr(self, name)
            if value < 1:
                raise ValueError(f"{name} must be at least 1, got {value}")
        if self.breadth_floor < 1:
            raise ValueError("breadth_floor must be at least 1")
        if not self.sources:
            raise ValueError("at least one source is required")
        self._check_reservations()

    def _check_reservations(self) -> None:
        """Reject reservations that cannot be honoured.

        A reservation naming a source this budget will not search is a
        typo that would otherwise do nothing at all, and reserving every
        place leaves preference order deciding nothing -- both are
        configuration mistakes worth failing on rather than absorbing.

        Raises:
            ValueError: A reservation names an unsearched source, asks
                for fewer than one place, or the reservations together
                claim every document the question may read.
        """
        total = 0
        for source, places in self.reserved_slots:
            if source not in self.sources:
                raise ValueError(f"reserved slots for unsearched {source!r}")
            if places < 1:
                raise ValueError(f"reserved slots for {source!r} must be >= 1")
            total += places
        if total >= self.hits_per_question and total:
            raise ValueError(
                f"reservations claim all {self.hits_per_question} hits"
            )

    def descend(self) -> ResearchBudget | None:
        """Return the budget for the next level down.

        Returns:
            A budget with one less level and half the breadth, or None
            when this was the last level.
        """
        if self.depth <= 1:
            return None
        return replace(
            self,
            depth=self.depth - 1,
            breadth=max(self.breadth_floor, self.breadth // 2),
        )

    def max_threads(self) -> int:
        """Return the most threads this budget can open, all levels.

        The number a caller can quote before spending anything. Useful
        for a cost estimate and for asserting in a test that the loop
        cannot exceed what it was given.
        """
        total = 0
        level: ResearchBudget | None = self
        while level is not None:
            total += level.breadth
            level = level.descend()
        return total

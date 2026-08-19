"""A MAP-Elites archive: what stops a search collapsing into one basin.

Selecting parents by score alone is the obvious strategy and a
consistently bad one. The best few programs in a generation are usually
near-copies of each other, so breeding from them produces more of the
same, and the search settles into the first decent basin it finds and
polishes it for the rest of its budget. Nothing looks wrong while this
happens -- the score improves, slowly, forever.

The fix is to stop keeping *the best* and start keeping **the best of
each kind**. Every variant is placed in a cell by its behaviour -- what
move produced it, how long the program is, how deeply nested, what it
depends on -- and parents are drawn from across those cells, so a
compact-but-mediocre program and a sprawling-but-strong one are both
still in play.

Three decisions here are worth reading, because the obvious version of
each is wrong.

**A cell keeps a front, not an elite.** Reducing a cell to its single
best variant re-introduces, inside the cell, exactly the collapse the
archive exists to prevent: two genuinely different trades that happen to
share a niche compete for one slot, and the one that loses on the
primary objective is discarded even though nothing dominates it. So each
cell holds its own non-dominated set (this is MOME), capped, with the
most crowded member dropped when it overflows -- crowding rather than
score, because dropping by score would again delete the trade.

**Selection is half exploit, half explore.** Textbook MAP-Elites samples
occupied cells uniformly, which is right when the budget is tens of
thousands of evaluations. A run here evaluates tens. Spending all of it
uniformly would leave every cell shallow and none refined, so half the
children come from the strongest members and the global front, and half
from a uniform draw across cells. The uniform half prevents collapse;
the greedy half makes progress inside a small budget.

**Cells come from `grid`, and are derived rather than stored.** Under an
adaptive or CVT grid a variant's cell depends on every other variant, so
a cell id computed at evaluation time is wrong by the next generation.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from co_scientist.agents.code_evolve.grid import (
    DEFAULT_GRID,
    Grid,
    assign_cells,
    coverage,
)
from co_scientist.code_eval.pareto import ObjectiveValues, pareto_front

# How many variants one cell may hold. More than one so a cell can keep
# a real trade-off; small so the archive still compresses -- an
# unbounded cell is a list of every variant with extra steps.
DEFAULT_CELL_CAPACITY = 3

# Fraction of a generation's children bred from the strongest members
# rather than from a uniform draw across cells. See the module
# docstring: pure uniform selection is correct at textbook scale and
# wrong at this one.
EXPLOIT_SHARE = 0.5


@dataclass(frozen=True)
class ArchiveEntry:
    """One evaluated variant, as the archive sees it.

    Attributes:
        variant_id: Identifies it to the caller.
        fitness: Primary-objective score; None when it never scored.
        objective_values: Every objective's score, for dominance.
        behaviour: Raw feature values -- see `behaviour.describe`. The
            grid derives a cell from these; nothing here is pre-binned,
            because the binning depends on the whole population.
        ordinal: Its attempt number, used only to break ties toward the
            earlier attempt -- the same rule the rest of the store uses.
    """

    variant_id: str
    fitness: float | None = None
    objective_values: tuple[float | None, ...] = ()
    behaviour: dict[str, Any] = field(default_factory=dict)
    ordinal: int = 0


def _crowding_rank(entries: Sequence[ArchiveEntry]) -> list[float]:
    """Scores how isolated each entry is among its peers.

    Standard NSGA-II crowding distance: for every objective, sort and
    measure the gap between each entry's neighbours; the extremes are
    infinitely isolated and are never dropped. This is what decides
    which member a full cell gives up -- dropping by score instead would
    delete precisely the trade the cell is there to keep.
    """
    count = len(entries)
    distances = [0.0] * count
    width = max((len(e.objective_values) for e in entries), default=0)
    for axis in range(width):
        values = [_axis_value(entry, axis) for entry in entries]
        order = sorted(range(count), key=lambda i: values[i])
        distances[order[0]] = float("inf")
        distances[order[-1]] = float("inf")
        spread = values[order[-1]] - values[order[0]]
        if spread <= 0:
            continue
        for position in range(1, count - 1):
            index = order[position]
            gap = values[order[position + 1]] - values[order[position - 1]]
            distances[index] += gap / spread
    return distances


def _axis_value(entry: ArchiveEntry, axis: int) -> float:
    """One objective's score, with an unreported axis read as the worst.

    Only used for crowding, never for dominance. Crowding just needs a
    total order to measure gaps along; dominance is where treating a
    missing value as the floor would wrongly delete a variant.
    """
    if axis >= len(entry.objective_values):
        return float("-inf")
    value = entry.objective_values[axis]
    return float("-inf") if value is None else value


def _prune(
    entries: list[ArchiveEntry], capacity: int
) -> tuple[ArchiveEntry, ...]:
    """Trims a cell to capacity, dropping its most crowded members."""
    if len(entries) <= capacity:
        return tuple(entries)
    distances = _crowding_rank(entries)
    keep = sorted(
        range(len(entries)),
        key=lambda i: (-distances[i], entries[i].ordinal),
    )[:capacity]
    return tuple(entries[index] for index in sorted(keep))


def _cell_members(
    entries: list[ArchiveEntry], capacity: int
) -> tuple[ArchiveEntry, ...]:
    """Reduces one cell's variants to its capped non-dominated set.

    Unscored variants are kept only when a cell has nothing else: a
    niche whose only member crashed is still worth a repair attempt,
    but one that has working programs should not spend selection slots
    on a variant that never ran.
    """
    scored = [entry for entry in entries if entry.fitness is not None]
    if not scored:
        return _prune(sorted(entries, key=lambda e: e.ordinal)[:1], capacity)
    values: list[ObjectiveValues] = [e.objective_values for e in scored]
    front = [scored[index] for index in pareto_front(values)]
    return _prune(front or scored, capacity)


def build_archive(
    entries: Sequence[ArchiveEntry],
    *,
    grid: Grid = DEFAULT_GRID,
    capacity: int = DEFAULT_CELL_CAPACITY,
) -> dict[tuple[Any, ...], tuple[ArchiveEntry, ...]]:
    """Reduces every evaluated variant to the front of each cell.

    Args:
        entries: Every evaluated variant in the run.
        grid: The run's descriptors, strategy and cell count.
        capacity: How many variants one cell may hold.

    Returns:
        Each occupied cell's non-dominated members, keyed by cell.
    """
    cells = assign_cells([entry.behaviour for entry in entries], grid)
    grouped: dict[tuple[Any, ...], list[ArchiveEntry]] = {}
    for entry, cell in zip(entries, cells, strict=False):
        grouped.setdefault(cell, []).append(entry)
    return {
        cell: _cell_members(members, capacity)
        for cell, members in grouped.items()
    }


def archive_coverage(
    entries: Sequence[ArchiveEntry], *, grid: Grid = DEFAULT_GRID
) -> tuple[int, float]:
    """How many cells a run has reached, and how evenly it filled them.

    The count alone can be high while a run is still collapsed -- forty
    variants in one cell and one in each of five others reaches six
    cells and has explored almost nothing -- so the evenness comes with
    it. See `grid.coverage`.
    """
    cells = assign_cells([entry.behaviour for entry in entries], grid)
    return len(set(cells)), coverage(cells)


def _exploit_order(entries: Sequence[ArchiveEntry]) -> list[ArchiveEntry]:
    """Members ranked strongest-first, unscored ones last."""
    return sorted(
        entries,
        key=lambda e: (e.fitness is None, -(e.fitness or 0.0), e.ordinal),
    )


def _front_members(
    entries: Sequence[ArchiveEntry],
) -> list[ArchiveEntry]:
    """The members no other member dominates across every objective.

    With one objective this is just the joint best. With several it is
    the set of real trades, and including it in the greedy half is what
    keeps a variant that wins only on the second objective from being
    bred out by variants that win on the first.
    """
    values: list[ObjectiveValues] = [e.objective_values for e in entries]
    return [entries[index] for index in pareto_front(values)]


def select_parents(
    entries: Sequence[ArchiveEntry],
    count: int,
    *,
    grid: Grid = DEFAULT_GRID,
    rng: random.Random | None = None,
) -> list[ArchiveEntry]:
    """Chooses the parents for the next generation.

    Args:
        entries: Every evaluated variant in the run.
        count: How many children the generation will have.
        grid: The run's niching configuration.
        rng: Source of randomness, injectable so a test can pin the draw.

    Returns:
        One parent per child, in order. Empty only when there is nothing
        to breed from at all.

    The uniform half draws a *cell* first and a member within it second,
    rather than drawing from all members at once. Drawing from members
    would hand a cell holding three trades three times the attention of
    a cell holding one, which is population size deciding selection --
    the bias the archive exists to remove.
    """
    if count < 1:
        return []
    cells = build_archive(entries, grid=grid)
    members = [member for group in cells.values() for member in group]
    if not members:
        return []

    source = rng or random.Random()
    exploit_count = min(len(members), max(1, round(count * EXPLOIT_SHARE)))
    chosen = _exploit_order(_front_members(members) or members)[:exploit_count]
    keys = list(cells)
    chosen.extend(
        source.choice(cells[source.choice(keys)])
        for _ in range(max(0, count - len(chosen)))
    )
    return chosen[:count]

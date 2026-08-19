"""Turning behaviour vectors into archive cells.

A fixed grid -- bin edges written into the run config before anything
has run -- has one failure mode that no amount of care avoids: the edges
are guesses about a distribution nobody has seen yet. Guess too coarse
and every variant lands in one cell, so the archive degenerates to
keeping a single elite and the diversity mechanism silently does
nothing. Guess too fine and every variant gets its own cell, so the
archive keeps everything, which is the same failure viewed from the
other side -- selection stops preferring anything.

So the grid is derived from the data instead, and three strategies are
offered because they fail differently:

``fixed``
    Declared edges. Right when the author genuinely knows the scale --
    an accuracy in [0, 1], a latency budget with a contractual
    threshold -- and wrong whenever they are guessing.
``adaptive``
    Per-axis quantiles of what has actually been observed. Cells stay
    balanced as the run moves, at the cost of a cell's meaning drifting.
``cvt``
    k-means over the whole behaviour vector at once, into a fixed number
    of cells. The default, because it is the only one whose archive size
    is bounded by construction: `cells` cells, whatever the dimensions
    of behaviour space or the scale of any axis.

**Cells are computed from raw behaviour, never stored.** Under an
adaptive grid the cell a variant belongs to depends on every other
variant, so a cell id written at evaluation time is wrong by the next
generation. Storing the behaviour and deriving the cell keeps one source
of truth; the alternative is two that disagree slowly.

**An axis must describe a variant's kind, not its progress -- and the
adaptive strategies are the ones this bites.** A fixed grid whose edges
are too coarse quietly collapses a useless axis into one bin, which is a
crude accident that happens to be protective. `adaptive` and `cvt` have
no such accident: they faithfully subdivide whatever axis they are
given, so an axis that mostly tracks how refined a variant is turns the
archive into "keep every refinement level of every approach", and the
uniform half of selection spends its budget re-drawing the same approach
at different maturities. Measured on the decoy landscape (200 seeds,
identical budget), adding a length axis that only grows with refinement
took CVT from a mean best of 7.84 to 5.71 and halved how often the run
escaped the decoy. This is why `source_lines` is *not* a default axis
despite being the cheapest one available, and why `max_depth` and
`imports` are -- nesting and dependencies say what kind of program this
is, and a variant does not become deeper or import more simply by being
polished.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from co_scientist.agents.code_evolve.behaviour import is_categorical

# Default number of CVT cells. Small on purpose: a discovery run
# evaluates tens of variants, and an archive with more cells than
# variants has stopped compressing anything.
DEFAULT_CELLS = 12

# k-means bounds. Both small because the input is at most a few hundred
# points in under ten dimensions, and because selection has to be
# reproducible rather than optimal.
_KMEANS_ITERATIONS = 25
_KMEANS_SEED = 20260819


class GridStrategy(Enum):
    """How behaviour vectors are turned into cells."""

    FIXED = "fixed"
    ADAPTIVE = "adaptive"
    CVT = "cvt"


@dataclass(frozen=True)
class Descriptor:
    """One axis of behaviour the archive niches along.

    Attributes:
        feature: What is measured -- ``operator``, ``imports``,
            ``source_lines``, ``max_depth``, ``branch_count``,
            ``call_diversity``, ``source_bytes``, or ``metric:<key>``.
        bins: Ascending edges, used by the ``fixed`` strategy. Under
            ``adaptive`` their *count* sets the resolution; under
            ``cvt`` they are ignored entirely.
    """

    feature: str
    bins: tuple[float, ...] = ()


@dataclass(frozen=True)
class Grid:
    """The run's niching configuration.

    Attributes:
        descriptors: The axes, in order.
        strategy: How cells are derived from them.
        cells: Target cell count for ``cvt``.
    """

    descriptors: tuple[Descriptor, ...]
    strategy: GridStrategy = GridStrategy.CVT
    cells: int = DEFAULT_CELLS


# What a run gets when it declares nothing. Every axis here describes a
# kind of program -- the move that produced it, how it is structured,
# what it depends on -- and none of them is a proxy for how refined it
# is. Program length is deliberately absent: see the module docstring
# for the measurement that took it out.
DEFAULT_DESCRIPTORS: tuple[Descriptor, ...] = (
    Descriptor(feature="operator"),
    Descriptor(feature="max_depth"),
    Descriptor(feature="imports"),
)

DEFAULT_GRID = Grid(descriptors=DEFAULT_DESCRIPTORS)

Behaviour = Mapping[str, Any]


def _numeric(value: Any) -> float | None:
    """Reads a numeric feature value, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fixed_coord(value: Any, descriptor: Descriptor) -> Any:
    """Places a value on one axis using declared edges."""
    if is_categorical(descriptor.feature) or not descriptor.bins:
        return value if value is not None else "unknown"
    number = _numeric(value)
    if number is None:
        return "unknown"
    return sum(1 for edge in descriptor.bins if number >= edge)


def _quantile_edges(values: Sequence[float], bins: int) -> tuple[float, ...]:
    """Edges splitting observed values into roughly equal-sized bins.

    Duplicates are dropped, so an axis where most variants share a value
    collapses to fewer bins rather than producing empty ones -- an empty
    cell is not a niche nothing has reached, it is a niche that cannot
    be reached, and counting it would overstate the run's coverage.
    """
    ordered = sorted(values)
    if not ordered or bins < 2:
        return ()
    edges = []
    for index in range(1, bins):
        position = min(len(ordered) - 1, int(len(ordered) * index / bins))
        edges.append(ordered[position])
    return tuple(sorted(set(edges)))


def _adaptive_edges(
    behaviours: Sequence[Behaviour], descriptor: Descriptor
) -> tuple[float, ...]:
    """Derives one axis's edges from what the run has actually produced."""
    observed = [
        number
        for behaviour in behaviours
        if (number := _numeric(behaviour.get(descriptor.feature))) is not None
    ]
    return _quantile_edges(observed, max(2, len(descriptor.bins) + 1))


def _vectorize(
    behaviours: Sequence[Behaviour], descriptors: Sequence[Descriptor]
) -> list[list[float]]:
    """Encodes behaviours as comparable numeric vectors for clustering.

    Numeric axes are min-max normalized so an axis measured in bytes
    cannot dominate one measured in nesting levels -- the same
    cross-scale trap that makes a weighted-sum objective meaningless.
    Categorical axes become a one-hot block, so two variants differ by a
    constant on that axis whatever the categories are named.
    """
    columns: list[list[float]] = []
    for descriptor in descriptors:
        raw = [b.get(descriptor.feature) for b in behaviours]
        if is_categorical(descriptor.feature):
            columns.extend(_one_hot(raw))
        else:
            columns.append(_normalized([_numeric(value) for value in raw]))
    return [list(row) for row in zip(*columns, strict=False)] or [
        [] for _ in behaviours
    ]


def _normalized(values: Sequence[float | None]) -> list[float]:
    """Scales one numeric axis into [0, 1], centring a constant axis."""
    present = [value for value in values if value is not None]
    if not present:
        return [0.0 for _ in values]
    low, high = min(present), max(present)
    if high == low:
        return [0.5 for _ in values]
    return [
        0.5 if value is None else (value - low) / (high - low)
        for value in values
    ]


def _one_hot(values: Sequence[Any]) -> list[list[float]]:
    """Encodes one categorical axis as equidistant columns."""
    categories = sorted({str(value) for value in values})
    return [
        [1.0 if str(value) == category else 0.0 for value in values]
        for category in categories
    ]


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    """Squared euclidean distance, which is all k-means needs."""
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=False))


def _initial_centroids(
    points: Sequence[Sequence[float]], k: int, rng: random.Random
) -> list[list[float]]:
    """k-means++ seeding: spread the first centroids out deliberately."""
    centroids = [list(rng.choice(points))]
    while len(centroids) < k:
        weights = [
            min(_distance(point, centre) for centre in centroids)
            for point in points
        ]
        total = sum(weights)
        if total <= 0:
            centroids.append(list(rng.choice(points)))
            continue
        centroids.append(list(rng.choices(points, weights=weights)[0]))
    return centroids


def _assign(
    points: Sequence[Sequence[float]], centroids: Sequence[Sequence[float]]
) -> list[int]:
    """Labels each point with its nearest centroid."""
    return [
        min(range(len(centroids)), key=lambda i: _distance(point, centroids[i]))
        for point in points
    ]


def _recentre(
    points: Sequence[Sequence[float]], labels: Sequence[int], k: int
) -> list[list[float]]:
    """Moves each centroid to the mean of the points assigned to it."""
    centroids = []
    for index in range(k):
        members = [
            p
            for p, label in zip(points, labels, strict=False)
            if label == index
        ]
        if not members:
            centroids.append(list(points[index % len(points)]))
            continue
        centroids.append(
            [
                sum(values) / len(members)
                for values in zip(*members, strict=False)
            ]
        )
    return centroids


def _kmeans_labels(points: Sequence[Sequence[float]], k: int) -> list[int]:
    """Clusters behaviour vectors into at most ``k`` cells.

    Seeded from a constant so the same variants always produce the same
    cells: parent selection is already stochastic, and a grid that also
    moved between two reads of the same run would make a diversity
    regression impossible to reproduce.
    """
    if not points or not points[0]:
        return [0 for _ in points]
    k = max(1, min(k, len(points)))
    rng = random.Random(_KMEANS_SEED)
    centroids = _initial_centroids(points, k, rng)
    labels = _assign(points, centroids)
    for _ in range(_KMEANS_ITERATIONS):
        centroids = _recentre(points, labels, k)
        updated = _assign(points, centroids)
        if updated == labels:
            break
        labels = updated
    return labels


def _static_cells(
    behaviours: Sequence[Behaviour], grid: Grid
) -> list[tuple[Any, ...]]:
    """Cells for the fixed and adaptive strategies."""
    edges = {
        descriptor.feature: (
            descriptor.bins
            if grid.strategy is GridStrategy.FIXED
            else _adaptive_edges(behaviours, descriptor)
        )
        for descriptor in grid.descriptors
    }
    return [
        tuple(
            _fixed_coord(
                behaviour.get(d.feature),
                Descriptor(feature=d.feature, bins=edges[d.feature]),
            )
            for d in grid.descriptors
        )
        for behaviour in behaviours
    ]


def assign_cells(
    behaviours: Sequence[Behaviour], grid: Grid
) -> list[tuple[Any, ...]]:
    """Assigns every variant to an archive cell.

    Args:
        behaviours: One behaviour mapping per variant.
        grid: The run's descriptors, strategy and target cell count.

    Returns:
        One cell key per variant, in the same order. Keys are opaque:
        compare them, do not read them.
    """
    if not behaviours:
        return []
    if grid.strategy is not GridStrategy.CVT:
        return _static_cells(behaviours, grid)
    labels = _kmeans_labels(
        _vectorize(behaviours, grid.descriptors), grid.cells
    )
    return [(label,) for label in labels]


def coverage(cells: Sequence[tuple[Any, ...]]) -> float:
    """How evenly a run's variants are spread across the cells it reached.

    Reported alongside the raw cell count because the count alone can be
    high while the run is still collapsed: forty variants in one cell and
    one variant in each of five others reaches six cells and has
    explored almost nothing. This is normalized entropy, so 1.0 is a
    perfectly even spread and 0.0 is everything in one place.
    """
    if not cells:
        return 0.0
    counts: dict[tuple[Any, ...], int] = {}
    for cell in cells:
        counts[cell] = counts.get(cell, 0) + 1
    if len(counts) < 2:
        return 0.0
    total = len(cells)
    entropy = -sum(
        (count / total) * math.log(count / total) for count in counts.values()
    )
    return entropy / math.log(len(counts))

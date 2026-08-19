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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from co_scientist.agents.code_evolve import tessellation
from co_scientist.agents.code_evolve.behaviour import (
    is_categorical,
    is_vector,
)

# Default number of CVT cells. Small on purpose: a discovery run
# evaluates tens of variants, and an archive with more cells than
# variants has stopped compressing anything.
DEFAULT_CELLS = 12

# k-means bounds. Both small because the input is at most a few hundred
# points in under ten dimensions, and because selection has to be
# reproducible rather than optimal.
_KMEANS_ITERATIONS = 25
_KMEANS_SEED = 20260819


class UnbinnableFeatureError(ValueError):
    """A vector-valued feature under a strategy that can only bin scalars.

    Raised rather than silently dropping the axis. A structural
    fingerprint is eight numbers describing what algorithm a program
    uses; `fixed` and `adaptive` place values on one dimension at a time
    and have nothing to do with it. Ignoring it would leave a run niching
    along fewer axes than its author declared, with nothing to show that
    it happened -- the same silent under-enforcement the sandbox refuses.
    """


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
        projection: A frozen coordinate system and its centroids, once
            the run has one. While this is empty, CVT re-clusters on
            every read, so a cell is a snapshot rather than an identity:
            adding a variant can move an older one to a different cell,
            and "cells occupied" is not monotonic. Freezing ends that --
            see `freeze`. Note it pins the *projection*, not just the
            centroids: the scaling and one-hot layout are derived from
            the population too, so pinning centroids alone would let the
            coordinate system drift underneath them.
    """

    descriptors: tuple[Descriptor, ...]
    strategy: GridStrategy = GridStrategy.CVT
    cells: int = DEFAULT_CELLS
    projection: tessellation.Projection = field(
        default_factory=tessellation.Projection
    )

    def __post_init__(self) -> None:
        """Refuses a combination that can never bin a single variant.

        The strategy and the axes are both known here, so an axis this
        strategy cannot place is decidable now. Left to binning time it
        raises once per variant instead -- a whole run failing
        identically at every step, with the one-line cause visible only
        in a task traceback.
        """
        if self.strategy is GridStrategy.CVT:
            return
        for descriptor in self.descriptors:
            if is_vector(descriptor.feature):
                raise UnbinnableFeatureError(
                    f"feature {descriptor.feature!r} is a vector and can "
                    f"only be used with the {GridStrategy.CVT.value!r} "
                    f"strategy, not {self.strategy.value!r}"
                )


# What a run gets when it declares nothing. Every axis here describes a
# kind of program -- the move that produced it, how it is structured,
# what it depends on -- and none of them is a proxy for how refined it
# is. Program length is deliberately absent: see the module docstring
# for the measurement that took it out.
DEFAULT_DESCRIPTORS: tuple[Descriptor, ...] = (
    Descriptor(feature="operator"),
    Descriptor(feature="max_depth"),
    Descriptor(feature="imports"),
    Descriptor(feature="recursion"),
    Descriptor(feature="ast_shape"),
)

DEFAULT_GRID = Grid(descriptors=DEFAULT_DESCRIPTORS)


def default_descriptors_for(strategy: GridStrategy) -> tuple[Descriptor, ...]:
    """The default axes a strategy can actually use.

    ``ast_shape`` is a vector and only the clustering strategy can read
    one, so the scalar subset is what a `fixed` or `adaptive` run gets by
    default. This is a narrowing of defaults the author never asked for,
    not a silent drop of something they declared -- a vector feature
    named explicitly under those strategies still raises.
    """
    if strategy is GridStrategy.CVT:
        return DEFAULT_DESCRIPTORS
    return tuple(
        descriptor
        for descriptor in DEFAULT_DESCRIPTORS
        if not is_vector(descriptor.feature)
    )


Behaviour = Mapping[str, Any]


def _numeric(value: Any) -> float | None:
    """Reads a numeric feature value, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fixed_coord(value: Any, descriptor: Descriptor) -> Any:
    """Places a value on one axis using declared edges."""
    if is_vector(descriptor.feature):
        raise UnbinnableFeatureError(
            f"feature {descriptor.feature!r} is a vector and can only be "
            f"used with the {GridStrategy.CVT.value!r} strategy"
        )
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


def _feature_kinds(
    descriptors: Sequence[Descriptor],
) -> list[tuple[str, str]]:
    """Pairs each descriptor with the column kind it projects to."""
    kinds = []
    for descriptor in descriptors:
        if is_categorical(descriptor.feature):
            kinds.append((descriptor.feature, tessellation.CATEGORY))
        elif is_vector(descriptor.feature):
            kinds.append((descriptor.feature, tessellation.COMPONENT))
        else:
            kinds.append((descriptor.feature, tessellation.NUMERIC))
    return kinds


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

    With a frozen tessellation each variant goes to its nearest
    centroid and nothing else moves. Without one, CVT re-clusters the
    whole population, which is correct but unstable -- so a run freezes
    as soon as it has enough variants to tessellate meaningfully.
    """
    if not behaviours:
        return []
    if grid.strategy is not GridStrategy.CVT:
        return _static_cells(behaviours, grid)
    if grid.projection:
        points = tessellation.project(behaviours, grid.projection.columns)
        labels = tessellation.nearest(points, grid.projection.centroids)
    else:
        columns = tessellation.derive_columns(
            behaviours, _feature_kinds(grid.descriptors)
        )
        labels, _ = tessellation.cluster(
            tessellation.project(behaviours, columns), grid.cells
        )
    return [(label,) for label in labels]


def freeze(behaviours: Sequence[Behaviour], grid: Grid) -> Grid:
    """Fixes the tessellation, so a cell becomes a durable identity.

    Until a CVT grid is frozen, every read re-clusters: a variant can
    change cells because a later variant arrived, so cell ids cannot be
    compared across time and the occupied-cell count can go *down*.
    Freezing takes the centroids the population implies right now and
    keeps them, after which assignment is nearest-centroid and nothing
    already placed ever moves.

    Args:
        behaviours: The population to tessellate from.
        grid: The run's current configuration.

    Returns:
        The grid with centroids fixed, or unchanged when it is already
        frozen, is not CVT, or has fewer variants than cells. That last
        condition is what stops a run freezing a one-point tessellation
        on its first generation and living with it forever.
    """
    if (
        grid.strategy is not GridStrategy.CVT
        or grid.projection
        or len(behaviours) < grid.cells
    ):
        return grid
    columns = tessellation.derive_columns(
        behaviours, _feature_kinds(grid.descriptors)
    )
    _, centroids = tessellation.cluster(
        tessellation.project(behaviours, columns), grid.cells
    )
    return replace(
        grid,
        projection=tessellation.Projection(
            columns=columns,
            centroids=tuple(tuple(centre) for centre in centroids),
        ),
    )


# How far a frozen tessellation may grow, as a multiple of its declared
# cell count. Growth exists so a run that changes character late is not
# niched by the run it used to be; a ceiling exists because unbounded
# growth is re-clustering under another name, and an archive with a cell
# per variant has stopped compressing anything.
EXTENSION_CEILING_FACTOR = 2


def extend(behaviours: Sequence[Behaviour], grid: Grid) -> Grid:
    """Grows a frozen tessellation to cover behaviour it does not.

    The complement of ``freeze``. Freezing keeps a cell meaning the same
    thing across generations, at the cost that behaviour appearing
    afterwards lands in whichever edge cell is nearest -- filed beside
    variants it has nothing in common with. This adds cells for
    behaviour outside the tessellation's own resolution and moves none
    of the existing centroids, so what was already placed stays placed.

    Args:
        behaviours: Every variant measured so far.
        grid: The run's configuration, already frozen.

    Returns:
        The grid with any new centroids appended, or unchanged when it
        is not frozen, is not CVT, or has nothing far enough away.
    """
    if grid.strategy is not GridStrategy.CVT or not grid.projection:
        return grid
    grown = tessellation.extend(
        grid.projection,
        behaviours,
        grid.cells * EXTENSION_CEILING_FACTOR,
    )
    if grown is grid.projection:
        return grid
    return replace(grid, projection=grown)


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

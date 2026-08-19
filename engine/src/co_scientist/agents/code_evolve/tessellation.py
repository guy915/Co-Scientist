"""Projecting behaviour into a fixed coordinate system, and clustering it.

Splitting this out of `grid` is not organisational. It exists because
freezing a tessellation means freezing *two* things, and freezing only
the obvious one produces a bug that looks like it works.

Centroids live in a coordinate system built from the population: each
numeric axis is scaled by the observed range, each categorical axis is
one-hot encoded over the observed categories. Both of those move as
variants arrive -- a new longest program rescales the length axis, a new
operator adds a column. So pinning the centroids while letting the
projection drift re-labels old variants anyway, silently, and the run
still cannot compare a cell id across two generations. The frozen
artifact is therefore the whole projection: the column layout, the
scaling of every column, and the centroids expressed in it.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# k-means bounds. Both small because the input is at most a few hundred
# points in under twenty dimensions, and because selection has to be
# reproducible rather than optimal.
_KMEANS_ITERATIONS = 25
_KMEANS_SEED = 20260819

# Column kinds.
NUMERIC = "numeric"
CATEGORY = "category"
COMPONENT = "component"

Behaviour = Mapping[str, Any]


@dataclass(frozen=True)
class Column:
    """One coordinate of the projected behaviour space.

    Attributes:
        feature: The behaviour feature this column reads.
        kind: ``numeric`` (scaled by low/high), ``category`` (one-hot on
            ``category``), or ``component`` (one entry of a vector
            feature, at ``index``).
        low: Observed minimum, for numeric scaling.
        high: Observed maximum, for numeric scaling.
        category: The category this column tests for.
        index: Which component of a vector feature this column holds.
    """

    feature: str
    kind: str
    low: float = 0.0
    high: float = 1.0
    category: str = ""
    index: int = 0


@dataclass(frozen=True)
class Projection:
    """A frozen coordinate system plus the centroids expressed in it.

    Attributes:
        columns: The coordinate layout, in order.
        centroids: Cell centres, each with one value per column.
    """

    columns: tuple[Column, ...] = ()
    centroids: tuple[tuple[float, ...], ...] = field(default=())

    def __bool__(self) -> bool:
        """A projection is usable only once it has centroids."""
        return bool(self.centroids)


def _numeric(value: Any) -> float | None:
    """Reads a numeric value, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _numeric_column(behaviours: Sequence[Behaviour], feature: str) -> Column:
    """Derives a numeric column's scaling from the observed range."""
    seen = [
        number
        for behaviour in behaviours
        if (number := _numeric(behaviour.get(feature))) is not None
    ]
    low, high = (min(seen), max(seen)) if seen else (0.0, 1.0)
    return Column(feature=feature, kind=NUMERIC, low=low, high=high)


def _category_columns(
    behaviours: Sequence[Behaviour], feature: str
) -> list[Column]:
    """One column per observed category, in a stable order."""
    seen = sorted({str(b.get(feature)) for b in behaviours})
    return [
        Column(feature=feature, kind=CATEGORY, category=category)
        for category in seen
    ]


def _component_columns(
    behaviours: Sequence[Behaviour], feature: str
) -> list[Column]:
    """One column per entry of a vector feature."""
    width = max(
        (
            len(value)
            for b in behaviours
            if isinstance(value := b.get(feature), (list, tuple))
        ),
        default=0,
    )
    return [
        Column(feature=feature, kind=COMPONENT, index=index)
        for index in range(width)
    ]


def _scaled(raw: Any, column: Column) -> float:
    """Scales a numeric value into [0, 1] using the column's frozen range.

    An unreported quantity sits mid-range rather than at zero: it is not
    a small value, and placing it at the floor would make a variant that
    measured nothing look like the most extreme one on that axis.
    """
    number = _numeric(raw)
    if number is None or column.high == column.low:
        return 0.5
    return (number - column.low) / (column.high - column.low)


def _component(raw: Any, column: Column) -> float:
    """Reads one entry of a vector feature, or zero when it is absent."""
    if isinstance(raw, (list, tuple)) and column.index < len(raw):
        return float(raw[column.index])
    return 0.0


_READERS = {
    CATEGORY: lambda raw, col: 1.0 if str(raw) == col.category else 0.0,
    COMPONENT: _component,
    NUMERIC: _scaled,
}


def _cell_value(behaviour: Behaviour, column: Column) -> float:
    """Reads one coordinate of one variant."""
    reader = _READERS.get(column.kind, _scaled)
    return float(reader(behaviour.get(column.feature), column))


def project(
    behaviours: Sequence[Behaviour], columns: Sequence[Column]
) -> list[list[float]]:
    """Places every variant in the given coordinate system."""
    return [
        [_cell_value(behaviour, column) for column in columns]
        for behaviour in behaviours
    ]


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    """Squared euclidean distance, which is all k-means needs."""
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=False))


def nearest(
    points: Sequence[Sequence[float]], centroids: Sequence[Sequence[float]]
) -> list[int]:
    """Labels each point with its nearest centroid."""
    return [
        min(
            range(len(centroids)),
            key=lambda i: _distance(point, centroids[i]),
        )
        for point in points
    ]


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
        if sum(weights) <= 0:
            centroids.append(list(rng.choice(points)))
            continue
        centroids.append(list(rng.choices(points, weights=weights)[0]))
    return centroids


def _recentre(
    points: Sequence[Sequence[float]], labels: Sequence[int], k: int
) -> list[list[float]]:
    """Moves each centroid to the mean of the points assigned to it."""
    centroids = []
    for index in range(k):
        members = [
            point
            for point, label in zip(points, labels, strict=False)
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


def cluster(
    points: Sequence[Sequence[float]], k: int
) -> tuple[list[int], list[list[float]]]:
    """Clusters points into at most ``k`` cells.

    Seeded from a constant so the same population always produces the
    same cells: parent selection is already stochastic, and a grid that
    also moved between two reads of one run would make a diversity
    regression impossible to reproduce.

    Returns:
        The label per point, and the centroids they were assigned to.
    """
    if not points or not points[0]:
        return [0 for _ in points], [[]]
    k = max(1, min(k, len(points)))
    rng = random.Random(_KMEANS_SEED)
    centroids = _initial_centroids(points, k, rng)
    labels = nearest(points, centroids)
    for _ in range(_KMEANS_ITERATIONS):
        centroids = _recentre(points, labels, k)
        updated = nearest(points, centroids)
        if updated == labels:
            break
        labels = updated
    return labels, centroids


def _typical_spacing(centroids: Sequence[Sequence[float]]) -> float:
    """The tessellation's own resolution: mean nearest-neighbour gap.

    Extension needs a notion of "far", and any constant would be wrong:
    distances grow with the number of columns, and the columns come from
    the run. The gap between neighbouring centroids is the scale the
    tessellation itself was built at, so it is the scale at which a
    point is outside what it describes.
    """
    gaps = [
        min(
            _distance(centre, other)
            for index, other in enumerate(centroids)
            if index != position
        )
        for position, centre in enumerate(centroids)
    ]
    return sum(gaps) / len(gaps)


def _outliers(
    points: Sequence[Sequence[float]],
    centroids: Sequence[Sequence[float]],
    spacing: float,
) -> list[Sequence[float]]:
    """Points farther from every centroid than the grid's own spacing."""
    return [
        point
        for point in points
        if min(_distance(point, centre) for centre in centroids) > spacing
    ]


def extend(
    projection: Projection,
    behaviours: Sequence[Behaviour],
    ceiling: int,
) -> Projection:
    """Grows a frozen tessellation to cover behaviour it does not.

    Freezing is what makes a cell mean the same thing from one
    generation to the next, and its cost is that a run which changes
    character later is niched by the run it used to be: novel behaviour
    lands in whichever edge cell happens to be nearest, indistinguishable
    from the variants already there.

    This adds centroids for behaviour that sits outside the frozen
    tessellation's own resolution, and **moves none of the existing
    ones**. So a variant already well inside a cell keeps it -- the
    stability freezing exists for -- while genuinely new behaviour earns
    a cell of its own instead of being folded into the nearest one.

    Two things it deliberately does not do. It never adds *columns*: a
    categorical value the frozen population never saw has no column, and
    minting one would change the vector space and move every point in
    it. And it stops at ``ceiling``, because unbounded growth is
    re-clustering by another name -- an archive with a cell per variant
    has stopped compressing anything.

    Args:
        projection: The frozen coordinate system.
        behaviours: Every variant measured so far.
        ceiling: Most centroids the tessellation may hold.

    Returns:
        The same projection when nothing is far enough away or it is
        already at its ceiling; otherwise one with centroids appended.
    """
    centroids = list(projection.centroids)
    room = ceiling - len(centroids)
    if len(centroids) < 2 or room < 1:
        return projection
    points = project(behaviours, projection.columns)
    spacing = _typical_spacing(centroids)
    far = _outliers(points, centroids, spacing)
    if not far:
        return projection
    _, added = cluster(far, min(room, len(far)))
    return Projection(
        columns=projection.columns,
        centroids=(*projection.centroids, *(tuple(c) for c in added)),
    )


def derive_columns(
    behaviours: Sequence[Behaviour],
    features: Sequence[tuple[str, str]],
) -> tuple[Column, ...]:
    """Builds the coordinate layout the population implies.

    Args:
        behaviours: The population to measure.
        features: ``(feature, kind)`` pairs, where kind is one of the
            module's column-kind constants.

    Returns:
        The columns, in declared feature order.
    """
    columns: list[Column] = []
    for feature, kind in features:
        if kind == CATEGORY:
            columns.extend(_category_columns(behaviours, feature))
        elif kind == COMPONENT:
            columns.extend(_component_columns(behaviours, feature))
        else:
            columns.append(_numeric_column(behaviours, feature))
    return tuple(columns)


def projection_to_json(projection: Projection) -> dict[str, Any]:
    """Serializes a frozen projection for storage on a run.

    Written out in full -- columns and centroids -- because a projection
    restored without its column layout is centroids in a coordinate
    system nobody can reconstruct, which places every variant somewhere
    plausible and wrong.
    """
    return {
        "columns": [
            {
                "feature": column.feature,
                "kind": column.kind,
                "low": column.low,
                "high": column.high,
                "category": column.category,
                "index": column.index,
            }
            for column in projection.columns
        ],
        "centroids": [list(centre) for centre in projection.centroids],
    }


def _column_from_json(raw: Any) -> Column | None:
    """Rebuilds one column, or None when the record is unusable."""
    if not isinstance(raw, dict) or not isinstance(raw.get("feature"), str):
        return None
    kind = raw.get("kind")
    if kind not in (NUMERIC, CATEGORY, COMPONENT):
        return None
    return Column(
        feature=str(raw["feature"]),
        kind=str(kind),
        low=float(raw.get("low", 0.0) or 0.0),
        high=float(raw.get("high", 1.0) or 1.0),
        category=str(raw.get("category", "")),
        index=int(raw.get("index", 0) or 0),
    )


def projection_from_json(raw: Any) -> Projection:
    """Restores a frozen projection, or an empty one if it is unusable.

    Partial restoration is refused: a projection missing a column or a
    centroid is not a smaller projection, it is a different coordinate
    system, and using it would re-label every variant silently. An empty
    result simply means the run re-freezes, which costs one generation
    of cell stability and nothing else.
    """
    if not isinstance(raw, dict):
        return Projection()
    raw_columns = raw.get("columns")
    raw_centroids = raw.get("centroids")
    if not isinstance(raw_columns, list) or not isinstance(raw_centroids, list):
        return Projection()
    columns = [_column_from_json(item) for item in raw_columns]
    if not columns or any(column is None for column in columns):
        return Projection()
    width = len(columns)
    centroids = [
        tuple(float(value) for value in centre)
        for centre in raw_centroids
        if isinstance(centre, list) and len(centre) == width
    ]
    if not centroids or len(centroids) != len(raw_centroids):
        return Projection()
    return Projection(
        columns=tuple(c for c in columns if c is not None),
        centroids=tuple(centroids),
    )

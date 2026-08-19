"""Growing a frozen tessellation to cover behaviour it does not.

Freezing a coordinate system is what makes a cell mean the same thing
from one generation to the next, and its cost is blindness: behaviour
appearing afterwards lands in whichever edge cell happens to be
nearest, filed beside variants it has nothing in common with, so a run
that changes character late is niched by the run it used to be.

Everything here buys that back **without moving anything already
placed**, which is the property that makes growing safe. Split from
``tessellation`` so that module stays under the line ceiling; it holds
the coordinate system itself, this holds what happens when the
coordinate system turns out to be too small.
"""

from __future__ import annotations

from collections.abc import Sequence

from co_scientist.agents.code_evolve.tessellation import (
    CATEGORY,
    COMPONENT,
    NUMERIC,
    Behaviour,
    Column,
    Projection,
    _distance,
    _numeric_column,
    cluster,
    project,
)


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


def _new_category_columns(
    projection: Projection, behaviours: Sequence[Behaviour]
) -> list[Column]:
    """Columns for categorical values the frozen population never saw.

    Without one, every unseen value reads zero in every column of its
    feature -- so they all share one corner of the space, and "an
    operator this run had never used" is the same point as any other
    unfamiliar value. A column of its own is what makes it its own kind.
    """
    known: dict[str, set[str]] = {}
    for column in projection.columns:
        if column.kind == CATEGORY:
            known.setdefault(column.feature, set()).add(column.category)
    minted = []
    for feature, categories in sorted(known.items()):
        seen = {str(b.get(feature)) for b in behaviours if feature in b}
        for value in sorted(seen - categories):
            minted.append(
                Column(feature=feature, kind=CATEGORY, category=value)
            )
    return minted


def _new_metric_columns(
    projection: Projection, behaviours: Sequence[Behaviour]
) -> list[Column]:
    """Columns for metrics no variant had reported when this froze.

    A metric is the one measurement that is not a guess about a
    program's text: it is something the program computed and wrote
    down. A program that starts reporting a new one has told the
    archive something it has no way to represent otherwise.

    Only ever *new* keys, and only ones some existing column's feature
    set already implies are wanted -- a run that declared no metric axis
    gets none.
    """
    wanted = {
        column.feature
        for column in projection.columns
        if column.kind == NUMERIC and column.feature.startswith("metric:")
    }
    if not wanted:
        return []
    prefix = sorted(wanted)[0].split(":", 1)[0] + ":"
    seen = {
        key
        for behaviour in behaviours
        for key in behaviour
        if key.startswith(prefix)
    }
    return [_numeric_column(behaviours, key) for key in sorted(seen - wanted)]


# What a variant that does not report a column's feature reads there.
# The padding an existing centroid takes when that column is appended,
# so the new coordinate contributes exactly zero to every distance that
# already existed.
_ABSENT_VALUE = {CATEGORY: 0.0, COMPONENT: 0.0, NUMERIC: 0.5}


def _widened(projection: Projection, minted: Sequence[Column]) -> Projection:
    """Appends columns, padding every existing centroid to match.

    Appending is exactly distance-preserving, which is why it is safe on
    a frozen tessellation: a variant already placed does not report the
    new column's feature, so it reads the absent value there -- and so
    does every padded centroid, so each new coordinate contributes zero
    to every existing squared distance. The padding is per column kind
    because "absent" is not the same number for each: a category a
    variant is not reads zero, an unreported quantity sits mid-range.
    Padding is not optional -- ``_distance`` zips, so a centroid left
    short would silently truncate the comparison.
    """
    padding = tuple(_ABSENT_VALUE.get(column.kind, 0.5) for column in minted)
    return Projection(
        columns=(*projection.columns, *minted),
        centroids=tuple((*centre, *padding) for centre in projection.centroids),
    )


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

    Growth happens on both axes of that problem, and neither moves
    anything already placed. **New columns** are minted for categorical
    values -- and reported metrics -- the frozen population never saw,
    which is exactly distance-preserving (see ``_widened``). **New
    centroids** are added for behaviour sitting outside the
    tessellation's own resolution. So
    a variant already well inside a cell keeps it -- the stability
    freezing exists for -- while genuinely new behaviour earns a cell of
    its own instead of being folded into the nearest one.

    Centroid growth stops at ``ceiling``, because unbounded growth is
    re-clustering by another name -- an archive with a cell per variant
    has stopped compressing anything. Column growth has no such ceiling:
    a column is a distinction the run actually observed, and refusing to
    represent it is the blindness this exists to remove.

    Args:
        projection: The frozen coordinate system.
        behaviours: Every variant measured so far.
        ceiling: Most centroids the tessellation may hold.

    Returns:
        The same projection when nothing has changed; otherwise a wider
        one, with centroids appended when anything sits far enough out.
    """
    widened = projection
    minted = _new_category_columns(
        projection, behaviours
    ) + _new_metric_columns(projection, behaviours)
    if minted:
        widened = _widened(projection, minted)
    centroids = list(widened.centroids)
    room = ceiling - len(centroids)
    if len(centroids) < 2 or room < 1:
        return widened
    points = project(behaviours, widened.columns)
    far = _outliers(points, centroids, _typical_spacing(centroids))
    if not far:
        return widened
    _, added = cluster(far, min(room, len(far)))
    return Projection(
        columns=widened.columns,
        centroids=(*widened.centroids, *(tuple(c) for c in added)),
    )

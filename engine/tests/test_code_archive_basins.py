"""Does the archive actually escape a decoy basin, or only claim to?

The unit tests next door check that selection *reaches* every niche.
This checks the thing that motivated the archive at all: on a landscape
with an easy approach that saturates low and a harder one that ends far
higher, score-only selection gets stuck and never recovers, because the
harder approach is behind on the only axis it is judged by.

Deterministic: fixed seeds, no I/O, pure arithmetic.
"""

from __future__ import annotations

import math
import random
from typing import Any

from co_scientist.agents.code_evolve.archive import (
    ArchiveEntry,
    select_parents,
)
from co_scientist.agents.code_evolve.grid import (
    DEFAULT_DESCRIPTORS,
    METRIC_WILDCARD,
    Descriptor,
    Grid,
    GridStrategy,
)

# One categorical axis, fixed: the landscape's only real behaviour is
# which approach a variant took, so the grid should say exactly that
# rather than let CVT infer axes from a synthetic vector.
_GRID = Grid(
    descriptors=(Descriptor(feature="operator"),),
    strategy=GridStrategy.FIXED,
)

# ceiling, gain per refinement. "quick" is the decoy -- ahead at the
# start, finished by level 2. "deep" begins far worse and overtakes it,
# but only if something keeps breeding it while it is behind.
_APPROACHES = {
    "quick": (5.0, 1.6, 3.0),
    "medium": (9.0, 0.9, 1.2),
    "deep": (16.0, 1.5, 0.4),
    "wild": (11.0, 0.8, 0.2),
}
_GENERATIONS = 10
_CHILDREN = 4
_SEEDS = range(60)


def _score(approach: str, level: int) -> float:
    ceiling, gain, start = _APPROACHES[approach]
    return min(ceiling, start + gain * level)


def _mutate(genome: tuple[str, int], rng: random.Random) -> tuple[str, int]:
    """Refines the parent's approach, or occasionally switches."""
    approach, level = genome
    if rng.random() < 0.2:
        return (rng.choice(list(_APPROACHES)), 1)
    return (approach, level + 1)


def _entries(
    scored: list[tuple[tuple[str, int], float]],
) -> list[ArchiveEntry]:
    return [
        ArchiveEntry(
            variant_id=str(index),
            fitness=fitness,
            objective_values=(fitness,),
            behaviour={"operator": genome[0]},
            ordinal=index,
        )
        for index, (genome, fitness) in enumerate(scored)
    ]


def _top_k(entries: list[ArchiveEntry], count: int) -> list[ArchiveEntry]:
    """The strategy the archive replaced: breed from the best few."""
    best = sorted(entries, key=lambda e: -(e.fitness or 0.0))[:2]
    return [best[i % len(best)] for i in range(count)]


def _simulate(strategy: str, seed: int) -> float:
    """Runs one search to its budget and returns the best score found."""
    rng = random.Random(seed)
    scored: list[tuple[tuple[str, int], float]] = [
        (("quick", 0), _score("quick", 0))
    ]
    for _ in range(_GENERATIONS):
        entries = _entries(scored)
        picks = (
            _top_k(entries, _CHILDREN)
            if strategy == "top_k"
            else select_parents(entries, _CHILDREN, grid=_GRID, rng=rng)
        )
        for pick in picks:
            child = _mutate(scored[int(pick.variant_id)][0], rng)
            scored.append((child, _score(*child)))
    return max(fitness for _, fitness in scored)


def test_score_only_selection_never_leaves_the_decoy() -> None:
    # The failure the archive exists to fix, stated as a measurement:
    # every run ends at exactly the easy approach's ceiling. The harder
    # approach is generated -- the explore move produces it -- and then
    # discarded every time for being behind.
    results = [_simulate("top_k", seed) for seed in _SEEDS]
    assert max(results) == _APPROACHES["quick"][0]


def test_the_archive_escapes_the_decoy() -> None:
    results = [_simulate("archive", seed) for seed in _SEEDS]
    escaped = [score for score in results if score > _APPROACHES["quick"][0]]
    assert len(escaped) > len(results) // 2


def test_the_archive_beats_score_only_selection_on_average() -> None:
    greedy = [_simulate("top_k", seed) for seed in _SEEDS]
    archive = [_simulate("archive", seed) for seed in _SEEDS]
    assert sum(archive) / len(archive) > sum(greedy) / len(greedy) * 1.25


# The same landscape, described two ways: once with axes that say what
# kind of program a variant is, and once with an extra axis that only
# grows as a variant is refined.
_LIBS = {
    "quick": "none",
    "medium": "none",
    "deep": "numpy",
    "wild": "itertools",
}
_DEPTH = {"quick": 1.0, "medium": 2.0, "deep": 0.0, "wild": 3.0}

_KIND_AXES = (
    Descriptor(feature="operator"),
    Descriptor(feature="max_depth"),
    Descriptor(feature="imports"),
)
_WITH_PROGRESS_AXIS = (*_KIND_AXES, Descriptor(feature="source_lines"))


def _simulate_with_axes(
    descriptors: tuple[Descriptor, ...], seed: int
) -> float:
    """Runs one search under a CVT grid over the given axes."""
    grid = Grid(descriptors, GridStrategy.CVT, cells=12)
    rng = random.Random(seed)
    scored: list[tuple[tuple[str, int], float]] = [
        (("quick", 0), _score("quick", 0))
    ]
    for _ in range(_GENERATIONS):
        entries = [
            ArchiveEntry(
                variant_id=str(index),
                fitness=fitness,
                objective_values=(fitness,),
                behaviour={
                    "operator": genome[0],
                    "imports": _LIBS[genome[0]],
                    "max_depth": _DEPTH[genome[0]],
                    "source_lines": 20.0 + 8 * genome[1],
                },
                ordinal=index,
            )
            for index, (genome, fitness) in enumerate(scored)
        ]
        for pick in select_parents(entries, _CHILDREN, grid=grid, rng=rng):
            child = _mutate(scored[int(pick.variant_id)][0], rng)
            scored.append((child, _score(*child)))
    return max(fitness for _, fitness in scored)


def test_an_axis_that_tracks_refinement_degrades_the_archive() -> None:
    # Why `source_lines` is not a default descriptor. An adaptive grid
    # faithfully subdivides whatever axis it is given, so an axis that
    # only grows as a variant is polished turns the archive into "keep
    # every refinement level of every approach" and the uniform half of
    # selection re-draws one approach at different maturities.
    kind = [_simulate_with_axes(_KIND_AXES, seed) for seed in _SEEDS]
    padded = [_simulate_with_axes(_WITH_PROGRESS_AXIS, seed) for seed in _SEEDS]
    assert sum(kind) / len(kind) > sum(padded) / len(padded) * 1.15


def test_the_shipped_defaults_describe_kind_rather_than_progress() -> None:
    # A guard on the default itself, so the measurement above cannot be
    # undone by quietly adding the cheapest available axis back.
    assert [d.feature for d in DEFAULT_DESCRIPTORS] == [
        "operator",
        "max_depth",
        "imports",
        "recursion",
        "ast_shape",
        METRIC_WILDCARD,
    ]
    # Every one of those describes a kind of program. Program length --
    # the cheapest feature available -- stays out, because it grows as a
    # variant is polished and an axis that tracks maturity turns the
    # archive into "keep every refinement level of every approach".
    assert "source_lines" not in [d.feature for d in DEFAULT_DESCRIPTORS]


# Two approaches that a static reading of their text cannot tell apart:
# same nesting, same dependencies, same shape. They differ only in what
# they compute, which the programs report as a metric. This is the case
# the syntactic fingerprint provably cannot separate -- deciding whether
# two programs in the same shape compute different things is not a
# question static analysis answers in general.
_TWINS = {
    "twin_quick": (5.0, 1.6, 3.0),
    "twin_deep": (16.0, 1.5, 0.4),
}
_TWIN_FOOTPRINT = {"twin_quick": 1.0, "twin_deep": 40.0}
_SHAPE = {"max_depth": 2.0, "imports": "none"}

_SYNTACTIC_AXES = (
    Descriptor(feature="max_depth"),
    Descriptor(feature="imports"),
)
_WITH_SEMANTIC_AXIS = (*_SYNTACTIC_AXES, Descriptor(feature=METRIC_WILDCARD))


def _twin_score(approach: str, level: int) -> float:
    ceiling, gain, start = _TWINS[approach]
    return min(ceiling, start + gain * level)


def _twin_mutate(
    genome: tuple[str, int], rng: random.Random
) -> tuple[str, int]:
    approach, level = genome
    if rng.random() < 0.2:
        return (rng.choice(list(_TWINS)), 1)
    return (approach, level + 1)


def _simulate_twins(descriptors: tuple[Descriptor, ...], seed: int) -> float:
    """Runs one search where the two approaches share every shape."""
    grid = Grid(descriptors, GridStrategy.CVT, cells=12)
    rng = random.Random(seed)
    scored: list[tuple[tuple[str, int], float]] = [
        (("twin_quick", 0), _twin_score("twin_quick", 0))
    ]
    for _ in range(_GENERATIONS):
        entries = [
            ArchiveEntry(
                variant_id=str(index),
                fitness=fitness,
                objective_values=(fitness,),
                behaviour={
                    **_SHAPE,
                    "metric:footprint": _TWIN_FOOTPRINT[genome[0]],
                },
                ordinal=index,
            )
            for index, (genome, fitness) in enumerate(scored)
        ]
        for pick in select_parents(entries, _CHILDREN, grid=grid, rng=rng):
            child = _twin_mutate(scored[int(pick.variant_id)][0], rng)
            scored.append((child, _twin_score(*child)))
    return max(fitness for _, fitness in scored)


def test_a_reported_metric_separates_what_the_syntax_cannot() -> None:
    # The measurement behind `metric:*`. With only structural axes the
    # two approaches are one cell, so the archive keeps one elite and
    # collapses to score-only selection inside it -- the decoy wins.
    # A metric the programs report is execution-derived, not a reading
    # of their text, and it is the only thing that tells them apart.
    blind = [_simulate_twins(_SYNTACTIC_AXES, seed) for seed in _SEEDS]
    seeing = [_simulate_twins(_WITH_SEMANTIC_AXIS, seed) for seed in _SEEDS]
    escapes_blind = sum(1 for best in blind if best > _TWINS["twin_quick"][0])
    escapes_seeing = sum(1 for best in seeing if best > _TWINS["twin_quick"][0])
    assert escapes_seeing > escapes_blind
    assert sum(seeing) / len(seeing) > sum(blind) / len(blind)


# Learning the axes instead of choosing them. PCA is the cheapest honest
# learner: it derives directions from the population rather than from
# anyone's judgement about what matters. Two feature sets are fed to it
# -- everything available, and the curated subset the defaults ship --
# because which one it is given turns out to be the whole story.
_ALL_FEATURES = ("max_depth", "branch_count", "source_lines")
_KIND_FEATURES = ("max_depth",)
_PCA_COMPONENTS = 2
_PCA_ITERATIONS = 40


def _rows(
    behaviours: list[dict[str, Any]], keys: tuple[str, ...]
) -> list[list[float]]:
    """Scales the named features into [0, 1], one row per variant."""
    raw = [[float(b[key]) for key in keys] for b in behaviours]
    lows = [min(row[i] for row in raw) for i in range(len(keys))]
    highs = [max(row[i] for row in raw) for i in range(len(keys))]
    return [
        [
            0.5
            if highs[i] == lows[i]
            else (row[i] - lows[i]) / (highs[i] - lows[i])
            for i in range(len(keys))
        ]
        for row in raw
    ]


def _components(rows: list[list[float]], count: int) -> list[list[float]]:
    """Top principal directions, by power iteration with deflation."""
    width = len(rows[0])
    means = [sum(row[i] for row in rows) / len(rows) for i in range(width)]
    centred = [[v - means[i] for i, v in enumerate(row)] for row in rows]
    found: list[list[float]] = []
    for _ in range(count):
        vec = [1.0 / math.sqrt(width)] * width
        for _ in range(_PCA_ITERATIONS):
            out = [0.0] * width
            for row in centred:
                dot = sum(a * b for a, b in zip(row, vec, strict=True))
                for i in range(width):
                    out[i] += dot * row[i]
            norm = math.sqrt(sum(v * v for v in out)) or 1.0
            vec = [v / norm for v in out]
        found.append(vec)
        centred = [
            [
                v - sum(a * b for a, b in zip(row, vec, strict=True)) * vec[i]
                for i, v in enumerate(row)
            ]
            for row in centred
        ]
    return found


def _learned(
    behaviours: list[dict[str, Any]], keys: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Re-describes every variant along axes derived from the population."""
    rows = _rows(behaviours, keys)
    comps = _components(rows, min(_PCA_COMPONENTS, len(keys)))
    return [
        {
            f"pc{i}": sum(a * b for a, b in zip(row, comp, strict=True))
            for i, comp in enumerate(comps)
        }
        for row in rows
    ]


def _simulate_learned(keys: tuple[str, ...], seed: int) -> float:
    """Runs one search whose axes are learned from what it has seen."""
    grid = Grid(
        tuple(
            Descriptor(f"pc{i}") for i in range(min(_PCA_COMPONENTS, len(keys)))
        ),
        GridStrategy.CVT,
        cells=12,
    )
    rng = random.Random(seed)
    scored: list[tuple[tuple[str, int], float]] = [
        (("quick", 0), _score("quick", 0))
    ]
    for _ in range(_GENERATIONS):
        measured = [
            {
                "max_depth": _DEPTH[genome[0]],
                "branch_count": float(len(genome[0])),
                "source_lines": 20.0 + 8 * genome[1],
            }
            for genome, _ in scored
        ]
        learned = _learned(measured, keys)
        entries = [
            ArchiveEntry(str(index), fitness, (fitness,), learned[index], index)
            for index, (_, fitness) in enumerate(scored)
        ]
        for pick in select_parents(entries, _CHILDREN, grid=grid, rng=rng):
            child = _mutate(scored[int(pick.variant_id)][0], rng)
            scored.append((child, _score(*child)))
    return max(fitness for _, fitness in scored)


def test_learned_axes_inherit_the_flaw_in_what_they_are_fed() -> None:
    """Why the axes are hand-written and not learned.

    PCA maximizes variance, and in program space the direction of
    greatest variance is maturity: programs grow as they are refined.
    Handed every available feature it finds that direction first and
    reproduces the refinement-axis collapse almost exactly -- the same
    result as declaring `source_lines` outright.

    Handed the curated features instead it is *indistinguishable* from
    the hand-written grid. So learning does not substitute for choosing
    what to measure: it can only re-mix what it is given, and what it is
    given is the decision that mattered all along. The same shape as the
    strategy finding above -- with the right axes every strategy scored
    alike, and so does every learner.
    """
    hand = [_simulate_with_axes(_KIND_AXES, seed) for seed in _SEEDS]
    from_all = [_simulate_learned(_ALL_FEATURES, seed) for seed in _SEEDS]
    from_kind = [_simulate_learned(_KIND_FEATURES, seed) for seed in _SEEDS]

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    assert mean(from_all) < mean(hand) * 0.85
    assert mean(from_kind) >= mean(hand) * 0.95

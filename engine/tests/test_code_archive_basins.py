"""Does the archive actually escape a decoy basin, or only claim to?

The unit tests next door check that selection *reaches* every niche.
This checks the thing that motivated the archive at all: on a landscape
with an easy approach that saturates low and a harder one that ends far
higher, score-only selection gets stuck and never recovers, because the
harder approach is behind on the only axis it is judged by.

Deterministic: fixed seeds, no I/O, pure arithmetic.
"""

from __future__ import annotations

import random

from co_scientist.agents.code_evolve.archive import (
    ArchiveEntry,
    select_parents,
)
from co_scientist.agents.code_evolve.grid import (
    DEFAULT_DESCRIPTORS,
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
    ]
    # Every one of those describes a kind of program. Program length --
    # the cheapest feature available -- stays out, because it grows as a
    # variant is polished and an axis that tracks maturity turns the
    # archive into "keep every refinement level of every approach".
    assert "source_lines" not in [d.feature for d in DEFAULT_DESCRIPTORS]

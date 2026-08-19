"""A MAP-Elites archive: what stops a search collapsing into one basin.

Selecting parents by score alone is the obvious strategy and a
consistently bad one. The best few programs in a generation are usually
near-copies of each other, so breeding from them produces more of the
same, and the search settles into the first decent basin it finds and
polishes it for the rest of its budget. Nothing looks wrong while this
happens -- the score improves, slowly, forever.

The fix is to stop keeping *the best* and start keeping **the best of
each kind**. Every variant is assigned a niche from its behaviour -- how
long the program is, what move produced it, where its secondary metrics
land -- and the archive holds one elite per occupied niche. Parents are
drawn from that archive, so a compact-but-mediocre program and a
sprawling-but-strong one are both still in play, and the run keeps a
frontier of genuinely different approaches rather than one lineage.

Two adaptations to this codebase's actual budget, both deliberate:

**Selection is half exploit, half explore.** Textbook MAP-Elites samples
occupied niches uniformly, which is right when the budget is tens of
thousands of evaluations. A run here evaluates tens. Spending all of it
uniformly would leave every niche shallow and none of them refined, so
half the children come from the strongest elites and half from a uniform
draw across niches. The uniform half is what prevents collapse; the
greedy half is what makes progress inside a small budget.

**The default descriptors are behavioural and free.** A run that declares
none still gets a real grid, because the two axes that always exist --
the operator that produced the variant, and how long the program is --
already separate a tuned constant from a rewritten algorithm. A run that
knows its own domain should say so; `descriptors` in the run config takes
any reported metric as an axis.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from co_scientist.code_eval.pareto import ObjectiveValues, pareto_front

# Axis names the archive can compute without the program reporting
# anything. Everything else is a metric, named `metric:<key>`.
SOURCE_BYTES = "source_bytes"
SOURCE_LINES = "source_lines"
OPERATOR = "operator"
METRIC_PREFIX = "metric:"

# What a run gets when it declares no descriptors. Two axes that exist
# for every variant of every run: the move that produced it, and its
# size. The size edges are coarse on purpose -- they separate a one-line
# tweak from a rewrite, and a run that needs finer resolution knows its
# own scale better than a default can.
DEFAULT_DESCRIPTORS: tuple[Descriptor, ...]

# Fraction of a generation's children bred from the strongest elites
# rather than from a uniform draw across niches. See the module
# docstring: pure uniform selection is correct at textbook scale and
# wrong at this one.
EXPLOIT_SHARE = 0.5


@dataclass(frozen=True)
class Descriptor:
    """One axis of the archive's grid.

    Attributes:
        feature: What is measured -- ``operator``, ``source_bytes``,
            ``source_lines``, or ``metric:<key>`` for anything the
            program reports.
        bins: Ascending edges. A value falls in the bin counting how many
            edges it is at or above, so ``[10, 100]`` gives three bins.
            Empty for a categorical feature like ``operator``, which
            bins itself.
    """

    feature: str
    bins: tuple[float, ...] = ()


DEFAULT_DESCRIPTORS = (
    Descriptor(feature=OPERATOR),
    Descriptor(feature=SOURCE_LINES, bins=(20.0, 80.0, 250.0)),
)


@dataclass(frozen=True)
class ArchiveEntry:
    """One evaluated variant, as the archive sees it.

    Attributes:
        variant_id: Identifies it to the caller.
        fitness: Primary-objective score; None when it never scored.
        objective_values: Every objective's score, for dominance.
        operator: The move that produced it, or None for the seed.
        source_lines: Total lines across the program's files.
        source_bytes: Total size of the program's files.
        metrics: What it reported, raw.
        ordinal: Its attempt number, used only to break ties toward the
            earlier attempt -- the same rule the rest of the store uses.
    """

    variant_id: str
    fitness: float | None = None
    objective_values: tuple[float | None, ...] = ()
    operator: str | None = None
    source_lines: int = 0
    source_bytes: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    ordinal: int = 0


def _feature_value(entry: ArchiveEntry, feature: str) -> Any:
    """Reads one axis off a variant, or None when it has no value there."""
    if feature == OPERATOR:
        return entry.operator or "seed"
    if feature == SOURCE_LINES:
        return float(entry.source_lines)
    if feature == SOURCE_BYTES:
        return float(entry.source_bytes)
    if feature.startswith(METRIC_PREFIX):
        return entry.metrics.get(feature[len(METRIC_PREFIX) :])
    return None


def _bin_index(value: Any, bins: tuple[float, ...]) -> Any:
    """Places a value on one axis.

    A categorical axis (no bins) is its own coordinate. A numeric value
    becomes the count of edges it meets or exceeds. A missing value gets
    its own coordinate rather than being folded into the lowest bin --
    "did not report this" is a different behaviour from "reported the
    smallest value", and merging them hides a whole class of variant in
    the corner of the grid.
    """
    if not bins:
        return value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "unknown"
    return sum(1 for edge in bins if value >= edge)


def niche_key(
    entry: ArchiveEntry, descriptors: Sequence[Descriptor]
) -> tuple[Any, ...]:
    """Computes the grid cell a variant belongs to.

    Args:
        entry: The evaluated variant.
        descriptors: The run's axes, in order.

    Returns:
        One coordinate per axis. Stable for a given variant and set of
        descriptors, so it can be stored once at evaluation time.
    """
    return tuple(
        _bin_index(_feature_value(entry, d.feature), d.bins)
        for d in descriptors
    )


def _better(candidate: ArchiveEntry, incumbent: ArchiveEntry) -> bool:
    """Whether a candidate should replace a cell's current elite.

    Scored beats unscored; between two scored, higher primary fitness
    wins; ties go to the earlier attempt, matching `best_code_variant`.
    An unscored variant can still hold an empty cell, because a niche
    whose only member crashed is still worth a repair attempt.
    """
    if candidate.fitness is None:
        return False
    if incumbent.fitness is None:
        return True
    if candidate.fitness != incumbent.fitness:
        return candidate.fitness > incumbent.fitness
    return candidate.ordinal < incumbent.ordinal


def build_archive(
    entries: Sequence[ArchiveEntry], descriptors: Sequence[Descriptor]
) -> dict[tuple[Any, ...], ArchiveEntry]:
    """Reduces every evaluated variant to one elite per occupied niche.

    Args:
        entries: Every evaluated variant in the run.
        descriptors: The run's axes.

    Returns:
        The elite per niche, keyed by cell.
    """
    elites: dict[tuple[Any, ...], ArchiveEntry] = {}
    for entry in entries:
        key = niche_key(entry, descriptors)
        incumbent = elites.get(key)
        if incumbent is None or _better(entry, incumbent):
            elites[key] = entry
    return elites


def _exploit_order(entries: Sequence[ArchiveEntry]) -> list[ArchiveEntry]:
    """Elites ranked strongest-first, unscored ones last."""
    return sorted(
        entries,
        key=lambda e: (e.fitness is None, -(e.fitness or 0.0), e.ordinal),
    )


def _front_entries(
    entries: Sequence[ArchiveEntry],
) -> list[ArchiveEntry]:
    """The elites no other elite dominates across every objective.

    With one objective this is just the joint best. With several it is
    the set of real trades, and including it in the candidate pool is
    what keeps a variant that wins only on the second objective from
    being bred out by variants that win on the first.
    """
    values: list[ObjectiveValues] = [e.objective_values for e in entries]
    return [entries[index] for index in pareto_front(values)]


def select_parents(
    entries: Sequence[ArchiveEntry],
    count: int,
    *,
    descriptors: Sequence[Descriptor] = DEFAULT_DESCRIPTORS,
    rng: random.Random | None = None,
) -> list[ArchiveEntry]:
    """Chooses the parents for the next generation.

    Args:
        entries: Every evaluated variant in the run.
        count: How many children the generation will have.
        descriptors: The run's grid axes.
        rng: Source of randomness, injectable so a test can pin the draw.

    Returns:
        One parent per child, in order. Empty only when there is nothing
        to breed from at all.

    Half the slots go to the strongest elites and to the Pareto front --
    the part that makes progress -- and half to a uniform draw across
    occupied niches, which is the part that keeps the run from spending
    its whole budget polishing one basin. Both halves draw from the
    archive rather than from the raw variant list, so a hundred
    near-identical children of one good program still occupy one cell
    and get one share of attention.
    """
    if count < 1:
        return []
    elites = list(build_archive(entries, descriptors).values())
    if not elites:
        return []

    source = rng or random.Random()
    exploit_count = min(len(elites), max(1, round(count * EXPLOIT_SHARE)))
    preferred = _exploit_order(_front_entries(elites) or elites)
    chosen = preferred[:exploit_count]
    chosen.extend(
        source.choice(elites) for _ in range(max(0, count - len(chosen)))
    )
    return chosen[:count]

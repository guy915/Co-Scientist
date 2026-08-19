"""The diversity archive and Pareto dominance.

The tests that matter here are the ones a score-only search fails: a
generation of near-identical top scorers must not take every parent
slot, and a variant that wins only on the second objective must survive.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from co_scientist.agents.code_evolve.archive import (
    ArchiveEntry,
    Descriptor,
    build_archive,
    niche_key,
    select_parents,
)
from co_scientist.code_eval import dominates, pareto_front


def entry(
    variant_id: str, fitness: float | None = None, **over: Any
) -> ArchiveEntry:
    """One archive entry, with the fields a test does not pin defaulted."""
    lines = int(over.get("lines", 10))
    values = over.get("values")
    return ArchiveEntry(
        variant_id=variant_id,
        fitness=fitness,
        objective_values=values if values is not None else (fitness,),
        operator=over.get("operator"),
        source_lines=lines,
        source_bytes=lines * 30,
        metrics=over.get("metrics") or {},
        ordinal=int(over.get("ordinal", 0)),
    )


class TestDominance:
    def test_better_on_every_axis_dominates(self) -> None:
        assert dominates((2.0, 2.0), (1.0, 1.0))

    def test_a_tie_on_every_axis_dominates_nothing(self) -> None:
        assert not dominates((1.0, 1.0), (1.0, 1.0))

    def test_a_trade_dominates_nothing_either_way(self) -> None:
        assert not dominates((2.0, 1.0), (1.0, 2.0))
        assert not dominates((1.0, 2.0), (2.0, 1.0))

    def test_equal_on_one_axis_and_better_on_another_dominates(self) -> None:
        assert dominates((1.0, 2.0), (1.0, 1.0))

    def test_a_missing_objective_is_skipped_not_scored(self) -> None:
        # None means "no position on this axis", so the comparison runs
        # on the axes both sides reported. Treating None as a floor
        # instead would let a variant dominate purely by having measured
        # more things than its rival.
        assert not dominates((1.0, None), (5.0, 5.0))
        assert dominates((5.0, None), (1.0, 5.0))

    def test_two_variants_sharing_no_axis_are_incomparable(self) -> None:
        assert not dominates((None, 5.0), (1.0, None))
        assert not dominates((1.0, None), (None, 5.0))

    def test_a_partial_variant_stays_on_the_front_when_it_leads(
        self,
    ) -> None:
        # It reported one objective and won it. Dropping it for not
        # measuring the other would discard the best program on the axis
        # it did measure.
        assert 1 in pareto_front([(1.0, 1.0), (9.0, None)])

    def test_a_front_keeps_every_real_trade(self) -> None:
        front = pareto_front([(2.0, 1.0), (1.0, 2.0), (1.0, 1.0)])
        assert front == (0, 1)

    def test_a_variant_that_measured_nothing_is_not_on_the_front(
        self,
    ) -> None:
        assert pareto_front([(None, None), (1.0, 1.0)]) == (1,)

    def test_a_single_objective_front_is_the_joint_best(self) -> None:
        assert pareto_front([(1.0,), (3.0,), (3.0,)]) == (1, 2)


class TestNiching:
    def test_the_operator_separates_kinds_of_change(self) -> None:
        descriptors = [Descriptor(feature="operator")]
        tuned = entry("a", 1.0, operator="hyperparameters")
        rewritten = entry("b", 1.0, operator="algorithm_swap")
        assert niche_key(tuned, descriptors) != niche_key(
            rewritten, descriptors
        )

    def test_the_seed_has_its_own_operator_cell(self) -> None:
        descriptors = [Descriptor(feature="operator")]
        assert niche_key(entry("a", 1.0), descriptors) == ("seed",)

    def test_size_bins_count_edges_met(self) -> None:
        descriptors = [Descriptor(feature="source_lines", bins=(10.0, 100.0))]
        assert niche_key(entry("a", lines=5), descriptors) == (0,)
        assert niche_key(entry("b", lines=10), descriptors) == (1,)
        assert niche_key(entry("c", lines=500), descriptors) == (2,)

    def test_a_metric_axis_reads_what_the_program_reported(self) -> None:
        descriptors = [Descriptor(feature="metric:memory_mb", bins=(100.0,))]
        light = entry("a", metrics={"memory_mb": 50.0})
        heavy = entry("b", metrics={"memory_mb": 900.0})
        assert niche_key(light, descriptors) == (0,)
        assert niche_key(heavy, descriptors) == (1,)

    def test_an_unreported_axis_gets_its_own_cell(self) -> None:
        # Not folded into the lowest bin: "did not report" is a
        # different behaviour from "reported the smallest value", and
        # merging them hides a whole class of variant.
        descriptors = [Descriptor(feature="metric:memory_mb", bins=(100.0,))]
        assert niche_key(entry("a"), descriptors) == ("unknown",)


class TestArchive:
    def test_one_elite_survives_per_niche(self) -> None:
        descriptors = [Descriptor(feature="operator")]
        elites = build_archive(
            [
                entry("weak", 1.0, operator="vectorize", ordinal=1),
                entry("strong", 5.0, operator="vectorize", ordinal=2),
                entry("other", 2.0, operator="simplify", ordinal=3),
            ],
            descriptors,
        )
        assert {e.variant_id for e in elites.values()} == {"strong", "other"}

    def test_a_scored_variant_displaces_an_unscored_one(self) -> None:
        descriptors = [Descriptor(feature="operator")]
        elites = build_archive(
            [
                entry("crashed", None, operator="repair", ordinal=1),
                entry("works", 0.0, operator="repair", ordinal=2),
            ],
            descriptors,
        )
        assert next(iter(elites.values())).variant_id == "works"

    def test_an_unscored_variant_still_holds_an_empty_cell(self) -> None:
        # A niche whose only member crashed is still worth repairing.
        descriptors = [Descriptor(feature="operator")]
        elites = build_archive(
            [entry("crashed", None, operator="repair")], descriptors
        )
        assert next(iter(elites.values())).variant_id == "crashed"

    def test_a_tie_keeps_the_earlier_attempt(self) -> None:
        descriptors = [Descriptor(feature="operator")]
        elites = build_archive(
            [
                entry("later", 3.0, operator="simplify", ordinal=9),
                entry("earlier", 3.0, operator="simplify", ordinal=2),
            ],
            descriptors,
        )
        assert next(iter(elites.values())).variant_id == "earlier"


class TestSelection:
    def test_near_identical_top_scorers_do_not_take_every_slot(self) -> None:
        # The failure this whole module exists to prevent. Score-only
        # selection returns the four best, which here are four copies of
        # one program; the archive collapses them to one cell and gives
        # the rest of the generation to genuinely different variants.
        crowd = [
            entry(
                f"tweak{i}",
                9.0 - i * 0.01,
                operator="hyperparameters",
                lines=40,
                ordinal=i,
            )
            for i in range(8)
        ]
        different = [
            entry("small", 2.0, operator="simplify", lines=5, ordinal=20),
            entry("big", 3.0, operator="algorithm_swap", lines=300, ordinal=21),
        ]
        parents = select_parents(crowd + different, 4, rng=random.Random(0))
        chosen = {p.variant_id for p in parents}
        assert len(chosen & {v.variant_id for v in crowd}) <= 2
        assert chosen & {"small", "big"}

    def test_the_strongest_elite_is_always_bred_from(self) -> None:
        # The explore half must not cost the run its best program.
        entries = [
            entry("best", 9.0, operator="targeted_edit", ordinal=1),
            entry("mid", 4.0, operator="simplify", ordinal=2),
            entry("weak", 1.0, operator="explore", ordinal=3),
        ]
        for seed in range(20):
            parents = select_parents(entries, 4, rng=random.Random(seed))
            assert "best" in {p.variant_id for p in parents}

    def test_a_second_objective_winner_survives_selection(self) -> None:
        # It loses on the primary axis, so score-only selection drops it.
        # It is on the Pareto front, so the archive keeps breeding it.
        entries = [
            entry(
                "fast_but_wrong",
                1.0,
                operator="vectorize",
                ordinal=1,
                values=(1.0, 9.0),
            ),
            entry(
                "accurate",
                9.0,
                operator="targeted_edit",
                ordinal=2,
                values=(9.0, 1.0),
            ),
        ]
        parents = select_parents(entries, 2, rng=random.Random(3))
        assert {p.variant_id for p in parents} == {
            "fast_but_wrong",
            "accurate",
        }

    def test_selection_returns_exactly_the_requested_count(self) -> None:
        entries = [entry("only", 1.0, operator="seed")]
        assert len(select_parents(entries, 4, rng=random.Random(0))) == 4

    def test_nothing_to_breed_from_returns_nothing(self) -> None:
        assert select_parents([], 4) == []

    def test_a_zero_child_generation_asks_for_no_parents(self) -> None:
        assert select_parents([entry("a", 1.0)], 0) == []

    def test_every_occupied_niche_is_reachable(self) -> None:
        # A cell that selection can never draw from is a cell that does
        # not diversify anything.
        entries = [
            entry(f"v{i}", float(i), operator=op, ordinal=i)
            for i, op in enumerate(["seed", "simplify", "vectorize", "explore"])
        ]
        drawn: set[str] = set()
        for seed in range(60):
            drawn.update(
                p.variant_id
                for p in select_parents(entries, 4, rng=random.Random(seed))
            )
        assert drawn == {"v0", "v1", "v2", "v3"}


@pytest.mark.parametrize("count", [1, 2, 3, 4, 8])
def test_selection_never_returns_more_than_asked(count: int) -> None:
    entries = [entry(f"v{i}", float(i), operator=f"op{i}") for i in range(6)]
    parents = select_parents(entries, count, rng=random.Random(1))
    assert len(parents) == count

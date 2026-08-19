"""The diversity archive: a Pareto front per cell, and selection from it.

The tests that matter are the ones a simpler archive fails: a cell must
not reduce two genuinely different trades to whichever wins on the
primary objective, and a crowded cell must not take selection slots
proportional to how many variants it happens to hold.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from co_scientist.agents.code_evolve.archive import (
    DEFAULT_CELL_CAPACITY,
    ArchiveEntry,
    archive_coverage,
    build_archive,
    select_parents,
)
from co_scientist.agents.code_evolve.grid import (
    Descriptor,
    Grid,
    GridStrategy,
)
from co_scientist.code_eval import dominates, pareto_front

# One categorical axis, declared: these tests are about what the archive
# does with cells, not about how cells are derived (see test_code_grid).
_BY_OPERATOR = Grid(
    descriptors=(Descriptor(feature="operator"),),
    strategy=GridStrategy.FIXED,
)


def entry(
    variant_id: str, fitness: float | None = None, **over: Any
) -> ArchiveEntry:
    """One archive entry, with the fields a test does not pin defaulted."""
    values = over.get("values")
    return ArchiveEntry(
        variant_id=variant_id,
        fitness=fitness,
        objective_values=values if values is not None else (fitness,),
        behaviour={"operator": over.get("operator", "seed")},
        ordinal=int(over.get("ordinal", 0)),
    )


class TestDominance:
    def test_better_on_every_axis_dominates(self) -> None:
        assert dominates((2.0, 2.0), (1.0, 1.0))

    def test_a_trade_dominates_nothing_either_way(self) -> None:
        assert not dominates((2.0, 1.0), (1.0, 2.0))
        assert not dominates((1.0, 2.0), (2.0, 1.0))

    def test_a_missing_objective_is_skipped_not_scored(self) -> None:
        assert not dominates((1.0, None), (5.0, 5.0))
        assert dominates((5.0, None), (1.0, 5.0))

    def test_two_variants_sharing_no_axis_are_incomparable(self) -> None:
        assert not dominates((None, 5.0), (1.0, None))

    def test_a_front_keeps_every_real_trade(self) -> None:
        assert pareto_front([(2.0, 1.0), (1.0, 2.0), (1.0, 1.0)]) == (0, 1)

    def test_a_variant_that_measured_nothing_is_not_on_the_front(
        self,
    ) -> None:
        assert pareto_front([(None, None), (1.0, 1.0)]) == (1,)


class TestCells:
    def test_a_cell_keeps_both_sides_of_a_trade(self) -> None:
        # The limit this closes. Reducing a cell to its best-by-primary
        # discards a variant nothing dominates -- the same collapse the
        # archive exists to prevent, one level down.
        cells = build_archive(
            [
                entry("accurate", 9.0, operator="a", values=(9.0, 1.0)),
                entry("fast", 1.0, operator="a", values=(1.0, 9.0)),
            ],
            grid=_BY_OPERATOR,
        )
        held = {e.variant_id for group in cells.values() for e in group}
        assert held == {"accurate", "fast"}

    def test_a_dominated_variant_is_dropped_from_its_cell(self) -> None:
        cells = build_archive(
            [
                entry("good", 9.0, operator="a", values=(9.0, 9.0)),
                entry("worse", 1.0, operator="a", values=(1.0, 1.0)),
            ],
            grid=_BY_OPERATOR,
        )
        held = {e.variant_id for group in cells.values() for e in group}
        assert held == {"good"}

    def test_a_cell_is_capped(self) -> None:
        # An unbounded cell is a list of every variant with extra steps.
        entries = [
            entry(
                f"v{i}",
                float(i),
                operator="a",
                ordinal=i,
                values=(float(i), float(-i)),
            )
            for i in range(8)
        ]
        cells = build_archive(entries, grid=_BY_OPERATOR, capacity=3)
        assert all(len(group) <= 3 for group in cells.values())

    def test_a_capped_cell_keeps_its_extremes(self) -> None:
        # Pruning by crowding, not by score: dropping the least-scoring
        # member would delete exactly the trade the cell is there to
        # keep, so the endpoints of the front must survive.
        entries = [
            entry(
                f"v{i}",
                float(i),
                operator="a",
                ordinal=i,
                values=(float(i), float(10 - i)),
            )
            for i in range(6)
        ]
        cells = build_archive(entries, grid=_BY_OPERATOR, capacity=3)
        held = {e.variant_id for group in cells.values() for e in group}
        assert {"v0", "v5"} <= held

    def test_separate_cells_stay_separate(self) -> None:
        cells = build_archive(
            [
                entry("a", 1.0, operator="vectorize"),
                entry("b", 5.0, operator="simplify"),
            ],
            grid=_BY_OPERATOR,
        )
        assert len(cells) == 2

    def test_an_unscored_variant_holds_an_otherwise_empty_cell(self) -> None:
        # A niche whose only member crashed is still worth repairing.
        cells = build_archive(
            [entry("crashed", None, operator="repair")], grid=_BY_OPERATOR
        )
        assert next(iter(cells.values()))[0].variant_id == "crashed"

    def test_an_unscored_variant_yields_to_a_working_one(self) -> None:
        cells = build_archive(
            [
                entry("crashed", None, operator="repair", ordinal=1),
                entry("works", 0.0, operator="repair", ordinal=2),
            ],
            grid=_BY_OPERATOR,
        )
        held = {e.variant_id for group in cells.values() for e in group}
        assert held == {"works"}

    def test_the_default_capacity_leaves_room_for_a_trade(self) -> None:
        assert DEFAULT_CELL_CAPACITY > 1


class TestSelection:
    def test_near_identical_top_scorers_do_not_take_every_slot(self) -> None:
        crowd = [
            entry(
                f"tweak{i}",
                9.0 - i * 0.01,
                operator="hyperparameters",
                ordinal=i,
            )
            for i in range(8)
        ]
        different = [
            entry("small", 2.0, operator="simplify", ordinal=20),
            entry("big", 3.0, operator="algorithm_swap", ordinal=21),
        ]
        chosen = {
            p.variant_id
            for p in select_parents(
                crowd + different,
                4,
                grid=_BY_OPERATOR,
                rng=random.Random(0),
            )
        }
        assert len(chosen & {v.variant_id for v in crowd}) <= 2
        assert chosen & {"small", "big"}

    def test_a_crowded_cell_does_not_buy_extra_attention(self) -> None:
        # Drawing a cell first and a member second is what keeps
        # population size out of the selection decision.
        crowded = [
            entry(
                f"c{i}",
                float(i),
                operator="a",
                ordinal=i,
                values=(float(i), float(-i)),
            )
            for i in range(3)
        ]
        lone = [entry("lonely", 1.0, operator="b", ordinal=9)]
        draws = [
            p.variant_id
            for seed in range(80)
            for p in select_parents(
                crowded + lone,
                4,
                grid=_BY_OPERATOR,
                rng=random.Random(seed),
            )
        ]
        assert draws.count("lonely") > len(draws) // 8

    def test_the_strongest_member_is_always_bred_from(self) -> None:
        entries = [
            entry("best", 9.0, operator="targeted_edit", ordinal=1),
            entry("mid", 4.0, operator="simplify", ordinal=2),
            entry("weak", 1.0, operator="explore", ordinal=3),
        ]
        for seed in range(20):
            parents = select_parents(
                entries, 4, grid=_BY_OPERATOR, rng=random.Random(seed)
            )
            assert "best" in {p.variant_id for p in parents}

    def test_a_second_objective_winner_survives_selection(self) -> None:
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
        parents = select_parents(
            entries, 2, grid=_BY_OPERATOR, rng=random.Random(3)
        )
        assert {p.variant_id for p in parents} == {
            "fast_but_wrong",
            "accurate",
        }

    def test_every_occupied_cell_is_reachable(self) -> None:
        entries = [
            entry(f"v{i}", float(i), operator=op, ordinal=i)
            for i, op in enumerate(["seed", "simplify", "vectorize", "explore"])
        ]
        drawn: set[str] = set()
        for seed in range(60):
            drawn.update(
                p.variant_id
                for p in select_parents(
                    entries, 4, grid=_BY_OPERATOR, rng=random.Random(seed)
                )
            )
        assert drawn == {"v0", "v1", "v2", "v3"}

    def test_nothing_to_breed_from_returns_nothing(self) -> None:
        assert select_parents([], 4) == []

    def test_a_zero_child_generation_asks_for_no_parents(self) -> None:
        assert select_parents([entry("a", 1.0)], 0) == []


class TestCoverageReport:
    def test_coverage_counts_cells_and_how_evenly_they_are_filled(
        self,
    ) -> None:
        entries = [
            entry(f"v{i}", 1.0, operator=op, ordinal=i)
            for i, op in enumerate(["a", "b", "c"])
        ]
        occupied, evenness = archive_coverage(entries, grid=_BY_OPERATOR)
        assert occupied == 3
        assert evenness == pytest.approx(1.0)

    def test_a_collapsed_run_reports_no_evenness(self) -> None:
        entries = [
            entry(f"v{i}", 1.0, operator="a", ordinal=i) for i in range(5)
        ]
        occupied, evenness = archive_coverage(entries, grid=_BY_OPERATOR)
        assert occupied == 1
        assert evenness == 0.0


@pytest.mark.parametrize("count", [1, 2, 3, 4, 8])
def test_selection_returns_exactly_the_requested_count(count: int) -> None:
    entries = [
        entry(f"v{i}", float(i), operator=f"op{i}", ordinal=i) for i in range(6)
    ]
    parents = select_parents(
        entries, count, grid=_BY_OPERATOR, rng=random.Random(1)
    )
    assert len(parents) == count

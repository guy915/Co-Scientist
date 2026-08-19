"""Turning behaviour into cells: fixed, adaptive, and CVT grids.

The failure a fixed grid has is silent in both directions -- edges too
coarse and the archive keeps one elite, edges too fine and it keeps
everything -- so the tests below check that the adaptive strategies
survive the distributions that break a declared one.
"""

from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.code_evolve.grid import (
    DEFAULT_CELLS,
    Descriptor,
    Grid,
    GridStrategy,
    assign_cells,
    coverage,
)


def _behaviours(
    values: list[float], feature: str = "source_lines"
) -> list[dict[str, Any]]:
    return [{feature: value} for value in values]


class TestFixed:
    def test_declared_edges_place_values_in_bins(self) -> None:
        grid = Grid(
            descriptors=(Descriptor("source_lines", bins=(10.0, 100.0)),),
            strategy=GridStrategy.FIXED,
        )
        cells = assign_cells(_behaviours([5.0, 10.0, 500.0]), grid)
        assert cells == [(0,), (1,), (2,)]

    def test_coarse_edges_collapse_everything_into_one_cell(self) -> None:
        # The silent failure. Every variant shares a cell, so the
        # archive keeps a single elite and the diversity mechanism does
        # nothing while appearing to be configured.
        grid = Grid(
            descriptors=(Descriptor("source_lines", bins=(10_000.0,)),),
            strategy=GridStrategy.FIXED,
        )
        cells = assign_cells(_behaviours([1.0, 50.0, 900.0]), grid)
        assert len(set(cells)) == 1

    def test_a_categorical_axis_is_its_own_coordinate(self) -> None:
        grid = Grid(
            descriptors=(Descriptor("operator"),),
            strategy=GridStrategy.FIXED,
        )
        cells = assign_cells(
            [{"operator": "a"}, {"operator": "b"}, {"operator": "a"}], grid
        )
        assert cells[0] == cells[2] != cells[1]

    def test_a_missing_value_gets_its_own_coordinate(self) -> None:
        # "Did not report this" is a different behaviour from "reported
        # the smallest value"; merging them hides a class of variant.
        grid = Grid(
            descriptors=(Descriptor("metric:x", bins=(1.0,)),),
            strategy=GridStrategy.FIXED,
        )
        cells = assign_cells([{"metric:x": 0.5}, {}], grid)
        assert cells[0] != cells[1]


class TestAdaptive:
    def test_edges_come_from_the_observed_spread(self) -> None:
        # The same declared descriptor that collapsed under FIXED above
        # separates the population here, because the edges are derived.
        grid = Grid(
            descriptors=(Descriptor("source_lines", bins=(10_000.0,)),),
            strategy=GridStrategy.ADAPTIVE,
        )
        cells = assign_cells(_behaviours([1.0, 50.0, 900.0, 4000.0]), grid)
        assert len(set(cells)) > 1

    def test_a_constant_axis_collapses_rather_than_faking_bins(self) -> None:
        # An empty cell is not a niche nothing reached, it is one that
        # cannot be reached, and counting it overstates coverage.
        grid = Grid(
            descriptors=(Descriptor("source_lines", bins=(1.0, 2.0)),),
            strategy=GridStrategy.ADAPTIVE,
        )
        cells = assign_cells(_behaviours([7.0, 7.0, 7.0]), grid)
        assert len(set(cells)) == 1


class TestCvt:
    def test_cells_are_bounded_by_the_target_count(self) -> None:
        # The property no declared grid has: the archive cannot grow
        # past its budget however many variants arrive.
        grid = Grid(
            descriptors=(Descriptor("source_lines"),),
            strategy=GridStrategy.CVT,
            cells=4,
        )
        cells = assign_cells(_behaviours([float(i) for i in range(80)]), grid)
        assert len(set(cells)) <= 4

    def test_similar_variants_share_a_cell(self) -> None:
        grid = Grid(
            descriptors=(Descriptor("source_lines"),),
            strategy=GridStrategy.CVT,
            cells=2,
        )
        cells = assign_cells(_behaviours([1.0, 1.1, 90.0, 91.0]), grid)
        assert cells[0] == cells[1]
        assert cells[2] == cells[3]
        assert cells[0] != cells[2]

    def test_an_axis_with_a_huge_range_does_not_swamp_a_small_one(
        self,
    ) -> None:
        # Bytes beside nesting depth is the same cross-scale trap that
        # makes a weighted-sum objective meaningless; normalization is
        # what stops the larger unit deciding every cell.
        grid = Grid(
            descriptors=(
                Descriptor("source_bytes"),
                Descriptor("max_depth"),
            ),
            strategy=GridStrategy.CVT,
            cells=2,
        )
        behaviours = [
            {"source_bytes": 1000.0, "max_depth": 0.0},
            {"source_bytes": 1001.0, "max_depth": 9.0},
        ]
        assert len(set(assign_cells(behaviours, grid))) == 2

    def test_clustering_is_reproducible(self) -> None:
        # Selection is already stochastic; a grid that also moved
        # between two reads would make a regression unreproducible.
        grid = Grid(descriptors=(Descriptor("source_lines"),), cells=3)
        data = _behaviours([1.0, 2.0, 40.0, 41.0, 90.0])
        assert assign_cells(data, grid) == assign_cells(data, grid)

    def test_fewer_variants_than_cells_is_fine(self) -> None:
        grid = Grid(descriptors=(Descriptor("source_lines"),), cells=12)
        assert len(assign_cells(_behaviours([1.0]), grid)) == 1

    def test_the_default_cell_count_is_small(self) -> None:
        # An archive with more cells than variants has stopped
        # compressing anything.
        assert DEFAULT_CELLS <= 20


class TestCoverage:
    def test_everything_in_one_cell_is_no_coverage(self) -> None:
        assert coverage([(0,), (0,), (0,)]) == 0.0

    def test_an_even_spread_is_full_coverage(self) -> None:
        assert coverage([(0,), (1,), (2,)]) == pytest.approx(1.0)

    def test_a_lopsided_spread_scores_low_despite_many_cells(self) -> None:
        # The number that stops a high cell count reading as exploration:
        # forty variants in one cell and one in each of five others has
        # reached six cells and explored almost nothing.
        lopsided = [(0,)] * 40 + [(i,) for i in range(1, 6)]
        assert 0.0 < coverage(lopsided) < 0.5

    def test_no_variants_is_no_coverage(self) -> None:
        assert coverage([]) == 0.0

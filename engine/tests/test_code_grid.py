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
    UnbinnableFeatureError,
    assign_cells,
    coverage,
    extend,
    freeze,
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


class TestFreezing:
    def _population(self, count: int) -> list[dict[str, Any]]:
        return [{"source_lines": float(i)} for i in range(count)]

    def test_an_unfrozen_grid_can_move_a_variant(self) -> None:
        # The instability freezing removes: adding variants re-clusters,
        # so a cell is a snapshot rather than an identity.
        grid = Grid((Descriptor("source_lines"),), GridStrategy.CVT, cells=3)
        early = self._population(6)
        before = assign_cells(early, grid)
        after = assign_cells(early + self._population(30), grid)[: len(early)]
        assert before != after

    def test_freezing_pins_every_variant_already_placed(self) -> None:
        grid = Grid((Descriptor("source_lines"),), GridStrategy.CVT, cells=3)
        early = self._population(6)
        frozen = freeze(early, grid)
        before = assign_cells(early, frozen)
        after = assign_cells(early + self._population(30), frozen)[: len(early)]
        assert before == after

    def test_freezing_is_idempotent(self) -> None:
        grid = Grid((Descriptor("source_lines"),), GridStrategy.CVT, cells=3)
        once = freeze(self._population(6), grid)
        twice = freeze(self._population(40), once)
        assert once.projection == twice.projection

    def test_a_run_with_too_few_variants_does_not_freeze(self) -> None:
        # Freezing a one-point tessellation on the first generation
        # would leave the run with it forever.
        grid = Grid((Descriptor("source_lines"),), GridStrategy.CVT, cells=8)
        assert not freeze(self._population(3), grid).projection

    def test_a_non_clustering_strategy_never_freezes(self) -> None:
        grid = Grid(
            (Descriptor("source_lines", bins=(1.0,)),), GridStrategy.FIXED
        )
        assert not freeze(self._population(40), grid).projection

    def test_a_frozen_grid_still_places_new_variants(self) -> None:
        grid = Grid((Descriptor("source_lines"),), GridStrategy.CVT, cells=3)
        frozen = freeze(self._population(9), grid)
        cells = assign_cells(
            [*self._population(9), {"source_lines": 99.0}], frozen
        )
        assert len(cells) == 10
        assert len(set(cells)) <= 3


class TestVectorFeatures:
    def test_a_vector_feature_separates_under_clustering(self) -> None:
        grid = Grid((Descriptor("ast_shape"),), GridStrategy.CVT, cells=2)
        cells = assign_cells(
            [
                {"ast_shape": (1.0, 0.0)},
                {"ast_shape": (0.9, 0.1)},
                {"ast_shape": (0.0, 1.0)},
            ],
            grid,
        )
        assert cells[0] == cells[1] != cells[2]

    def test_a_vector_feature_is_refused_by_a_binning_strategy(self) -> None:
        # Silently dropping it would leave the run niching along fewer
        # axes than its author declared, with nothing to show for it.
        # Refused when the grid is built, not when a variant is binned:
        # both halves are known here, so deferring turns one bad
        # declaration into every variant of the run failing alike.
        with pytest.raises(UnbinnableFeatureError):
            Grid((Descriptor("ast_shape"),), GridStrategy.FIXED)

    def test_the_refusal_covers_the_adaptive_strategy_too(self) -> None:
        with pytest.raises(UnbinnableFeatureError):
            Grid((Descriptor("ast_shape"),), GridStrategy.ADAPTIVE)

    def test_a_variant_missing_the_vector_sits_apart(self) -> None:
        grid = Grid((Descriptor("ast_shape"),), GridStrategy.CVT, cells=2)
        cells = assign_cells(
            [{"ast_shape": (1.0, 1.0)}, {"ast_shape": (0.9, 1.0)}, {}], grid
        )
        assert cells[2] != cells[0]


class TestExtension:
    """Growing a frozen tessellation without moving what it placed.

    Freezing is what makes a cell a durable identity, and its cost is
    that behaviour appearing afterwards lands in whichever edge cell is
    nearest -- filed beside variants it has nothing in common with.
    Extension buys that back, and the property that makes it safe is
    that no existing centroid moves.
    """

    def _grid(self) -> Grid:
        early = [{"source_lines": float(i)} for i in range(12)]
        return freeze(early, Grid((Descriptor("source_lines"),), cells=4))

    def test_novel_behaviour_earns_a_cell_instead_of_the_nearest_edge(
        self,
    ) -> None:
        grid = self._grid()
        far = [{"source_lines": 4000.0}, {"source_lines": 4001.0}]
        before = assign_cells(far, grid)
        after = assign_cells(far, extend([*self._population(), *far], grid))
        assert before[0] != after[0]

    def test_nothing_already_placed_moves(self) -> None:
        # The whole point of freezing. An extension that re-clustered
        # would give back the instability it exists to remove.
        grid = self._grid()
        settled = list(self._population())
        before = assign_cells(settled, grid)
        grown = extend([*settled, {"source_lines": 9000.0}], grid)
        assert assign_cells(settled, grown) == before

    def test_existing_centroids_are_kept_verbatim(self) -> None:
        grid = self._grid()
        grown = extend([*self._population(), {"source_lines": 9000.0}], grid)
        assert (
            grown.projection.centroids[: len(grid.projection.centroids)]
            == grid.projection.centroids
        )

    def test_a_population_that_stayed_put_grows_nothing(self) -> None:
        grid = self._grid()
        assert extend(list(self._population()), grid) is grid

    def test_growth_stops_at_its_ceiling(self) -> None:
        # Unbounded growth is re-clustering by another name: an archive
        # with a cell per variant has stopped compressing anything.
        grid = self._grid()
        wandering = list(self._population())
        for _ in range(6):
            wandering += [
                {"source_lines": float(10 ** (i + 3))} for i in range(6)
            ]
            grid = extend(wandering, grid)
        assert len(grid.projection.centroids) <= grid.cells * 2

    def test_an_unfrozen_grid_is_left_alone(self) -> None:
        # There is nothing to preserve yet, and re-clustering is what an
        # unfrozen grid already does on every read.
        grid = Grid((Descriptor("source_lines"),), cells=4)
        assert extend([{"source_lines": 1.0}], grid) is grid

    def _population(self) -> list[dict[str, Any]]:
        return [{"source_lines": float(i)} for i in range(12)]


class TestColumnGrowth:
    """Minting a column for a category the frozen population never saw.

    Without one every unseen value reads zero in every column of its
    feature, so they all share one corner: "an operator this run had
    never used" is the same point as any other unfamiliar value. The
    property that makes minting safe is that appending a column is
    exactly distance-preserving.
    """

    def _frozen(self) -> Grid:
        seen = [
            {"operator": name, "max_depth": float(index)}
            for index, name in enumerate(["seed", "refine", "rewrite"] * 4)
        ]
        grid = Grid((Descriptor("operator"), Descriptor("max_depth")), cells=3)
        return freeze(seen, grid)

    def _population(self) -> list[dict[str, Any]]:
        return [
            {"operator": name, "max_depth": float(index)}
            for index, name in enumerate(["seed", "refine", "rewrite"] * 4)
        ]

    def test_an_unseen_category_gets_a_column(self) -> None:
        grid = self._frozen()
        novel = {"operator": "quantum_leap", "max_depth": 1.0}
        grown = extend([*self._population(), novel], grid)
        assert len(grown.projection.columns) > len(grid.projection.columns)
        assert any(
            column.category == "quantum_leap"
            for column in grown.projection.columns
        )

    def test_two_unseen_categories_stop_sharing_a_corner(self) -> None:
        # The failure minting removes: every unfamiliar value read as the
        # same point, so two genuinely different kinds shared a cell.
        grid = self._frozen()
        first = {"operator": "quantum_leap", "max_depth": 1.0}
        second = {"operator": "time_travel", "max_depth": 1.0}
        before = assign_cells([first, second], grid)
        grown = extend([*self._population(), first, second], grid)
        assert before[0] == before[1]
        assert (
            assign_cells([first, second], grown)[0]
            != assign_cells([first, second], grown)[1]
        )

    def test_every_existing_distance_is_unchanged(self) -> None:
        # Not "close enough": a column testing for a category a point is
        # not reads zero, and so does every padded centroid, so each new
        # coordinate adds exactly zero to every existing squared
        # distance. Asserted exactly, because approximately-preserved is
        # how a frozen grid starts drifting again.
        from co_scientist.agents.code_evolve.tessellation import (
            _distance,
            project,
        )

        grid = self._frozen()
        settled = self._population()
        novel = {"operator": "quantum_leap", "max_depth": 1.0}
        grown = extend([*settled, novel], grid)

        before = project(settled, grid.projection.columns)
        after = project(settled, grown.projection.columns)
        for point, moved in zip(before, after, strict=True):
            for old_centre, new_centre in zip(
                grid.projection.centroids,
                grown.projection.centroids,
                strict=False,
            ):
                assert _distance(point, old_centre) == _distance(
                    moved, new_centre
                )

    def test_nothing_already_placed_changes_cell(self) -> None:
        grid = self._frozen()
        settled = self._population()
        before = assign_cells(settled, grid)
        grown = extend(
            [*settled, {"operator": "quantum_leap", "max_depth": 1.0}], grid
        )
        assert assign_cells(settled, grown) == before

    def test_a_familiar_population_mints_nothing(self) -> None:
        grid = self._frozen()
        assert extend(self._population(), grid) is grid

"""``metric:*``: the one axis not read from a program's text.

Split from ``test_code_grid`` because it is a different kind of claim.
Every other descriptor is a reading of source, decided before anything
runs; these are decided by what the programs *did*, which is what lets
the archive separate two variants no static reading can tell apart.
"""

from __future__ import annotations

from typing import Any

from co_scientist.agents.code_evolve.grid import (
    METRIC_WILDCARD,
    Descriptor,
    Grid,
    assign_cells,
    extend,
    freeze,
)


class TestMetricWildcard:
    """``metric:*`` -- one axis per measurement the programs reported.

    The only descriptor that is not a reading of a program's text, and
    the only one whose keys are unknowable until something has run.
    """

    def _cells(
        self, descriptors: tuple[Descriptor, ...], behaviours: Any
    ) -> list[tuple[Any, ...]]:
        return assign_cells(behaviours, Grid(descriptors, cells=4))

    def test_it_separates_variants_that_only_a_metric_tells_apart(
        self,
    ) -> None:
        twins = [
            {"max_depth": 2.0, "metric:footprint": 1.0},
            {"max_depth": 2.0, "metric:footprint": 40.0},
        ]
        shape_only = self._cells((Descriptor("max_depth"),), twins)
        with_metric = self._cells(
            (Descriptor("max_depth"), Descriptor(METRIC_WILDCARD)), twins
        )
        assert shape_only[0] == shape_only[1]
        assert with_metric[0] != with_metric[1]

    def test_it_separates_programs_no_static_axis_can(self) -> None:
        """The limit of reading a program's text, and what closes it.

        These two are identical on *every* static axis -- same node
        multiset, so the same fingerprint at any width; same depth,
        imports, recursion and densities -- and they compute different
        things. No amount of widening separates them, because they do
        not differ in composition at all; only running them does.

        Note what is being pinned, and what is not. Two such programs
        reporting the *same* measurements genuinely belong in one cell:
        the archive keeps the best of each kind, and nothing has yet
        shown these to be different kinds. The claim is only that a
        difference the run can observe is one the archive can act on.
        """
        from co_scientist.agents.code_evolve.behaviour import describe

        first = "def solve():\n    a = 1\n    b = 2\n    return a - b\n"
        second = "def solve():\n    a = 2\n    b = 1\n    return a - b\n"
        static = (
            describe({"main.py": first}),
            describe({"main.py": second}),
        )
        assert static[0] == static[1]  # the premise, not an assumption

        measured = (
            describe({"main.py": first}, metrics={"residual": -1.0}),
            describe({"main.py": second}, metrics={"residual": 1.0}),
        )
        axes = (Descriptor("ast_shape"), Descriptor(METRIC_WILDCARD))
        cells = self._cells(axes, list(measured))
        assert cells[0] != cells[1]

    def test_an_objective_metric_is_excluded_from_expansion(self) -> None:
        # An objective's value *is* the variant's score, so niching on
        # it niches by progress -- the failure the module docstring
        # measures, arriving through the one axis nobody declared.
        refining = [
            {"max_depth": 2.0, "metric:score": float(level)}
            for level in range(8)
        ]
        cells = self._cells(
            (
                Descriptor("max_depth"),
                Descriptor(METRIC_WILDCARD, exclude=("score",)),
            ),
            refining,
        )
        assert len(set(cells)) == 1

    def test_it_costs_nothing_when_nothing_reports_a_metric(self) -> None:
        plain = [{"max_depth": 1.0}, {"max_depth": 9.0}]
        assert self._cells(
            (Descriptor("max_depth"), Descriptor(METRIC_WILDCARD)), plain
        ) == self._cells((Descriptor("max_depth"),), plain)

    def test_a_metric_appearing_later_earns_a_column(self) -> None:
        # A program that starts reporting something new has told the
        # archive a fact it could not otherwise represent.
        early = [
            {"max_depth": float(i), "metric:footprint": float(i)}
            for i in range(8)
        ]
        grid = freeze(
            early,
            Grid(
                (Descriptor("max_depth"), Descriptor(METRIC_WILDCARD)),
                cells=4,
            ),
        )
        assert grid.projection
        novel = {"max_depth": 2.0, "metric:footprint": 2.0, "metric:new": 5.0}
        grown = extend([*early, novel], grid)
        assert any(
            column.feature == "metric:new"
            for column in grown.projection.columns
        )
        # And every variant already placed is still where it was.
        assert assign_cells(early, grown) == assign_cells(early, grid)

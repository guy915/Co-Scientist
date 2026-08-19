"""The structural fingerprint: which algorithm, not which surface.

The pairs below are the point. Each is two programs a surface feature
reads as identical -- same imports, same nesting, same length class --
implementing the task a different way.
"""

from __future__ import annotations

import ast
import math
import re

import pytest

from co_scientist.agents.code_evolve.behaviour import describe
from co_scientist.agents.code_evolve.fingerprint import (
    SHAPE_BUCKETS,
    densities,
    recursion,
    shape,
)

_FOR = (
    "def solve(n):\n"
    "    total = 0\n"
    "    for i in range(n):\n"
    "        total += i * i\n"
    "    return total\n"
)
_WHILE = (
    "def solve(n):\n"
    "    total = 0\n"
    "    i = 0\n"
    "    while i < n:\n"
    "        total += i * i\n"
    "        i += 1\n"
    "    return total\n"
)
_COMPREHENSION = "def solve(n):\n    return sum(i * i for i in range(n))\n"
_RECURSIVE = (
    "def solve(n):\n"
    "    if n == 0:\n"
    "        return 0\n"
    "    return n * n + solve(n - 1)\n"
)


def _apart(left: str, right: str) -> float:
    return math.dist(shape({"main.py": left}), shape({"main.py": right}))


def _one(text: str) -> dict[str, str]:
    """One file, since these helpers all read whole programs."""
    return {"main.py": text}


class TestShape:
    def test_a_program_matches_itself_exactly(self) -> None:
        assert _apart(_FOR, _FOR) == 0.0

    def test_renaming_a_variable_barely_moves_a_program(self) -> None:
        # Niching by kind must survive cosmetic edits, or every rename
        # mints a new cell and the archive stops compressing.
        renamed = re.sub(r"\btotal\b", "acc", re.sub(r"\bi\b", "k", _FOR))
        assert ast.parse(renamed) is not None  # a real rename, not a typo
        assert _apart(_FOR, renamed) < 0.05

    def test_a_loop_and_a_recursion_are_far_apart(self) -> None:
        assert _apart(_FOR, _RECURSIVE) > 0.1

    def test_a_loop_and_a_comprehension_are_far_apart(self) -> None:
        assert _apart(_FOR, _COMPREHENSION) > 0.1

    def test_two_loop_kinds_are_distinguishable(self) -> None:
        # The case the surface features merged: same imports, same
        # depth, same operator, different algorithm.
        assert _apart(_FOR, _WHILE) > 0.0

    def test_a_generator_and_a_set_comprehension_are_not_one_point(
        self,
    ) -> None:
        # At eight buckets these were *exactly* equal: the grams that
        # separate them landed together, so the archive could not hold
        # both -- not occasionally, but for every run, forever. A
        # collision this cheap to hit is what decided the width; see
        # the table in the fingerprint module docstring.
        generator = "def f(n):\n    return sum(i for i in range(n))\n"
        set_comp = "def f(n):\n    return sum({i for i in range(n)})\n"
        assert _apart(generator, set_comp) > 0.0

    def test_the_profile_is_a_composition(self) -> None:
        # Fractions, not counts: a count grows as a variant is refined,
        # and an axis that grows with refinement degrades the archive.
        assert sum(shape(_one(_FOR))) == pytest.approx(1.0)

    def test_scaling_a_program_up_barely_moves_it(self) -> None:
        # Same algorithm, three times the body. A count-based profile
        # would place these far apart; a composition should not.
        bigger = _FOR.replace(
            "        total += i * i\n",
            "        total += i * i\n" * 3,
        )
        assert _apart(_FOR, bigger) < 0.1

    def test_an_empty_program_has_an_empty_profile(self) -> None:
        assert shape({}) == tuple(0.0 for _ in range(SHAPE_BUCKETS))

    def test_an_unparseable_program_still_gets_a_profile(self) -> None:
        rust = "fn main() { for i in 0..3 { go(i); } }"
        profile = shape(_one(rust))
        assert len(profile) == SHAPE_BUCKETS
        assert sum(profile) > 0

    def test_the_profile_is_stable_across_processes(self) -> None:
        # A randomized hash would give a different fingerprint in the
        # worker that evaluates and the one that selects.
        assert shape(_one(_FOR)) == shape(_one(_FOR))


class TestRecursion:
    def test_a_self_calling_function_is_recursive(self) -> None:
        assert recursion(_one(_RECURSIVE)) == "recursive"

    def test_a_loop_is_iterative(self) -> None:
        assert recursion(_one(_FOR)) == "iterative"

    def test_an_unparseable_program_is_neither(self) -> None:
        # Not "iterative": a program we could not read is a different
        # fact from one we read and found no recursion in.
        assert recursion(_one("fn main() {}")) == "unknown"


class TestDensities:
    def test_a_loop_and_a_comprehension_spend_syntax_differently(
        self,
    ) -> None:
        loop = densities(_one(_FOR))
        comp = densities(_one(_COMPREHENSION))
        assert loop["loop_density"] > 0 and comp["loop_density"] == 0
        assert comp["comprehension_density"] > 0

    def test_densities_are_absent_rather_than_zero_when_unreadable(
        self,
    ) -> None:
        # Zero is a real density; defaulting to it would file every
        # unparseable variant beside genuinely loop-free code.
        assert densities(_one("fn main() {}")) == {}


class TestThroughBehaviour:
    def test_describe_carries_the_fingerprint_and_recursion(self) -> None:
        behaviour = describe({"main.py": _RECURSIVE})
        assert behaviour["recursion"] == "recursive"
        assert len(behaviour["ast_shape"]) == SHAPE_BUCKETS

    def test_two_loop_kinds_differ_in_behaviour_but_not_on_the_surface(
        self,
    ) -> None:
        first = describe({"main.py": _FOR})
        second = describe({"main.py": _WHILE})
        assert first["max_depth"] == second["max_depth"]
        assert first["imports"] == second["imports"]
        assert first["ast_shape"] != second["ast_shape"]


class TestMultipleFiles:
    def test_a_data_file_does_not_erase_the_fingerprint(self) -> None:
        # Concatenating first and parsing once meant one non-Python file
        # made the whole program unreadable, and every structural
        # measurement silently fell back to the crude text path.
        code = {"main.py": _RECURSIVE}
        with_notes = {**code, "README.txt": "How this works.\n"}
        assert recursion(with_notes) == recursion(code) == "recursive"
        assert densities(with_notes)

    def test_recursion_in_any_file_counts(self) -> None:
        split = {"main.py": _FOR, "helper.py": _RECURSIVE}
        assert recursion(split) == "recursive"

    def test_a_program_with_no_readable_file_is_unknown(self) -> None:
        assert recursion({"a.txt": "notes", "b.md": "more"}) == "unknown"
        assert densities({"a.txt": "notes"}) == {}

    def test_file_order_cannot_change_the_fingerprint(self) -> None:
        first = shape({"a.py": _FOR, "b.py": _RECURSIVE})
        second = shape({"b.py": _RECURSIVE, "a.py": _FOR})
        assert first == second

"""Measuring what a program is, for the archive to niche it by.

The point of these features is to tell apart programs that size and
operator read as identical. So the tests that matter are the pairs: two
programs of similar length that are built differently must not produce
the same behaviour.
"""

from __future__ import annotations

from co_scientist.agents.code_evolve.behaviour import describe, is_categorical

_FLAT = (
    "import json\n"
    "values = [1, 2, 3]\n"
    "total = sum(values)\n"
    "json.dump({'score': total}, open('m.json', 'w'))\n"
)

_NESTED = (
    "import json\n"
    "total = 0\n"
    "for i in range(3):\n"
    "    for j in range(3):\n"
    "        if i < j:\n"
    "            total += 1\n"
    "json.dump({'score': total}, open('m.json', 'w'))\n"
)


class TestStructure:
    def test_nesting_separates_a_loop_nest_from_flat_code(self) -> None:
        # The limit this exists to close: both programs are about the
        # same length and could come from the same operator.
        flat = describe({"main.py": _FLAT})
        nested = describe({"main.py": _NESTED})
        assert nested["max_depth"] > flat["max_depth"]

    def test_branch_count_separates_them_too(self) -> None:
        assert (
            describe({"main.py": _NESTED})["branch_count"]
            > describe({"main.py": _FLAT})["branch_count"]
        )

    def test_dependencies_separate_two_approaches(self) -> None:
        # "Rewrote it with numpy" is a different approach from "tuned
        # the pure-Python loop", and every size-based axis reads them
        # as the same cell.
        pure = describe({"main.py": "total = sum(range(10))\n"})
        vectorized = describe(
            {"main.py": "import numpy as np\ntotal = np.arange(10).sum()\n"}
        )
        assert pure["imports"] != vectorized["imports"]
        assert vectorized["imports"] == "numpy"

    def test_dependency_order_cannot_split_a_cell(self) -> None:
        first = describe({"main.py": "import json\nimport os\n"})
        second = describe({"main.py": "import os\nimport json\n"})
        assert first["imports"] == second["imports"]

    def test_a_long_dependency_list_degrades_to_a_count(self) -> None:
        # Otherwise every marginally different dependency list mints a
        # niche nothing else can ever occupy.
        many = "\n".join(f"import mod{i}" for i in range(9))
        assert describe({"main.py": many})["imports"] == "9-deps"

    def test_a_program_with_no_imports_says_so(self) -> None:
        assert describe({"main.py": "x = 1\n"})["imports"] == "none"

    def test_call_diversity_counts_distinct_callees(self) -> None:
        behaviour = describe({"main.py": "f(1)\nf(2)\ng(3)\n"})
        assert behaviour["call_diversity"] == 2.0


class TestFallbacks:
    def test_unparseable_source_still_gets_a_depth(self) -> None:
        # A variant mid-repair, or a program in another language. Depth
        # falls back to indentation rather than reading as flat, which
        # would put it in the same cell as genuinely flat code.
        rust = "fn main() {\n    for i in 0..3 {\n        go(i);\n    }\n}\n"
        assert describe({"main.py": rust})["max_depth"] >= 2.0

    def test_an_empty_program_measures_zero_not_missing(self) -> None:
        behaviour = describe({})
        assert behaviour["source_bytes"] == 0.0
        assert behaviour["max_depth"] == 0.0

    def test_files_are_measured_together_in_a_stable_order(self) -> None:
        one = describe({"a.py": "x = 1\n", "b.py": "y = 2\n"})
        two = describe({"b.py": "y = 2\n", "a.py": "x = 1\n"})
        assert one == two


class TestProvenance:
    def test_the_seed_is_named_rather_than_left_blank(self) -> None:
        assert describe({"main.py": "x = 1\n"})["operator"] == "seed"

    def test_the_operator_is_carried_through(self) -> None:
        behaviour = describe({"main.py": "x = 1\n"}, operator="vectorize")
        assert behaviour["operator"] == "vectorize"

    def test_reported_metrics_become_axes(self) -> None:
        behaviour = describe({"main.py": "x = 1\n"}, metrics={"latency": 2.5})
        assert behaviour["metric:latency"] == 2.5

    def test_categorical_features_are_identified(self) -> None:
        assert is_categorical("operator")
        assert is_categorical("imports")
        assert not is_categorical("source_lines")

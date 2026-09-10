"""A run can force one generation strategy instead of deriving the mix.

``generation_strategy`` in a run's opts threads to the workflow state and
is honored by ``coordinator_strategy._determine_generation_counts`` in place
of the literature/tool-availability derivation, and validated upstream by
``run_setup._resolve_generation_strategy`` (which refuses a tools-requiring
label when tool-calling generation is off). Wired for
``evaluations.ablation_driver``'s fixed-strategy arm.
"""

from __future__ import annotations

from co_scientist.agents.generation.coordinator_strategy import (
    _determine_generation_counts,
    _forced_generation_strategy,
)
from co_scientist.generator.run_setup import _resolve_generation_strategy
from tests._state import make_state


def test_derivation_is_unchanged_when_no_strategy_is_forced() -> None:
    """With literature and tools, derivation still picks the tools mix."""
    counts = _determine_generation_counts(
        make_state(),
        total_count=4,
        has_literature=True,
        enable_tool_calling=True,
    )
    # lit_and_tools reserves an assumptions slice and splits the rest, so
    # both the tool-based and debate-with-lit paths get work.
    assert counts.tools_count > 0
    assert counts.debate_with_lit_count > 0


def test_forced_debate_only_overrides_the_derived_mix() -> None:
    """A forced no_lit routes everything to debate-only, tools=0.

    The inputs (has_literature and enable_tool_calling both True) would
    otherwise derive lit_and_tools; the override wins.
    """
    state = make_state(generation_strategy="no_lit")
    counts = _determine_generation_counts(
        state, total_count=4, has_literature=True, enable_tool_calling=True
    )
    assert counts.tools_count == 0
    assert counts.debate_with_lit_count == 0
    assert counts.debate_only_count > 0
    assert counts.is_degraded_mode is True


def test_unknown_forced_label_falls_back_to_derivation() -> None:
    """An unrecognized label derives rather than crashing the dispatch."""
    assert (
        _forced_generation_strategy(make_state(generation_strategy="bogus"))
        is None
    )
    counts = _determine_generation_counts(
        make_state(generation_strategy="bogus"),
        total_count=4,
        has_literature=False,
        enable_tool_calling=False,
    )
    assert counts.debate_only_count > 0


def test_resolver_refuses_tools_strategy_without_tool_calling() -> None:
    """A tools-requiring label is refused when tool-calling is off.

    lit_and_tools/dev_isolation route into the tool-based draft path, which
    has no tool loop without tool-calling generation, so the resolver
    degrades to deriving ("").
    """
    opts = {"generation_strategy": "lit_and_tools"}
    assert _resolve_generation_strategy(opts, False) == ""
    assert _resolve_generation_strategy(opts, True) == "lit_and_tools"


def test_resolver_allows_debate_strategy_without_tool_calling() -> None:
    """A debate strategy needs no tools, so it is honored regardless."""
    opts = {"generation_strategy": "no_lit"}
    assert _resolve_generation_strategy(opts, False) == "no_lit"


def test_resolver_ignores_absent_or_nonstring_strategy() -> None:
    assert _resolve_generation_strategy({}, True) == ""
    assert (
        _resolve_generation_strategy({"generation_strategy": None}, True) == ""
    )

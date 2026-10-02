"""Tests for the generation coordinator's strategy routing.

``generate_hypotheses`` selects among three generation strategies based on
state flags (literature availability, tool-calling, dev isolation) and
runs the chosen leaf strategies in parallel. These tests stub the leaf
strategies (``generate_with_tools``, ``generate_with_debate``, and
``generate_with_assumptions``) on the coordinator's module namespace --
so no LLM or MCP runs -- and assert the real routing, count-allocation,
and degraded-mode fallback logic. Result-assembly, the missing-guidance
precondition, and progress-event lifecycle tests live in the sibling
``test_coordinator_assembly.py``.
"""

import logging

import pytest

from co_scientist.agents.generation.coordinator import (
    generate_hypotheses,
)
from co_scientist.constants import LITERATURE_REVIEW_FAILED
from tests._generation_fakes import (
    _AssumptionsRecorder,
    _DebateRecorder,
    _install,
    _ToolsRecorder,
)
from tests._state import make_hypothesis, make_state


async def test_condition_a_splits_tools_debate_and_assumptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Literature + tool-calling reserves assumptions, then splits the rest.

    Of a batch of 4, one hypothesis is reserved for the iterative-assumptions
    technique and the remaining three are split between the tool-driven and
    debate-with-literature paths.
    """
    tools = _ToolsRecorder([make_hypothesis(text="t1")], llm_calls=3)
    debate = _DebateRecorder(
        [make_hypothesis(text="d1"), make_hypothesis(text="d2")],
        [{"hypothesis_text": "d1"}, {"hypothesis_text": "d2"}],
        llm_calls=9,
    )
    assumptions = _AssumptionsRecorder(
        [make_hypothesis(text="a1")], llm_calls=2
    )
    _install(monkeypatch, tools, debate, assumptions)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=4,
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    # 4 -> 1 assumptions + a 1/2 split of the remaining 3.
    assert assumptions.called and assumptions.count == 1
    assert tools.called and tools.count == 1
    assert debate.called and debate.count == 2
    # Both literature-aware paths receive the lit-review context, not None.
    assert debate.articles_with_reasoning == "some papers and reasoning"
    assert assumptions.articles_with_reasoning == "some papers and reasoning"
    # Assembly order: tools, then debate, then assumptions.
    # generate returns an AppendHypotheses op (children appended to the pool).
    texts = [h.text for h in result["hypotheses"].items]
    assert texts == ["t1", "d1", "d2", "a1"]
    assert result["hypothesis_count"] == 4
    assert len(result["debate_transcripts"]) == 2
    # Real LLM calls summed across every strategy that ran (finding L3).
    assert result["llm_call_count"] == 3 + 9 + 2


async def test_condition_a_single_count_collapses_to_tools_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With total_count=1, condition (a) allocates all to tools (no debate)."""
    tools = _ToolsRecorder([make_hypothesis(text="t1")])
    debate = _DebateRecorder([], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=1,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert tools.called and tools.count == 1
    # debate_with_lit_count collapses to 0, so debate is never invoked.
    assert not debate.called
    assert result["hypothesis_count"] == 1
    assert result["debate_transcripts"] == []


async def test_condition_c_debate_with_lit_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Literature present but tool-calling off routes all to debate-with-lit."""
    tools = _ToolsRecorder([make_hypothesis(text="should-not-appear")])
    debate = _DebateRecorder(
        [
            make_hypothesis(text="d1"),
            make_hypothesis(text="d2"),
            make_hypothesis(text="d3"),
        ],
        [{"hypothesis_text": "d1"}],
    )
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=3,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=False,
    )
    result = await generate_hypotheses(state)

    assert not tools.called
    assert debate.called and debate.count == 3
    assert debate.articles_with_reasoning == "papers"
    assert [h.text for h in result["hypotheses"].items] == ["d1", "d2", "d3"]
    assert result["hypothesis_count"] == 3
    assert "debate-with-literature" in result["message"]


async def test_condition_b_degraded_mode_applies_fallback_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No literature routes to debate-only with the fallback grounding note."""
    tools = _ToolsRecorder([])
    # Debate-only hypotheses arrive without literature_grounding.
    debate = _DebateRecorder(
        [
            make_hypothesis(text="d1", literature_grounding=None),
            make_hypothesis(text="d2", literature_grounding="stale"),
        ],
        [{"hypothesis_text": "d1"}, {"hypothesis_text": "d2"}],
    )
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=2,
        mcp_available=False,  # no MCP -> has_literature False -> degraded
        articles_with_reasoning="ignored because mcp unavailable",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert not tools.called
    assert debate.called and debate.count == 2
    # Debate-only path passes None for literature context.
    assert debate.articles_with_reasoning is None
    # Degraded-mode fallback overwrites grounding on every hypothesis.
    for hyp in result["hypotheses"].items:
        assert hyp.literature_grounding is not None
        assert hyp.literature_grounding.startswith(
            "No literature review available."
        )
    assert "debate-only" in result["message"]
    assert result["hypothesis_count"] == 2


async def test_condition_b_degraded_mode_logs_a_single_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The degraded case used to log a four-record decorative banner.

    ``"=" * 80`` above and below two message lines. A durable,
    user-visible log panel renders every WARNING record verbatim, so this
    collapses to exactly one record carrying the same information.
    """
    tools = _ToolsRecorder([])
    debate = _DebateRecorder([make_hypothesis(text="d1")], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=1,
        mcp_available=False,  # no MCP -> has_literature False -> degraded
        articles_with_reasoning=None,
        enable_tool_calling_generation=True,
    )
    with caplog.at_level(logging.WARNING):
        await generate_hypotheses(state)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "latent knowledge" in warnings[0].getMessage()


async def test_failed_lit_review_marker_is_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LITERATURE_REVIEW_FAILED sentinel is treated as no literature."""
    tools = _ToolsRecorder([])
    debate = _DebateRecorder([make_hypothesis(text="d1")], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=1,
        mcp_available=True,
        articles_with_reasoning=LITERATURE_REVIEW_FAILED,
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    # Sentinel -> has_literature False -> degraded debate-only path.
    assert not tools.called
    assert debate.called and debate.articles_with_reasoning is None
    assert result["hypothesis_count"] == 1


async def test_no_lit_path_invokes_assumptions_technique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LLM-only path uses the iterative-assumptions technique too (SSR §4).

    With enough hypotheses to split, a no-literature run reserves a slice for
    the assumptions technique, so a hypothesis flowing through a real run
    actually carries ``GenerationMethod.ASSUMPTIONS`` (not just registered).
    """
    from co_scientist.models import GenerationMethod
    from tests._llm_fake import install_fake_llm

    install_fake_llm(monkeypatch)
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,  # >= 4 -> reserve a slice for assumptions
        mcp_available=False,  # no literature -> the no_lit path
        enable_tool_calling_generation=True,
        model_name="fake-model",
    )

    result = await generate_hypotheses(state)

    methods = {h.generation_method for h in result["hypotheses"].items}
    assert GenerationMethod.ASSUMPTIONS in methods
    assert GenerationMethod.DEBATE in methods  # debate still runs the rest


async def test_lit_and_tools_reserves_assumptions_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Literature + tool-calling reserves a slice for assumptions (E07).

    Assumptions is a first-class SSR §4 technique, not a degraded-mode-only
    fallback: with enough hypotheses to split, the literature-and-tools
    strategy runs assumptions alongside tools and debate, and passes the
    live literature context (articles + reference index) through so the
    assumptions prompt can ground its claims in real citations.
    """
    tools = _ToolsRecorder([make_hypothesis(text="t1")])
    debate = _DebateRecorder([make_hypothesis(text="d1")], [])
    assumptions = _AssumptionsRecorder([make_hypothesis(text="a1")])
    _install(monkeypatch, tools, debate, assumptions)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,  # >= 4 -> reserve a slice for assumptions
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert assumptions.called and assumptions.count is not None
    assert assumptions.count > 0
    # The remaining count is split between tools and debate.
    assert tools.called and debate.called
    assert (assumptions.count or 0) + (tools.count or 0) + (
        debate.count or 0
    ) == 8
    # Literature context reaches the assumptions technique in lit mode.
    assert assumptions.articles_with_reasoning == "some papers and reasoning"
    assert assumptions.reference_index is not None
    assert "a1" in [h.text for h in result["hypotheses"].items]


async def test_lit_only_reserves_assumptions_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Literature without tool-calling still reserves an assumptions slice."""
    tools = _ToolsRecorder([])
    debate = _DebateRecorder([make_hypothesis(text="d1")], [])
    assumptions = _AssumptionsRecorder([make_hypothesis(text="a1")])
    _install(monkeypatch, tools, debate, assumptions)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=False,
    )
    result = await generate_hypotheses(state)

    assert not tools.called
    assert assumptions.called and (assumptions.count or 0) > 0
    assert (assumptions.count or 0) + (debate.count or 0) == 8
    assert assumptions.articles_with_reasoning == "papers"
    assert assumptions.reference_index is not None
    assert "a1" in [h.text for h in result["hypotheses"].items]


async def test_dev_isolation_routes_all_to_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev isolation mode sends every hypothesis to tools, skipping debate."""
    tools = _ToolsRecorder(
        [
            make_hypothesis(text="t1"),
            make_hypothesis(text="t2"),
            make_hypothesis(text="t3"),
        ]
    )
    debate = _DebateRecorder([], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=3,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=True,
        dev_test_lit_tools_isolation=True,
    )
    result = await generate_hypotheses(state)

    assert tools.called and tools.count == 3
    assert not debate.called
    assert result["hypothesis_count"] == 3
    assert "3 tool-based" in result["message"]

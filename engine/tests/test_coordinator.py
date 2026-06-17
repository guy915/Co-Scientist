"""Tests for the generation coordinator's strategy routing and assembly.

``generate_hypotheses`` selects among three generation strategies based on
state flags (literature availability, tool-calling, dev isolation), runs the
chosen leaf strategies in parallel, and assembles their outputs into a single
result dict. These tests stub the two leaf strategies
(``generate_with_tools`` and ``generate_with_debate``) on the coordinator's
module namespace -- so no LLM or MCP runs -- and assert the real routing,
count-allocation, degraded-mode fallback, and result-assembly logic.
"""

from typing import Any

import pytest

from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.exceptions import GenerationError
from co_scientist.models import Hypothesis
from co_scientist.nodes.generation import coordinator
from co_scientist.nodes.generation.coordinator import generate_hypotheses
from tests._state import make_hypothesis, make_state


class _ToolsRecorder:
    """Records calls to the stubbed ``generate_with_tools`` leaf strategy.

    The coordinator assigns this strategy's return value directly, so the stub
    returns a plain ``list[Hypothesis]``.
    """

    def __init__(self, hypotheses: list[Hypothesis]) -> None:
        self._hypotheses = hypotheses
        self.called = False
        self.count: int | None = None

    async def __call__(self, _state: Any, count: int,
                       _reference_index: Any) -> list[Hypothesis]:
        self.called = True
        self.count = count
        return list(self._hypotheses)


class _DebateRecorder:
    """Records calls to the stubbed ``generate_with_debate`` leaf strategy.

    The coordinator unpacks this strategy's return as a 2-tuple, so the stub
    returns ``(list[Hypothesis], list[transcript])``. ``generate_with_debate``
    is invoked with keyword arguments by the coordinator.
    """

    def __init__(self, hypotheses: list[Hypothesis],
                 transcripts: list[dict[str, Any]]) -> None:
        self._hypotheses = hypotheses
        self._transcripts = transcripts
        self.called = False
        self.count: int | None = None
        self.articles_with_reasoning: str | None = None

    async def __call__(
        self,
        *,
        state: Any,
        count: int,
        articles_with_reasoning: str | None = None,
        reference_index: Any = None,
    ) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
        self.called = True
        self.count = count
        self.articles_with_reasoning = articles_with_reasoning
        return list(self._hypotheses), list(self._transcripts)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    tools: _ToolsRecorder,
    debate: _DebateRecorder,
) -> None:
    """Patch both leaf strategies on the coordinator's namespace."""
    monkeypatch.setattr(coordinator, "generate_with_tools", tools)
    monkeypatch.setattr(coordinator, "generate_with_debate", debate)


async def test_missing_supervisor_guidance_raises() -> None:
    """Falsy supervisor_guidance raises GenerationError before any strategy."""
    # make_state() defaults supervisor_guidance to {} (falsy).
    with pytest.raises(GenerationError):
        await generate_hypotheses(make_state())


async def test_condition_a_splits_tools_and_debate(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Literature + tool-calling routes 50/50 to tools and debate-with-lit."""
    tools = _ToolsRecorder([make_hypothesis(text="t1"),
                            make_hypothesis(text="t2")])
    debate = _DebateRecorder(
        [make_hypothesis(text="d1"), make_hypothesis(text="d2")],
        [{"hypothesis_text": "d1"}, {"hypothesis_text": "d2"}],
    )
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=4,
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    # 50/50 split of 4 -> 2 tools + 2 debate-with-lit.
    assert tools.called and tools.count == 2
    assert debate.called and debate.count == 2
    # Debate-with-literature receives the lit-review context, not None.
    assert debate.articles_with_reasoning == "some papers and reasoning"
    # Assembly: tools first, then debate; count reflects returned lengths.
    assert [h.text for h in result["hypotheses"]] == ["t1", "t2", "d1", "d2"]
    assert result["hypothesis_count"] == 4
    assert len(result["debate_transcripts"]) == 2


async def test_condition_a_single_count_collapses_to_tools_only(
        monkeypatch: pytest.MonkeyPatch) -> None:
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
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Literature present but tool-calling off routes 100% to debate-with-lit."""
    tools = _ToolsRecorder([make_hypothesis(text="should-not-appear")])
    debate = _DebateRecorder(
        [make_hypothesis(text="d1"), make_hypothesis(text="d2"),
         make_hypothesis(text="d3")],
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
    assert [h.text for h in result["hypotheses"]] == ["d1", "d2", "d3"]
    assert result["hypothesis_count"] == 3
    assert "debate-with-literature" in result["message"]


async def test_condition_b_degraded_mode_applies_fallback_grounding(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """No literature routes to debate-only with the fallback grounding note."""
    tools = _ToolsRecorder([])
    # Debate-only hypotheses arrive without literature_grounding.
    debate = _DebateRecorder(
        [make_hypothesis(text="d1", literature_grounding=None),
         make_hypothesis(text="d2", literature_grounding="stale")],
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
    for hyp in result["hypotheses"]:
        assert hyp.literature_grounding is not None
        assert hyp.literature_grounding.startswith(
            "No literature review available.")
    assert "debate-only" in result["message"]
    assert result["hypothesis_count"] == 2


async def test_failed_lit_review_marker_is_degraded(
        monkeypatch: pytest.MonkeyPatch) -> None:
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


async def test_dev_isolation_routes_all_to_tools(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev isolation mode sends every hypothesis to tools, skipping debate."""
    tools = _ToolsRecorder([make_hypothesis(text="t1"),
                            make_hypothesis(text="t2"),
                            make_hypothesis(text="t3")])
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


async def test_result_dict_shape_and_message_format(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The result dict carries the expected keys and 'Generated N ...' message."""
    tools = _ToolsRecorder([make_hypothesis(text="t1")])
    debate = _DebateRecorder([make_hypothesis(text="d1")],
                             [{"hypothesis_text": "d1"}])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=2,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert set(result.keys()) == {
        "hypotheses",
        "debate_transcripts",
        "hypothesis_count",
        "message",
    }
    assert result["message"] == (
        "Generated 2 hypotheses (1 tool-based, 1 debate-with-literature)")


async def test_progress_callback_emits_start_and_complete(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A progress_callback receives start and complete generation events."""
    tools = _ToolsRecorder([])
    debate = _DebateRecorder([make_hypothesis(text="d1")],
                             [{"hypothesis_text": "d1"}])
    _install(monkeypatch, tools, debate)

    events: list[tuple[str, dict[str, Any]]] = []

    async def callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=1,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=False,
        progress_callback=callback,
    )
    await generate_hypotheses(state)

    emitted = [name for name, _ in events]
    assert emitted == ["generation_start", "generation_complete"]
    assert events[1][1]["hypotheses_count"] == 1

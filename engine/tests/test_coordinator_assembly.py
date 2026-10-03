"""Tests for the generation coordinator's result assembly and lifecycle.

Where ``test_coordinator.py`` asserts *which* strategy condition routes to
which leaf, this file asserts what ``generate_hypotheses`` does once a
strategy has run: the precondition it enforces before touching any
strategy, the shape and message format of the dict it returns, how a
later Supervisor cycle discloses a hypothesis as research expansion, and
the start/complete progress events it emits around the call. These tests
stub the same three leaf strategies (``generate_with_tools``,
``generate_with_debate``, ``generate_with_assumptions``) on the
coordinator's module namespace as the sibling file, so no LLM or MCP
runs.
"""

from typing import Any

import pytest

from co_scientist.agents.generation.generate import (
    generate_hypotheses,
)
from co_scientist.exceptions import GenerationError
from co_scientist.models import GenerationMethod
from tests._generation_fakes import _DebateRecorder, _install, _ToolsRecorder
from tests._state import make_hypothesis, make_state


async def test_missing_supervisor_guidance_raises() -> None:
    """Falsy supervisor_guidance raises GenerationError before any strategy."""
    # make_state() defaults supervisor_guidance to {} (falsy).
    with pytest.raises(GenerationError):
        await generate_hypotheses(make_state())


async def test_result_dict_shape_and_message_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The result dict carries expected keys and 'Generated N ...' message."""
    tools = _ToolsRecorder([make_hypothesis(text="t1")])
    debate = _DebateRecorder(
        [make_hypothesis(text="d1")], [{"hypothesis_text": "d1"}]
    )
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
        "llm_call_count",
        "message",
    }
    assert result["message"] == (
        "Generated 2 hypotheses (1 tool-based, 1 debate-with-literature)"
    )


async def test_later_generation_is_disclosed_as_research_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Later Supervisor cycles expose research expansion and base provenance."""
    tools = _ToolsRecorder([])
    hypothesis = make_hypothesis(text="underexplored branch")
    hypothesis.generation_method = GenerationMethod.DEBATE
    debate = _DebateRecorder([hypothesis], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "seek an underexplored branch"},
        initial_hypotheses_count=1,
        current_iteration=2,
        mcp_available=False,
        enable_tool_calling_generation=False,
    )
    result = await generate_hypotheses(state)

    expanded = result["hypotheses"].items[0]
    assert expanded.creation_iteration == 2
    assert expanded.generation_method == GenerationMethod.RESEARCH_EXPANSION
    assert expanded.enrichments["base_generation_method"] == "debate"


async def test_progress_callback_emits_start_and_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A progress_callback receives start and complete generation events."""
    tools = _ToolsRecorder([])
    debate = _DebateRecorder(
        [make_hypothesis(text="d1")], [{"hypothesis_text": "d1"}]
    )
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

"""Tests for the generation coordinator's summary logging.

``_log_generation_summary`` prints one INFO line per generation call: a total
plus a parenthesised per-strategy breakdown. The total counts every bucket
that feeds ``GenerationResults.all_hypotheses``, so the breakdown has to name
every one of them too -- otherwise a run allocating an assumptions slice logs
parts that do not sum to the total beside them. These tests drive the real
``generate_hypotheses`` path with stubbed leaf strategies and read the
rendered log record back.
"""

import logging
import re
from typing import Any

import pytest

from co_scientist.agents.generation import generate as coordinator
from co_scientist.agents.generation.generate import generate_hypotheses
from tests._state import make_hypothesis, make_state

_SUMMARY_RE = re.compile(r"Generated (\d+) total hypotheses \(([^)]*)\)")


def _stub_leaf_strategies(
    monkeypatch: pytest.MonkeyPatch,
    tools: list[str],
    debate: list[str],
    assumptions: list[str],
) -> None:
    """Patch the three leaf strategies to return fixed hypothesis texts."""

    async def fake_tools(*_args: Any, **_kwargs: Any) -> Any:
        return [make_hypothesis(text=t) for t in tools], 0

    async def fake_debate(*_args: Any, **_kwargs: Any) -> Any:
        return ([make_hypothesis(text=t) for t in debate], [], 0)

    async def fake_assumptions(*_args: Any, **_kwargs: Any) -> Any:
        return [make_hypothesis(text=t) for t in assumptions], 0

    monkeypatch.setattr(coordinator, "generate_with_tools", fake_tools)
    monkeypatch.setattr(coordinator, "generate_with_debate", fake_debate)
    monkeypatch.setattr(
        coordinator, "generate_with_assumptions", fake_assumptions
    )


def _summary_record(caplog: pytest.LogCaptureFixture) -> str:
    """Return the single rendered generation-summary log message."""
    messages = [
        record.getMessage()
        for record in caplog.records
        if _SUMMARY_RE.search(record.getMessage())
    ]
    assert len(messages) == 1, messages
    return messages[0]


def _parse_summary(message: str) -> tuple[int, list[int]]:
    """Split a summary line into its total and its breakdown numbers."""
    match = _SUMMARY_RE.search(message)
    assert match is not None, message
    total = int(match.group(1))
    parts = [int(n) for n in re.findall(r"\d+", match.group(2))]
    return total, parts


async def test_summary_breakdown_sums_to_total_with_assumptions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The breakdown accounts for the assumptions slice, not just the total.

    A batch of 8 under condition (a) allocates 2 to the iterative-assumptions
    technique, so a breakdown naming only tools/debate-with-lit/debate-only
    falls short of the total printed beside it.
    """
    _stub_leaf_strategies(
        monkeypatch,
        tools=["t1", "t2", "t3"],
        debate=["d1", "d2", "d3"],
        assumptions=["a1", "a2"],
    )
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,  # >= 4 -> a nonzero assumptions slice
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )

    with caplog.at_level(logging.INFO):
        result = await generate_hypotheses(state)

    # The fixture must actually exercise the assumptions bucket, or the
    # sum below holds whether or not the breakdown names it.
    assert result["hypothesis_count"] == 8
    total, parts = _parse_summary(_summary_record(caplog))
    assert total == 8
    assert sum(parts) == total


async def test_summary_breakdown_sums_to_total_without_assumptions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A batch too small to split (< 4) still balances, with a zero slice."""
    _stub_leaf_strategies(
        monkeypatch, tools=["t1"], debate=["d1", "d2"], assumptions=[]
    )
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=3,
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )

    with caplog.at_level(logging.INFO):
        await generate_hypotheses(state)

    total, parts = _parse_summary(_summary_record(caplog))
    assert total == 3
    assert sum(parts) == total


async def test_assumptions_bucket_methods_are_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Every populated bucket gets a generation_methods debug line."""
    _stub_leaf_strategies(
        monkeypatch,
        tools=["t1", "t2", "t3"],
        debate=["d1", "d2", "d3"],
        assumptions=["a1", "a2"],
    )
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )

    with caplog.at_level(logging.DEBUG):
        await generate_hypotheses(state)

    labels = {
        record.getMessage().split(" generation_methods:")[0]
        for record in caplog.records
        if " generation_methods:" in record.getMessage()
    }
    assert labels == {"tool-based", "debate-with-Lit", "assumptions"}

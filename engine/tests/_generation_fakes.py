"""Recording leaf strategies for coordinator behavior tests."""

from typing import Any

import pytest

from co_scientist.agents.generation import generate as coordinator
from co_scientist.models import Hypothesis


class _ToolsRecorder:
    """Records calls to the stubbed ``generate_with_tools`` leaf strategy."""

    def __init__(
        self, hypotheses: list[Hypothesis], llm_calls: int = 0
    ) -> None:
        self._hypotheses = hypotheses
        self.llm_calls = llm_calls
        self.called = False
        self.count: int | None = None

    async def __call__(
        self, _state: Any, count: int, _reference_index: Any
    ) -> tuple[list[Hypothesis], int]:
        self.called = True
        self.count = count
        return list(self._hypotheses), self.llm_calls


class _DebateRecorder:
    """Records calls to the stubbed ``generate_with_debate`` leaf strategy."""

    def __init__(
        self,
        hypotheses: list[Hypothesis],
        transcripts: list[dict[str, Any]],
        llm_calls: int = 0,
    ) -> None:
        self._hypotheses = hypotheses
        self._transcripts = transcripts
        self.llm_calls = llm_calls
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
    ) -> tuple[list[Hypothesis], list[dict[str, Any]], int]:
        self.called = True
        self.count = count
        self.articles_with_reasoning = articles_with_reasoning
        return list(self._hypotheses), list(self._transcripts), self.llm_calls


class _AssumptionsRecorder:
    """Records calls to the stubbed ``generate_with_assumptions`` leaf."""

    def __init__(
        self, hypotheses: list[Hypothesis], llm_calls: int = 0
    ) -> None:
        self._hypotheses = hypotheses
        self.llm_calls = llm_calls
        self.called = False
        self.count: int | None = None
        self.articles_with_reasoning: str | None = None
        self.reference_index: Any = None

    async def __call__(
        self,
        _state: Any,
        count: int,
        articles_with_reasoning: str | None = None,
        reference_index: Any = None,
    ) -> tuple[list[Hypothesis], int]:
        self.called = True
        self.count = count
        self.articles_with_reasoning = articles_with_reasoning
        self.reference_index = reference_index
        return list(self._hypotheses), self.llm_calls


def _install(
    monkeypatch: pytest.MonkeyPatch,
    tools: _ToolsRecorder,
    debate: _DebateRecorder,
    assumptions: _AssumptionsRecorder | None = None,
) -> None:
    """Patch the leaf strategies on the coordinator's namespace."""
    monkeypatch.setattr(coordinator, "generate_with_tools", tools)
    monkeypatch.setattr(coordinator, "generate_with_debate", debate)
    monkeypatch.setattr(
        coordinator,
        "generate_with_assumptions",
        assumptions or _AssumptionsRecorder([]),
    )

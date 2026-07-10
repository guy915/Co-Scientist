"""Tests for literature review phase 4 synthesis (synthesis.py).

Covers the two failure paths ``_phase4_synthesize`` degrades to the
``LITERATURE_REVIEW_FAILED`` sentinel on: no paper analyses to synthesize
from, and the synthesis LLM call raising. The happy path is already
exercised end-to-end via ``test_literature_review_node``.
"""

from typing import Any

import pytest

from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.nodes.literature_review import synthesis
from tests._state import make_state


async def test_phase4_synthesize_no_analyses_returns_failure_sentinel() -> None:
    """An empty analyses list returns the sentinel without calling the LLM."""
    state = make_state(research_goal="goal")

    result = await synthesis._phase4_synthesize([], state)

    assert result == LITERATURE_REVIEW_FAILED


async def test_phase4_synthesize_llm_failure_returns_failure_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synthesis LLM call that raises degrades to the failure sentinel."""

    async def _raise(**_: Any) -> str:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(synthesis, "call_llm", _raise)
    state = make_state(research_goal="goal")

    result = await synthesis._phase4_synthesize(
        [{"paper_id": "P1", "analysis": "text"}], state
    )

    assert result == LITERATURE_REVIEW_FAILED

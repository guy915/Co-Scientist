"""Tests for literature review phase 4 synthesis (synthesis.py).

``_phase4_synthesize`` degrades in two different ways depending on whether
Phase 3 produced anything: with no paper analyses at all it returns the
``LITERATURE_REVIEW_FAILED`` sentinel (there is nothing to build even a
fallback from); with a non-empty ``paper_analyses`` list it never discards
those analyses just because the synthesis LLM call itself failed -- it
rolls them up deterministically instead, since retrieval already spent the
real LLM calls that produced them. The happy (LLM-succeeds) path is already
exercised end-to-end via ``test_literature_review_node``.
"""

from typing import Any

import pytest

from co_scientist.agents.generation.literature_review import synthesis
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS,
)
from tests._state import make_state


async def test_phase4_synthesize_no_analyses_returns_failure_sentinel() -> None:
    """An empty analyses list returns the sentinel without calling the LLM."""
    state = make_state(research_goal="goal")

    result = await synthesis._phase4_synthesize([], state)

    assert result == LITERATURE_REVIEW_FAILED


async def test_phase4_synthesize_llm_failure_with_analyses_degrades_to_rollup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synthesis LLM failure must not discard successfully-retrieved papers.

    Losing the synthesis *prose* should not delete the *retrieval* -- the
    per-paper analyses cost real LLM calls to produce, so a failed synthesis
    call degrades to a deterministic roll-up of them rather than the
    failure sentinel.
    """

    async def _raise(**_: Any) -> str:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(synthesis, "call_llm", _raise)
    state = make_state(research_goal="goal")
    paper_analyses = [
        {
            "paper_id": "P1",
            "metadata": {"title": "A paper about X"},
            "analysis": {
                "key_findings": "X causes Y under condition Z.",
                "gaps_identified": "Mechanism of Y is unclear.",
                "unexplored_areas": "Nobody has tried blocking pathway W.",
            },
        }
    ]

    result = await synthesis._phase4_synthesize(paper_analyses, state)

    assert result != LITERATURE_REVIEW_FAILED
    # Honest about what it is: a mechanical roll-up, not a synthesis.
    assert "not an LLM synthesis" in result
    # The retrieved content actually survives into the fallback text --
    # gaps_identified and unexplored_areas are both hypothesis-generative
    # (what's missing, what nobody has tried), so both must survive.
    assert "A paper about X" in result
    assert "X causes Y under condition Z." in result
    assert "Mechanism of Y is unclear." in result
    assert "Nobody has tried blocking pathway W." in result


async def test_phase4_synthesize_fallback_rollup_is_length_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A huge pool of analyses must not blow a downstream prompt's budget.

    Also the crowded case for the per-paper allowance: with 50 papers each
    carrying long text in all three signal fields, the cap is spent
    thinly across papers instead of the first few consuming it all --
    so a paper well past where an unbounded roll-up would have run out
    (5-6 papers' worth of untruncated text exhausts 8000 chars) still
    gets a representation, with all three of its signals present.
    """

    async def _raise(**_: Any) -> str:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(synthesis, "call_llm", _raise)
    state = make_state(research_goal="goal")
    paper_analyses = [
        {
            "paper_id": f"P{i}",
            "metadata": {"title": f"Paper number {i}"},
            "analysis": {
                "key_findings": "Finding text. " * 50,
                "gaps_identified": "Gap text. " * 50,
                "unexplored_areas": "Unexplored text. " * 50,
            },
        }
        for i in range(50)
    ]

    result = await synthesis._phase4_synthesize(paper_analyses, state)

    # truncate() may append a short "..." suffix past the raw cap; the
    # bound that matters is "close to the cap", not "byte-exact".
    assert len(result) <= LITERATURE_SYNTHESIS_FALLBACK_MAX_CHARS + 10
    # A paper far past what an unbounded roll-up could ever have reached
    # still made it in, with all three of its signals represented.
    assert "Paper number 20" in result
    assert "Finding text." in result
    assert "Gap text." in result
    assert "Unexplored text." in result


async def test_phase4_synthesize_no_analyses_never_reaches_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The empty-analyses branch never reaches the LLM call at all."""

    async def _raise(**_: Any) -> str:
        raise AssertionError("must not be called with no analyses")

    monkeypatch.setattr(synthesis, "call_llm", _raise)
    state = make_state(research_goal="goal")

    result = await synthesis._phase4_synthesize([], state)

    assert result == LITERATURE_REVIEW_FAILED

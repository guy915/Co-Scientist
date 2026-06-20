"""Tests for the research-overview node.

The terminal node synthesizes the top-k hypotheses by Elo into a research
overview and an NIH Specific Aims page. These tests monkeypatch
``call_llm_json`` on the node module so no LLM or network calls are made, and
assert that the parsed overview and aims are returned in the state delta.
"""

from unittest.mock import AsyncMock

import pytest

from co_scientist.nodes import research_overview as ro
from tests._state import make_hypothesis, make_state


async def test_produces_overview_and_aims(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The node returns the overview and NIH Specific Aims from the LLM."""
    fake = AsyncMock(
        return_value={
            "overview": {
                "summary":
                    "S",
                "research_directions": [{
                    "title": "T",
                    "importance": "I",
                    "suggested_experiments": ["E"],
                }],
            },
            "nih_specific_aims": {
                "introduction": "intro",
                "aims": [{
                    "aim": "A",
                    "rationale": "R",
                    "approach": "Ap",
                }],
                "impact": "imp",
            },
        })
    monkeypatch.setattr(ro, "call_llm_json", fake)

    h = make_hypothesis(text="HDAC inhibition reverses fibrosis",
                        elo_rating=1700)
    state = make_state(hypotheses=[h],
                       research_goal="g",
                       supervisor_model_name="test/model",
                       meta_review={})
    out = await ro.research_overview_node(state)

    assert out["research_overview"]["overview"]["summary"] == "S"
    assert out["research_overview"]["nih_specific_aims"]["aims"][0][
        "aim"] == "A"
    assert fake.await_count == 1

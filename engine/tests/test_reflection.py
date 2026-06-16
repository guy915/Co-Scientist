# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for reflection_node: per-hypothesis literature analysis.

The node's only LLM dependency is ``call_llm_json``, which returns a
classification/reasoning dict per hypothesis; these tests stub that out and
assert on the reflection metadata written back onto each Hypothesis and the
returned state update. The INDRA/MCP enrichment path is left real: with the
default state's ``tool_registry=None`` it short-circuits to a network-free
no-op, which is exactly the LLM-only path under test.
"""

from typing import Any

import pytest

from co_scientist.nodes import reflection
from co_scientist.nodes.reflection import reflection_node
from tests._state import make_hypothesis, make_state

# Literature context that satisfies the node's ``articles_with_reasoning``
# guard so reflection actually runs (an empty/None value short-circuits the
# whole node).
_ARTICLES = "Article 1: observation A supports pathway X."


def _stub_llm(monkeypatch: pytest.MonkeyPatch, response: dict[str,
                                                              Any]) -> None:
    """Patch reflection's call_llm_json to return a fixed analysis response.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        response: The dict the stubbed LLM should return for every call.
    """

    async def fake(**_: Any) -> dict[str, Any]:
        return response

    monkeypatch.setattr(reflection, "call_llm_json", fake)


async def test_empty_hypotheses_returns_empty() -> None:
    """With articles present but no hypotheses, the node returns cleanly.

    The articles guard is satisfied so the hypotheses guard is the one that
    fires; the node returns an empty dict and never calls the LLM.
    """
    state = make_state(hypotheses=[], articles_with_reasoning=_ARTICLES)
    result = await reflection_node(state)
    assert result == {}


async def test_missing_articles_skips_node() -> None:
    """Without articles_with_reasoning the node short-circuits to an empty dict.

    The default state leaves ``articles_with_reasoning`` as None, so reflection
    is skipped even when hypotheses are present.
    """
    state = make_state(hypotheses=[make_hypothesis(text="a hypothesis")])
    result = await reflection_node(state)
    assert result == {}


async def test_hypotheses_get_reflection_notes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Each hypothesis gets reflection_notes built from the LLM response.

    The note interleaves the ``reasoning`` and ``classification`` keys read by
    ``analyze_single_hypothesis``; with no tool_registry the INDRA enrichment
    stays empty, so the ``indra_evidence`` key is never written.
    """
    hyp_a = make_hypothesis(text="alpha pathway drives growth")
    hyp_b = make_hypothesis(text="beta pathway drives growth")
    state = make_state(hypotheses=[hyp_a, hyp_b],
                       articles_with_reasoning=_ARTICLES)
    _stub_llm(monkeypatch, {
        "classification": "missing piece",
        "reasoning": "fills a gap",
    })

    result = await reflection_node(state)

    returned = result["hypotheses"]
    assert len(returned) == 2
    for hyp in returned:
        assert hyp.reflection_notes == "fills a gap\n\nClassification: missing piece"
        # LLM-only path: no INDRA enrichment was fetched.
        assert "indra_evidence" not in hyp.enrichments
    # The node mutates the same Hypothesis objects in place.
    assert hyp_a.reflection_notes == "fills a gap\n\nClassification: missing piece"
    assert hyp_b.reflection_notes == "fills a gap\n\nClassification: missing piece"
    # A reflection-phase assistant message is appended.
    assert result["messages"][0]["metadata"]["phase"] == "reflection"


async def test_empty_llm_response_defaults_gracefully(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An LLM response missing classification/reasoning uses safe defaults.

    ``analyze_single_hypothesis`` defaults ``classification`` to "neutral" and
    ``reasoning`` to "", so the note is exactly "\\n\\nClassification: neutral".
    """
    hyp = make_hypothesis(text="some hypothesis")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    _stub_llm(monkeypatch, {})

    result = await reflection_node(state)

    assert result["hypotheses"][0].reflection_notes == (
        "\n\nClassification: neutral")
    assert "indra_evidence" not in result["hypotheses"][0].enrichments

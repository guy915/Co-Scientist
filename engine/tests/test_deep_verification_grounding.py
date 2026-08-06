"""Graceful novelty grounding when MCP is down (audit E8).

With the live search back end unavailable, probe evidence must be grounded
against the run's already-retrieved corpus instead of being skipped --
the ungrounded path is exactly the failure mode the paper measured.
"""

from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import deep_verification as dv
from co_scientist.agents.reflection import deep_verification_evidence as dve
from tests._state import make_article, make_hypothesis, make_state


def test_corpus_fallback_selects_sources_matching_the_probe_queries() -> None:
    """Coverage over the query's terms picks the relevant corpus sources."""
    matching = make_article(
        "Tamoxifen efflux pump study",
        abstract="tamoxifen acrB expression Klebsiella pneumoniae",
        used_in_analysis=True,
    )
    unrelated = make_article(
        "Unrelated ecology survey",
        abstract="soil microbiome diversity survey",
        used_in_analysis=True,
    )
    state = make_state(articles=[unrelated, matching], mcp_available=False)

    articles, errors = dve._corpus_probe_evidence(
        state, ["tamoxifen acrB expression Klebsiella"]
    )

    assert [article.title for article in articles] == [
        "Tamoxifen efflux pump study"
    ]
    assert errors == [dve.CORPUS_FALLBACK_NOTE]


def test_corpus_fallback_retracted_sources_are_excluded() -> None:
    """A retracted source is not grounding even when its terms match."""
    retracted = make_article(
        "Retracted tamoxifen study",
        abstract="tamoxifen acrB expression Klebsiella",
        is_retracted=True,
    )
    state = make_state(articles=[retracted], mcp_available=False)

    articles, _ = dve._corpus_probe_evidence(
        state, ["tamoxifen acrB expression Klebsiella"]
    )

    assert articles == []


async def test_probe_retrieval_falls_back_to_corpus_without_mcp() -> None:
    """The node-level retrieval degrades to the corpus instead of skipping."""
    article = make_article(
        "Sertraline membrane study",
        abstract="sertraline proton motive force bacterial membrane",
        used_in_analysis=True,
    )
    state = make_state(articles=[article], mcp_available=False)

    articles, errors = await dve._retrieve_probe_evidence(
        state, ["sertraline proton motive force"]
    )

    assert articles == [article]
    assert errors == [dve.CORPUS_FALLBACK_NOTE]


async def test_probe_retrieval_with_no_queries_still_returns_nothing() -> None:
    """No queries means nothing to ground, with or without MCP."""
    article = make_article("Any paper", abstract="content")
    state = make_state(articles=[article], mcp_available=False)

    articles, errors = await dve._retrieve_probe_evidence(state, [])

    assert articles == []
    assert errors == []


async def test_verification_grounds_probes_in_corpus_when_mcp_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An MCP-down verification still gets a targeted evidence block.

    The probe's keywords match a corpus source, so the verifier is called
    a second time against it -- the same two-call shape as the live path,
    grounded in what the run already retrieved.
    """
    first = {
        "probes": [
            {
                "question": "Does sertraline dissipate proton motive force?",
                "answer": "Unknown.",
                "reasoning": "The corpus does not resolve it.",
                "assumption_is_fundamental": True,
                "search_query": "sertraline proton motive force",
            }
        ],
        "verdict": "weakened",
        "overall_assessment": "Evidence is missing.",
    }
    final = dict(first, verdict="holds")
    call = AsyncMock(side_effect=[first, final])
    monkeypatch.setattr(dv, "call_llm_json", call)

    state = make_state(
        hypotheses=[make_hypothesis(text="leader", elo_rating=2000)],
        articles=[
            make_article(
                "Sertraline membrane study",
                abstract="sertraline proton motive force bacterial membrane",
                used_in_analysis=True,
            )
        ],
        research_goal="goal",
        model_name="test/model",
        run_id="r1",
        mcp_available=False,
    )

    output = await dv.deep_verification_node(state)

    assert call.await_count == 2
    second_prompt = call.await_args_list[1].kwargs["prompt"]
    assert "Targeted probe evidence" in second_prompt
    assert "Sertraline membrane study" in second_prompt
    result_errors = output["hypotheses"][0].enrichments["deep_verification"][
        "retrieval_errors"
    ]
    assert dve.CORPUS_FALLBACK_NOTE in result_errors
    assert output["hypotheses"][0].deep_verification_verdict == "holds"


async def test_review_queries_still_formulated_when_corpus_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP down with a corpus still spends a query-generation call."""
    call = AsyncMock(return_value={"queries": ["term one"]})
    monkeypatch.setattr(cr, "_call_hypothesis_query_llm", call)

    state = make_state(
        articles=[make_article("Paper", abstract="x")],
        mcp_available=False,
    )
    queries = await cr._hypothesis_search_queries(
        state, make_hypothesis(text="h")
    )

    assert queries == ["term one"]
    assert call.await_count == 1


async def test_review_queries_skipped_when_nothing_to_ground_against(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No MCP and no corpus: a query call would only burn the budget."""
    call = AsyncMock(return_value={"queries": ["term one"]})
    monkeypatch.setattr(cr, "_call_hypothesis_query_llm", call)

    state = make_state(articles=None, mcp_available=False)
    queries = await cr._hypothesis_search_queries(
        state, make_hypothesis(text="h")
    )

    assert queries == []
    assert call.await_count == 0

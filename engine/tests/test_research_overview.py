"""Tests for the research-overview node.

The terminal node synthesizes the top-k hypotheses by Elo into a research
overview and an NIH Specific Aims page. These tests monkeypatch
``call_llm_json`` on the node module so no LLM or network calls are made, and
assert that the parsed overview and aims are returned in the state delta.
"""

from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.models import Article
from tests._state import make_article, make_hypothesis, make_state

# A grounded LLM response: one contact and one knowledge-base topic trace back
# to the analyzed source, and one of each is invented and must be dropped.
_OVERVIEW_RESPONSE = {
    "overview": {
        "summary": "S",
        "research_directions": [
            {
                "title": "T",
                "importance": "I",
                "suggested_experiments": ["E"],
            }
        ],
    },
    "nih_specific_aims": {
        "introduction": "intro",
        "aims": [
            {
                "aim": "A",
                "rationale": "R",
                "approach": "Ap",
            }
        ],
        "impact": "imp",
    },
    "research_contacts": [
        {
            "candidate_id": "author-1-1",
            "name": "Ada Researcher",
            "expertise": "Fibrosis mechanisms",
            "justification": "Authored the analyzed source.",
        },
        {
            "candidate_id": "invented",
            "name": "Invented Person",
            "expertise": "Unknown",
            "justification": "Not grounded.",
        },
    ],
    "knowledge_base": [
        {
            "title": "Epigenetic control of fibrosis",
            "summary": "HDAC activity is implicated in fibrosis.",
            "detail": "The analyzed study supports a testable axis.",
            "uncertainty": "Causality remains unresolved.",
            "evidence_ids": ["evidence-1", "invented-evidence"],
        },
        {
            "title": "Unsupported topic",
            "summary": "No source.",
            "detail": "No source.",
            "uncertainty": "Unknown.",
            "evidence_ids": ["invented-evidence"],
        },
    ],
}


def _grounded_articles() -> list[Article]:
    """One analyzed source grounding the contacts and knowledge base."""
    return [
        make_article(
            title="Fibrosis mechanisms",
            authors=["Ada Researcher"],
            source_id="PMID:123",
            url="https://pubmed.ncbi.nlm.nih.gov/123/",
            used_in_analysis=True,
        )
    ]


async def test_produces_overview_and_aims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The node returns the overview and NIH Specific Aims from the LLM."""
    fake = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis", elo_rating=1700
    )
    state = make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=_grounded_articles(),
    )
    out = await ro.research_overview_node(state)

    assert out["research_overview"]["overview"]["summary"] == "S"
    assert (
        out["research_overview"]["nih_specific_aims"]["aims"][0]["aim"] == "A"
    )
    assert fake.await_count == 1
    contacts = out["research_overview"]["research_contacts"]
    assert len(contacts) == 1
    assert contacts[0]["name"] == "Ada Researcher"
    assert contacts[0]["source_id"] == "PMID:123"
    assert "Invented Person" not in str(contacts)
    topics = out["research_overview"]["knowledge_base"]
    assert len(topics) == 1
    assert topics[0]["title"] == "Epigenetic control of fibrosis"
    assert topics[0]["references"][0]["title"] == "Fibrosis mechanisms"
    assert "Unsupported topic" not in str(topics)


def test_evidence_corpus_interleaves_sources() -> None:
    """The corpus head samples every source, not one source's top cluster.

    Articles arrive best-first (search results are ranked by retrieval score),
    which clusters each source's top papers together at the front. Feeding that
    order to the synthesis LLM makes it over-cite the first few references, so
    the corpus is round-robined across sources before it is numbered: the first
    N entries (N = source count) must cover all N sources.
    """
    articles = [
        make_article(title="P1", source="pubmed", used_in_analysis=True),
        make_article(title="P2", source="pubmed", used_in_analysis=True),
        make_article(title="P3", source="pubmed", used_in_analysis=True),
        make_article(title="O1", source="openalex", used_in_analysis=True),
        make_article(title="O2", source="openalex", used_in_analysis=True),
        make_article(title="C1", source="sbi_corpus", used_in_analysis=True),
    ]

    corpus = ro._build_evidence_corpus(articles)
    ordered = list(corpus.values())

    # Ids are contiguous in presentation order.
    assert [entry["evidence_id"] for entry in ordered] == [
        f"evidence-{i + 1}" for i in range(6)
    ]
    # The head (first three, one per source) covers every source rather than
    # three pubmed papers in a row.
    assert {entry["source"] for entry in ordered[:3]} == {
        "pubmed",
        "openalex",
        "sbi_corpus",
    }
    # Best-first order is preserved within each source.
    pubmed_titles = [e["title"] for e in ordered if e["source"] == "pubmed"]
    assert pubmed_titles == ["P1", "P2", "P3"]

"""Tests for research-overview research_contact_groups (R14-6).

Split out of test_research_overview.py to stay under the repo's 500-line
file ceiling. Shares _OVERVIEW_RESPONSE and _grounded_articles with the
main suite rather than importing them, since both are import-time private
module fixtures and duplicating this small a slice is simpler than
exporting test helpers across files.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.models import Article
from tests._state import make_article, make_hypothesis, make_state

# Mirrors test_research_overview.py's _OVERVIEW_RESPONSE: one contact and
# one knowledge-base topic trace back to the analyzed source.
_OVERVIEW_RESPONSE: dict[str, Any] = {
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
        "disease_description": "intro",
        "aims": [
            {
                "overarching_goal": "A",
                "hypothesis": "R",
                "reasoning": "Ap",
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
            "research_direction": "Epigenetic control of fibrosis",
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


async def test_research_contact_groups_resolve_indices_to_real_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R14-6: a group's example indices resolve to real hypothesis ids.

    The model never writes a title itself -- it names a 1-based position
    in the numbered top-k list, and the node resolves that back to the
    real hypothesis id. An out-of-range index (99, when only one
    hypothesis was offered) is dropped rather than guessed at, and a
    group naming no direction is dropped entirely.
    """
    response = {
        **_OVERVIEW_RESPONSE,
        "research_contact_groups": [
            {
                "research_direction": "Epigenetic control of fibrosis",
                "rationale": ("Both bring complementary chromatin expertise."),
                "example_hypothesis_indices": [1, 99],
            },
            {"research_direction": "", "rationale": "unnamed, dropped"},
        ],
    }
    fake = AsyncMock(return_value=response)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis",
        elo_rating=1700,
        id="h1",
    )
    state = make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=_grounded_articles(),
    )
    out = await ro.research_overview_node(state)

    groups = out["research_overview"]["research_contact_groups"]
    assert len(groups) == 1
    assert groups[0]["research_direction"] == ("Epigenetic control of fibrosis")
    assert groups[0]["rationale"] == (
        "Both bring complementary chromatin expertise."
    )
    assert groups[0]["example_hypothesis_ids"] == ["h1"]


async def test_research_contact_groups_default_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response omitting research_contact_groups degrades to []."""
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

    assert out["research_overview"]["research_contact_groups"] == []

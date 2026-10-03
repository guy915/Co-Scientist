"""Tests for the research-overview node.

The terminal node synthesizes the top-k hypotheses by Elo into a research
overview and an NIH Specific Aims page. These tests monkeypatch
``call_llm_json`` on the node module so no LLM or network calls are made, and
assert that the parsed overview and aims are returned in the state delta.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.meta_review.research_overview_evidence import (
    _format_evidence_corpus,
)
from co_scientist.constants import RESEARCH_OVERVIEW_TOP_K
from co_scientist.models import Article, Hypothesis
from tests._state import make_article, make_hypothesis, make_state

# A grounded LLM response: one contact and one knowledge-base topic trace back
# to the analyzed source, and one of each is invented and must be dropped.
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
        out["research_overview"]["nih_specific_aims"]["aims"][0][
            "overarching_goal"
        ]
        == "A"
    )
    # Two calls: the draft, plus the one call that develops its single
    # drafted direction (research_overview_direction_calls).
    assert fake.await_count == 2
    contacts = out["research_overview"]["research_contacts"]
    assert len(contacts) == 1
    assert contacts[0]["name"] == "Ada Researcher"
    assert contacts[0]["source_id"] == "PMID:123"
    assert contacts[0]["research_direction"] == "Epigenetic control of fibrosis"
    assert "Invented Person" not in str(contacts)
    topics = out["research_overview"]["knowledge_base"]
    assert len(topics) == 1
    assert topics[0]["title"] == "Epigenetic control of fibrosis"
    assert topics[0]["references"][0]["title"] == "Fibrosis mechanisms"
    assert "Unsupported topic" not in str(topics)


async def test_open_questions_and_patterns_map_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R12-10: open_questions/clear_patterns/unexpected_patterns pass through.

    New research-overview fields (see
    ``schemas.synthesis.RESEARCH_OVERVIEW_SCHEMA``); this pins that the
    node's formatting carries them into the state delta unchanged, the
    same way ``overview``/``nih_specific_aims`` already do.
    """
    response = {
        **_OVERVIEW_RESPONSE,
        "open_questions": ["What drives the reversal threshold?"],
        "clear_patterns": ["Lipid handling recurs across every idea."],
        "unexpected_patterns": ["A metabolic block explains proteolysis."],
    }
    fake = AsyncMock(return_value=response)
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

    overview = out["research_overview"]
    assert overview["open_questions"] == ["What drives the reversal threshold?"]
    assert overview["clear_patterns"] == [
        "Lipid handling recurs across every idea."
    ]
    assert overview["unexpected_patterns"] == [
        "A metabolic block explains proteolysis."
    ]


async def test_a_contact_with_no_research_direction_defaults_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A json_object-mode response omitting the field never raises.

    The schema declares research_direction required, but nothing enforces
    that server-side under the json_object downgrade, so the model may
    still omit it -- this must degrade to an empty string, not a KeyError.
    """
    response = {
        **_OVERVIEW_RESPONSE,
        "research_contacts": [
            {
                "candidate_id": "author-1-1",
                "name": "Ada Researcher",
                "expertise": "Fibrosis mechanisms",
                "justification": "Authored the analyzed source.",
            }
        ],
    }
    fake = AsyncMock(return_value=response)
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

    contacts = out["research_overview"]["research_contacts"]
    assert contacts[0]["research_direction"] == ""


# One (field, value) pair per publication-gate exclusion category: the
# blocking review dispositions and the blocking safety outcomes.
#
# A deep-verification "undermined" verdict is deliberately not here: it
# demotes rather than withholds, so the synthesis sees the idea. What it
# must not do is headline it -- pinned by
# test_an_undermined_idea_never_headlines_the_synthesis below.
_BLOCKED_HYPOTHESIS_FIELDS: list[tuple[str, str]] = [
    ("review_disposition", "inaccurate"),
    ("review_disposition", "non_novel"),
    ("review_disposition", "inaccurate_and_non_novel"),
    ("review_disposition", "evidence_blocked"),
    ("safety_status", "prohibited"),
    ("safety_status", "ethical_concern"),
    ("safety_status", "uncertain"),
]


def _blocked_hypotheses() -> list[Hypothesis]:
    """One hypothesis per exclusion category, each outranking healthy ideas.

    The high Elo ratings make the failure mode visible: an unfiltered
    top-k summary would consist of exactly these withheld ideas.
    """
    return [
        make_hypothesis(
            text=f"blocked idea {index} ({field_name}={value})",
            elo_rating=2000 + index,
            **{field_name: value},
        )
        for index, (field_name, value) in enumerate(_BLOCKED_HYPOTHESIS_FIELDS)
    ]


async def test_publication_gates_filter_before_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blocked hypotheses never reach the synthesis prompt.

    The pool mixes healthy hypotheses with one representative of every
    exclusion category; the blocked ones all outrank the healthy ones by
    Elo, so ranking the unfiltered pool would feed the withheld ideas to
    the synthesis LLM. Filtering must happen before that call -- prose
    already synthesized from a blocked idea cannot be unlabeled later.
    """
    fake = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    healthy = make_hypothesis(text="healthy idea", elo_rating=1500)
    needs_revision = make_hypothesis(
        text="needs revision idea",
        elo_rating=1400,
        review_disposition="needs_revision",
    )
    blocked = _blocked_hypotheses()

    state = make_state(
        hypotheses=[healthy, needs_revision, *blocked],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
    )
    out = await ro.research_overview_node(state)

    # Two calls: the draft, plus the one call that develops its single
    # drafted direction (research_overview_direction_calls).
    assert fake.await_count == 2
    assert fake.await_args_list[0] is not None
    prompt = fake.await_args_list[0].kwargs["prompt"]
    assert "healthy idea" in prompt
    # needs_revision ranks and publishes; only the not-viable band blocks.
    assert "needs revision idea" in prompt
    for hypothesis in blocked:
        assert hypothesis.text not in prompt
    assert out["research_overview"]["overview"]["summary"] == "S"


async def test_all_blocked_pool_skips_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the gates withhold everything, no LLM call happens.

    The node takes the same empty-pool branch as a run with no hypotheses
    at all and returns an empty research_overview.
    """
    fake = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    state = make_state(
        hypotheses=_blocked_hypotheses(),
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
    )
    out = await ro.research_overview_node(state)

    assert out == {"research_overview": {}}
    assert fake.await_count == 0


async def test_healthy_pool_keeps_top_k_elo_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fully publishable pool keeps the top-k Elo-order behavior.

    More hypotheses than the top-k cap are offered; the summary must hold
    exactly the strongest RESEARCH_OVERVIEW_TOP_K, in descending Elo order.
    """
    fake = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    hypotheses = [
        make_hypothesis(text=f"idea-{index:02d}", elo_rating=1000 + index * 10)
        for index in range(RESEARCH_OVERVIEW_TOP_K + 2)
    ]
    state = make_state(
        hypotheses=hypotheses,
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
    )
    await ro.research_overview_node(state)

    # Two calls: the draft, plus the one call that develops its single
    # drafted direction (research_overview_direction_calls).
    assert fake.await_count == 2
    assert fake.await_args_list[0] is not None
    prompt = fake.await_args_list[0].kwargs["prompt"]
    ranked_texts = [
        f"idea-{index:02d}"
        for index in range(RESEARCH_OVERVIEW_TOP_K + 1, 1, -1)
    ]
    positions = [prompt.index(text) for text in ranked_texts]
    assert positions == sorted(positions)
    assert "idea-00" not in prompt
    assert "idea-01" not in prompt


async def test_an_undermined_idea_never_headlines_the_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It reaches the synthesis, but below every sound idea.

    Its Elo is the highest in the pool because deep verification only
    probes the tournament's leaders and the verdict lands after the matches
    that promoted it -- so plain Elo order would open the run's synthesis
    with the one idea a probe found a fundamental flaw in.
    """
    fake = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    undermined = make_hypothesis(
        text="undermined leader",
        elo_rating=2000,
        deep_verification_verdict="undermined",
    )
    sound = [
        make_hypothesis(text=f"sound-{index}", elo_rating=1000 + index)
        for index in range(2)
    ]
    state = make_state(
        hypotheses=[undermined, *sound],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
    )
    await ro.research_overview_node(state)

    assert fake.await_args is not None
    prompt = fake.await_args.kwargs["prompt"]
    assert prompt.index("undermined leader") > prompt.index("sound-0")


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
        make_article(title="C1", source="third_source", used_in_analysis=True),
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
        "third_source",
    }
    # Best-first order is preserved within each source.
    pubmed_titles = [e["title"] for e in ordered if e["source"] == "pubmed"]
    assert pubmed_titles == ["P1", "P2", "P3"]


def test_evidence_corpus_prompt_strips_citation_markers() -> None:
    """A source's own citations do not reach the synthesis prompt.

    Left in, the synthesis model can copy one into the research overview
    it writes -- a real-looking reference attached to a claim the cited
    source never made.
    """
    abstract = "This confirms prior work (Smith et al. 2019) [12]."
    articles = [
        make_article(
            title="P1",
            source="pubmed",
            abstract=abstract,
            used_in_analysis=True,
        )
    ]

    corpus = ro._build_evidence_corpus(articles)
    formatted = _format_evidence_corpus(corpus)

    assert "(Smith et al. 2019)" not in formatted
    assert "[12]" not in formatted


def test_evidence_corpus_dict_keeps_citation_markers_for_the_report() -> None:
    """The corpus dict must keep the abstract as retrieved.

    It is reused to attach source metadata to the knowledge-base topics
    the report ships, so stripping belongs to the prompt formatter alone.
    """
    abstract = "This confirms prior work (Smith et al. 2019) [12]."
    articles = [
        make_article(
            title="P1",
            source="pubmed",
            abstract=abstract,
            used_in_analysis=True,
        )
    ]

    corpus = ro._build_evidence_corpus(articles)
    _format_evidence_corpus(corpus)

    assert next(iter(corpus.values()))["abstract"] == abstract

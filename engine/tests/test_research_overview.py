"""Offline contracts for research overview."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.generation import operations
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.meta_review.research_overview_evidence import (
    _format_evidence_corpus,
)
from co_scientist.constants import (
    RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS,
    RESEARCH_OVERVIEW_MAX_TOKENS,
    RESEARCH_OVERVIEW_TOP_K,
)
from co_scientist.models import Article, Hypothesis
from co_scientist.scheduling import TaskType
from co_scientist.schemas.synthesis import RESEARCH_OVERVIEW_SCHEMA
from tests._state import make_article, make_hypothesis, make_state

# A grounded LLM response: one contact and one knowledge-base topic trace back
# to the analyzed source, and one of each is invented and must be dropped.
_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE: dict[str, Any] = {
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


def _research_overview_grounded_articles() -> list[Article]:
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
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis", elo_rating=1700
    )
    state = make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=_research_overview_grounded_articles(),
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
        **_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE,
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
        articles=_research_overview_grounded_articles(),
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
        **_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE,
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
        articles=_research_overview_grounded_articles(),
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
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE)
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
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE)
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
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE)
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
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE)
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


# Mirrors test_research_overview.py's _OVERVIEW_RESPONSE: one contact and
# one knowledge-base topic trace back to the analyzed source.
_RESEARCH_OVERVIEW_CONTACTS_OVERVIEW_RESPONSE: dict[str, Any] = {
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


def _research_overview_contacts_grounded_articles() -> list[Article]:
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
        **_RESEARCH_OVERVIEW_CONTACTS_OVERVIEW_RESPONSE,
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
        articles=_research_overview_contacts_grounded_articles(),
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
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_CONTACTS_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis", elo_rating=1700
    )
    state = make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=_research_overview_contacts_grounded_articles(),
    )
    out = await ro.research_overview_node(state)

    assert out["research_overview"]["research_contact_groups"] == []


async def test_research_overview_synthesizes_without_nullable_authors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An analyzed article with null authors cannot block the overview."""
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_CONTACTS_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis", elo_rating=1700
    )
    state = make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=[
            make_article(
                title="Fibrosis mechanisms",
                authors=None,
                source_id="PMID:123",
                url="https://pubmed.ncbi.nlm.nih.gov/123/",
                used_in_analysis=True,
            )
        ],
    )

    out = await ro.research_overview_node(state)

    assert fake.await_count > 0
    assert out["research_overview"]["research_contacts"] == []


_RESPONSE: dict[str, Any] = {
    "overview": {
        "summary": "Where the evidence points.",
        "research_directions": [
            {
                "title": "Releasing the myeloid brake",
                "importance": "It unlocks fibrolysis.",
                "suggested_experiments": ["Block LILRB4."],
            }
        ],
    },
    "nih_specific_aims": {},
    "open_questions": ["What sets the reversal threshold?"],
    "knowledge_base": [],
}


def _state(**overrides: Any) -> Any:
    return make_state(
        hypotheses=[make_hypothesis(text="an idea", elo_rating=1700)],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=[make_article(used_in_analysis=True)],
        enable_overview_review=True,
        budget={"max_iterations": 3, "max_llm_calls": 7000},
        **overrides,
    )


async def test_a_periodic_firing_writes_only_the_interim_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``research_overview`` stays the published document's own key."""
    monkeypatch.setattr(ro, "call_llm_json", AsyncMock(return_value=_RESPONSE))

    out = await ro.research_overview_node(
        _state(next_task=TaskType.SYNTHESIZE.value)
    )

    assert "research_overview" not in out
    assert "Releasing the myeloid brake" in out["interim_overview"]
    assert "What sets the reversal threshold?" in out["interim_overview"]


async def test_a_periodic_firing_buys_neither_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call: no accuracy-review loop, no deep knowledge-base call."""
    fake = AsyncMock(return_value=_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)
    review = AsyncMock()
    monkeypatch.setattr(ro, "review_research_overview", review)
    deep = AsyncMock()
    monkeypatch.setattr(ro, "synthesize_knowledge_base", deep)

    await ro.research_overview_node(_state(next_task=TaskType.SYNTHESIZE.value))

    assert fake.await_count == 1
    assert review.await_count == 0
    assert deep.await_count == 0


async def test_a_periodic_firing_asks_only_for_directions_and_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interim call's own schema, not the terminal document's ten.

    Before this schema existed every periodic firing still paid for the
    NIH Specific Aims page, the contacts and the knowledge base at the
    terminal call's own generation cost, and discarded all of it --
    ``build_interim_overview`` only ever reads direction titles and open
    questions back out.
    """
    fake = AsyncMock(return_value=_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    await ro.research_overview_node(_state(next_task=TaskType.SYNTHESIZE.value))

    assert fake.await_args is not None
    schema = fake.await_args.kwargs["spec"].json_schema
    assert schema is not None
    properties = schema["schema"]["properties"]
    assert set(properties) == {"overview", "open_questions"}
    assert set(properties["overview"]["properties"]) == {"research_directions"}
    direction_item = properties["overview"]["properties"][
        "research_directions"
    ]["items"]
    assert set(direction_item["properties"]) == {"title"}
    assert "nih_specific_aims" not in properties
    assert "research_contacts" not in properties
    assert "knowledge_base" not in properties


def test_the_interim_schema_is_a_strict_subset_of_the_terminal_one() -> None:
    """Direction titles and open questions only -- named once, reused.

    ``RESEARCH_OVERVIEW_INTERIM_MAX_DIRECTIONS``/``_MAX_QUESTIONS`` are the
    same constants ``interim_overview.build_interim_overview`` renders
    from, so this call is never asked to write a title or question the
    next generate cycle will not see.
    """
    from co_scientist.schemas.synthesis import RESEARCH_OVERVIEW_INTERIM_SCHEMA

    terminal_top = set(RESEARCH_OVERVIEW_SCHEMA["schema"]["properties"])
    interim_top = set(RESEARCH_OVERVIEW_INTERIM_SCHEMA["schema"]["properties"])
    assert interim_top < terminal_top

    terminal_overview = set(
        RESEARCH_OVERVIEW_SCHEMA["schema"]["properties"]["overview"][
            "properties"
        ]
    )
    interim_overview_props = set(
        RESEARCH_OVERVIEW_INTERIM_SCHEMA["schema"]["properties"]["overview"][
            "properties"
        ]
    )
    assert interim_overview_props < terminal_overview


async def test_a_periodic_firing_is_budgeted_below_the_terminal_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tiny ask does not need the terminal document's base budget.

    Whether this actually lowers the deployed chain's *effective*
    ceiling depends on whether the model thinks -- see
    ``RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS``'s own docstring -- but the
    base budget passed to the call is smaller either way.
    """
    fake = AsyncMock(return_value=_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    await ro.research_overview_node(_state(next_task=TaskType.SYNTHESIZE.value))

    assert fake.await_args is not None
    spec = fake.await_args.kwargs["spec"]
    assert spec.max_tokens == RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS
    assert spec.max_tokens < RESEARCH_OVERVIEW_MAX_TOKENS


async def test_the_terminal_firing_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TERMINATE still publishes the overview and writes no interim."""
    monkeypatch.setattr(ro, "call_llm_json", AsyncMock(return_value=_RESPONSE))
    monkeypatch.setattr(
        ro, "synthesize_knowledge_base", AsyncMock(return_value=([], 0))
    )
    monkeypatch.setattr(
        ro,
        "review_research_overview",
        AsyncMock(return_value=(_RESPONSE, {"reviewed": True, "rounds": 1}, 1)),
    )

    out = await ro.research_overview_node(
        _state(next_task=TaskType.TERMINATE.value)
    )

    assert "interim_overview" not in out
    assert out["research_overview"]["overview"]["summary"]


def test_generation_reads_the_interim_overview_as_context() -> None:
    """The feedback edge lands where the generation prompts already read.

    Spliced onto the literature context the strategies are handed rather
    than into a new prompt slot: the block describes this run's own
    findings so far, which is what that context is.
    """
    state = make_state(interim_overview="Direction 1: block the brake.")
    augmented = operations._with_interim_overview(state, "Paper A says X.")

    assert augmented is not None
    assert "Direction 1: block the brake." in augmented
    assert "Paper A says X." in augmented


async def testprepare_task_state_splices_the_block_into_its_context() -> None:
    """The splice itself, at the seam every strategy is handed.

    ``_with_interim_overview`` being correct in isolation is not the fix:
    the call in ``prepare_generation`` is what puts it in front of the
    generation prompts.
    """
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=2,
        mcp_available=True,
        articles_with_reasoning="Paper A says X.",
        interim_overview="Direction 1: block the brake.",
    )

    context = (await operations.prepare_generation(state)).literature

    assert context is not None
    assert "Direction 1: block the brake." in context
    assert "Paper A says X." in context


def test_generation_context_is_untouched_before_the_first_firing() -> None:
    """No firing yet means byte-identical prompts to before this fix."""
    state = make_state()
    unchanged = operations._with_interim_overview(state, "Paper A says X.")
    assert unchanged == "Paper A says X."
    assert operations._with_interim_overview(state, None) is None

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.generation import operations
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.meta_review.research_overview_evidence import (
    RESEARCH_OVERVIEW_MAX_SOURCES,
)
from co_scientist.constants import (
    RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS,
    RESEARCH_OVERVIEW_MAX_TOKENS,
    RESEARCH_OVERVIEW_TOP_K,
)
from co_scientist.models import Article, Hypothesis
from co_scientist.scheduling import TaskType
from tests._state import make_article, make_hypothesis, make_state

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
    return [
        make_article(
            title="Fibrosis mechanisms",
            authors=["Ada Researcher"],
            source_id="PMID:123",
            url="https://pubmed.ncbi.nlm.nih.gov/123/",
            used_in_analysis=True,
        )
    ]


def _grounded_state(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "hypotheses": [
            make_hypothesis(
                text="HDAC inhibition reverses fibrosis",
                elo_rating=1700,
                id="h1",
            )
        ],
        "research_goal": "g",
        "supervisor_model_name": "test/model",
        "meta_review": {},
        "articles": _research_overview_grounded_articles(),
    }
    return make_state(**{**fields, **overrides})


async def _synthesize(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    monkeypatch.setattr(ro, "call_llm_json", AsyncMock(return_value=response))
    out = await ro.research_overview_node(_grounded_state(**overrides))
    overview: dict[str, Any] = out["research_overview"]
    return overview


async def test_publishes_overview_with_only_grounded_contacts_and_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    out = await ro.research_overview_node(_grounded_state())

    overview = out["research_overview"]
    assert overview["overview"]["summary"] == "S"
    assert overview["nih_specific_aims"]["aims"][0]["overarching_goal"] == "A"
    assert fake.await_count == 2
    contacts = overview["research_contacts"]
    assert len(contacts) == 1
    assert contacts[0]["name"] == "Ada Researcher"
    assert contacts[0]["source_id"] == "PMID:123"
    assert contacts[0]["research_direction"] == "Epigenetic control of fibrosis"
    assert "Invented Person" not in str(contacts)
    topics = overview["knowledge_base"]
    assert len(topics) == 1
    assert topics[0]["title"] == "Epigenetic control of fibrosis"
    assert topics[0]["references"][0]["title"] == "Fibrosis mechanisms"
    assert "Unsupported topic" not in str(topics)
    assert overview["research_contact_groups"] == []


async def test_open_questions_and_patterns_map_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overview = await _synthesize(
        monkeypatch,
        {
            **_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE,
            "open_questions": ["What drives the reversal threshold?"],
            "clear_patterns": ["Lipid handling recurs across every idea."],
            "unexpected_patterns": ["A metabolic block explains proteolysis."],
        },
    )

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
    """The json_object downgrade can omit schema-required fields."""
    contact = {
        key: value
        for key, value in _RESEARCH_OVERVIEW_OVERVIEW_RESPONSE[
            "research_contacts"
        ][0].items()
        if key != "research_direction"
    }

    overview = await _synthesize(
        monkeypatch,
        {
            **_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE,
            "research_contacts": [contact],
        },
    )

    assert overview["research_contacts"][0]["research_direction"] == ""


async def test_research_contact_groups_resolve_indices_to_real_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overview = await _synthesize(
        monkeypatch,
        {
            **_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE,
            "research_contact_groups": [
                {
                    "research_direction": "Epigenetic control of fibrosis",
                    "rationale": "Complementary chromatin expertise.",
                    "example_hypothesis_indices": [1, 99],
                },
                {"research_direction": "", "rationale": "unnamed, dropped"},
            ],
        },
    )

    assert overview["research_contact_groups"] == [
        {
            "research_direction": "Epigenetic control of fibrosis",
            "rationale": "Complementary chromatin expertise.",
            "example_hypothesis_ids": ["h1"],
        }
    ]


async def test_research_overview_synthesizes_without_nullable_authors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overview = await _synthesize(
        monkeypatch,
        _RESEARCH_OVERVIEW_OVERVIEW_RESPONSE,
        articles=[
            make_article(
                title="Fibrosis mechanisms",
                authors=None,
                source_id="PMID:123",
                used_in_analysis=True,
            )
        ],
    )

    assert overview["research_contacts"] == []


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
    """Blocked ideas outrank healthy ones to expose filtering after top-k
    selection."""
    return [
        make_hypothesis(
            text=f"blocked idea {index} ({field_name}={value})",
            elo_rating=2000 + index,
            **{field_name: value},
        )
        for index, (field_name, value) in enumerate(_BLOCKED_HYPOTHESIS_FIELDS)
    ]


async def _first_prompt(
    monkeypatch: pytest.MonkeyPatch, hypotheses: list[Hypothesis]
) -> tuple[str, AsyncMock]:
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)
    await ro.research_overview_node(
        make_state(
            hypotheses=hypotheses,
            research_goal="g",
            supervisor_model_name="test/model",
            meta_review={},
        )
    )
    return fake.await_args_list[0].kwargs["prompt"], fake


async def test_publication_gates_filter_before_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prose synthesized from a blocked idea cannot be safely unlabeled
    later."""
    blocked = _blocked_hypotheses()
    needs_revision = make_hypothesis(
        text="needs revision idea",
        elo_rating=1400,
        review_disposition="needs_revision",
    )
    healthy = make_hypothesis(text="healthy idea", elo_rating=1500)

    prompt, _ = await _first_prompt(
        monkeypatch, [healthy, needs_revision, *blocked]
    )

    assert "healthy idea" in prompt
    # needs_revision ranks and publishes; only the not-viable band blocks.
    assert "needs revision idea" in prompt
    assert not any(hypothesis.text in prompt for hypothesis in blocked)


async def test_all_blocked_pool_skips_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    out = await ro.research_overview_node(
        make_state(
            hypotheses=_blocked_hypotheses(),
            research_goal="g",
            supervisor_model_name="test/model",
            meta_review={},
        )
    )

    assert out == {"research_overview": {}}
    assert fake.await_count == 0


async def test_synthesis_keeps_the_top_k_by_elo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ideas = [
        make_hypothesis(text=f"idea-{index:02d}", elo_rating=1000 + index * 10)
        for index in range(RESEARCH_OVERVIEW_TOP_K + 2)
    ]

    prompt, _ = await _first_prompt(monkeypatch, ideas)

    ranked = [
        f"idea-{index:02d}"
        for index in range(RESEARCH_OVERVIEW_TOP_K + 1, 1, -1)
    ]
    positions = [prompt.index(text) for text in ranked]
    assert positions == sorted(positions)
    assert "idea-00" not in prompt
    assert "idea-01" not in prompt


async def test_an_undermined_idea_never_headlines_the_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verification lands after matches; a flawed idea may still hold the
    highest Elo."""
    undermined = make_hypothesis(
        text="undermined leader",
        elo_rating=2000,
        deep_verification_verdict="undermined",
    )
    sound = make_hypothesis(text="sound idea", elo_rating=1000)

    prompt, _ = await _first_prompt(monkeypatch, [undermined, sound])

    assert prompt.index("undermined leader") > prompt.index("sound idea")


async def test_the_synthesis_prompt_carries_a_capped_interleaved_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source-clustered ordering over-cites the first references, and full text
    or copied citations would mislead the model."""
    abstract = "This confirms prior work (Smith et al. 2019) [12]."
    sources = ("pubmed", "openalex", "web")
    articles = [
        make_article(
            title=f"{source}-{index}",
            source=source,
            abstract=abstract,
            content="FULL TEXT BODY " * 2000,
            used_in_analysis=True,
        )
        for source in sources
        for index in range(RESEARCH_OVERVIEW_MAX_SOURCES)
    ]
    fake = AsyncMock(return_value=_RESEARCH_OVERVIEW_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    await ro.research_overview_node(_grounded_state(articles=articles))

    prompt = fake.await_args_list[0].kwargs["prompt"]
    lines = [
        line for line in prompt.splitlines() if line.startswith("- evidence-")
    ]
    assert [line.split(":")[0] for line in lines] == [
        f"- evidence-{index + 1}"
        for index in range(RESEARCH_OVERVIEW_MAX_SOURCES)
    ]
    assert {
        line.split("source=")[1].split(";")[0] for line in lines[:3]
    } == set(sources)
    assert "FULL TEXT BODY" not in prompt
    assert "(Smith et al. 2019)" not in prompt
    assert "[12]" not in prompt


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


async def test_a_periodic_firing_writes_only_a_lean_interim_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Periodic calls must not buy terminal prose, review or a deep knowledge
    base that their consumers discard."""
    fake = AsyncMock(return_value=_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", fake)

    out = await ro.research_overview_node(
        _state(next_task=TaskType.SYNTHESIZE.value)
    )

    assert "research_overview" not in out
    assert "Releasing the myeloid brake" in out["interim_overview"]
    assert "What sets the reversal threshold?" in out["interim_overview"]
    assert fake.await_count == 1
    assert fake.await_args is not None
    spec = fake.await_args.kwargs["spec"]
    properties = spec.json_schema["schema"]["properties"]
    assert set(properties) == {"overview", "open_questions"}
    assert set(properties["overview"]["properties"]) == {"research_directions"}
    direction_item = properties["overview"]["properties"][
        "research_directions"
    ]["items"]
    assert set(direction_item["properties"]) == {"title"}
    assert spec.max_tokens == RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS
    assert spec.max_tokens < RESEARCH_OVERVIEW_MAX_TOKENS


async def test_the_terminal_firing_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


@pytest.mark.parametrize(
    ("interim", "expected"),
    [
        ("Direction 1: block the brake.", ["Direction 1: block the brake."]),
        ("", []),
    ],
    ids=["after-first-firing", "before-first-firing"],
)
async def test_generation_reads_the_interim_overview_as_context(
    interim: str, expected: list[str]
) -> None:
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=2,
        mcp_available=True,
        articles_with_reasoning="Paper A says X.",
        interim_overview=interim,
    )

    context = (await operations.prepare_generation(state)).literature

    assert context is not None
    assert "Paper A says X." in context
    assert all(text in context for text in expected)
    if not interim:
        assert context == "Paper A says X."

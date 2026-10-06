from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.generation import operations
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.meta_review import (
    research_overview_direction_calls as calls,
)
from co_scientist.agents.meta_review.research_overview_evidence import (
    RESEARCH_OVERVIEW_MAX_SOURCES,
)
from co_scientist.constants import (
    RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS,
    RESEARCH_OVERVIEW_INTERIM_MAX_TOKENS,
    RESEARCH_OVERVIEW_MAX_TOKENS,
)
from co_scientist.models import Article, Hypothesis
from co_scientist.scheduling import TaskType
from co_scientist.schemas.synthesis import (
    RESEARCH_OVERVIEW_MAX_DIRECTIONS,
    RESEARCH_OVERVIEW_TARGET_DIRECTIONS,
)
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


def _context() -> calls.DirectionWaveContext:
    return calls.DirectionWaveContext(
        state=make_state(
            research_goal="Reverse liver fibrosis",
            supervisor_model_name="test/model",
        ),
        hypotheses_summary="1. an idea",
        evidence_corpus_text="evidence-1: a paper",
    )


def _drafted(count: int) -> list[dict[str, Any]]:
    return [
        {
            "title": f"Direction {index}",
            "importance": f"Why direction {index} matters.",
            "recent_findings": "",
            "suggested_experiments": [],
            "sub_topics": [],
        }
        for index in range(count)
    ]


def _body() -> dict[str, Any]:
    return {
        "importance": "The developed argument.",
        "recent_findings": "What is already established.",
        "suggested_experiments": ["Knock it down and read out the marker."],
        "sub_topics": [
            {
                "title": "Sub-topic A",
                "why": "Because Y.",
                "what": "Investigate Z.",
                "example_idea": "Knock Z down and read out Y.",
                "specific_questions": ["Does Z cause Y?"],
            }
        ],
    }


async def test_every_drafted_direction_buys_its_own_bounded_call() -> None:
    ask = AsyncMock(return_value={**_body(), "title": "Renamed"})

    developed, spent = await calls.develop_research_directions(
        _context(), _drafted(RESEARCH_OVERVIEW_TARGET_DIRECTIONS), ask
    )

    assert spent == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert ask.await_count == RESEARCH_OVERVIEW_TARGET_DIRECTIONS
    assert all(direction["sub_topics"] for direction in developed)
    assert [d["title"] for d in developed] == [
        f"Direction {index}" for index in range(len(developed))
    ]
    sent = ask.await_args_list[0].kwargs
    assert sent["spec"].max_tokens == RESEARCH_OVERVIEW_DIRECTION_MAX_TOKENS
    assert sent["options"].enable_thinking is False
    assert all(
        f"Direction {index}" in sent["prompt"]
        for index in range(RESEARCH_OVERVIEW_TARGET_DIRECTIONS)
    )


async def test_one_failing_call_costs_only_its_own_direction() -> None:
    ask = AsyncMock(side_effect=[RuntimeError("provider exploded"), _body()])

    developed, spent = await calls.develop_research_directions(
        _context(), _drafted(2), ask
    )

    assert spent == 2
    assert developed[0]["title"] == "Direction 0"
    assert developed[0]["importance"] == "Why direction 0 matters."
    assert developed[0]["sub_topics"] == []
    assert developed[1]["sub_topics"]


async def _research_overview_directions_run_overview_node(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> dict[str, Any]:
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
    )
    return await ro.research_overview_node(state)


def _direction_response(direction: dict[str, Any]) -> dict[str, Any]:
    return {"overview": {"summary": "S", "research_directions": [direction]}}


async def test_missing_direction_detail_degrades_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [{"title": "Sub-topic A", "why": "w", "what": "w"}],
        }
    )
    plain = _direction_response(
        {"title": "T", "importance": "I", "suggested_experiments": ["E"]}
    )

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )
    plain_out = await _research_overview_directions_run_overview_node(
        monkeypatch, plain
    )

    direction = out["research_overview"]["overview"]["research_directions"][0]
    assert direction["sub_topics"][0]["example_idea"] == ""
    bare = plain_out["research_overview"]["overview"]["research_directions"][0]
    assert bare["sub_topics"] == []
    assert bare["recent_findings"] == ""
    assert (
        plain_out["research_overview"]["unexpected_research_directions"] == []
    )


async def test_sub_topics_are_capped_and_malformed_ones_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The json_object downgrade does not enforce maxItems server-side."""
    many = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [
                {
                    "title": f"Topic {i}",
                    "why": "w",
                    "what": "w",
                    "specific_questions": [f"q{n}" for n in range(6)],
                }
                for i in range(6)
            ],
        }
    )
    malformed = _direction_response(
        {
            "title": "T",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [
                {"title": "ok", "why": "w", "what": "w"},
                "not a dict",
                {
                    "title": "ok2",
                    "why": "w",
                    "what": "w",
                    "specific_questions": "not a list",
                },
            ],
        }
    )

    capped = await _research_overview_directions_run_overview_node(
        monkeypatch, many
    )
    kept = await _research_overview_directions_run_overview_node(
        monkeypatch, malformed
    )

    sub_topics = capped["research_overview"]["overview"]["research_directions"][
        0
    ]["sub_topics"]
    assert [t["title"] for t in sub_topics] == [f"Topic {i}" for i in range(4)]
    assert len(sub_topics[0]["specific_questions"]) == 4
    salvaged = kept["research_overview"]["overview"]["research_directions"][0][
        "sub_topics"
    ]
    assert [t["title"] for t in salvaged] == ["ok", "ok2"]
    assert [t["specific_questions"] for t in salvaged] == [[], []]


async def test_research_directions_are_capped_at_the_schema_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directions = [
        {
            "title": f"Direction {i}",
            "importance": "I",
            "suggested_experiments": ["E"],
            "sub_topics": [],
        }
        for i in range(9)
    ]
    response = {"overview": {"summary": "S", "research_directions": directions}}

    out = await _research_overview_directions_run_overview_node(
        monkeypatch, response
    )

    kept = out["research_overview"]["overview"]["research_directions"]
    assert len(kept) == RESEARCH_OVERVIEW_MAX_DIRECTIONS
    assert kept[0]["title"] == "Direction 0"

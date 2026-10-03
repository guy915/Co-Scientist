from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.meta_review import meta_review
from co_scientist.agents.meta_review.meta_review import (
    _collect_feedback_records,
    _collect_review_summaries,
    meta_review_node,
    normalize_recurring_themes,
)
from co_scientist.agents.proximity import proximity, proximity_node
from co_scientist.agents.reflection import reflection
from co_scientist.agents.reflection.reflection import reflection_node
from co_scientist.agents.safety import safety_screen_node
from co_scientist.agents.supervisor.orchestrator import _compute_stats
from co_scientist.prompts import (
    DebatePromptRequest,
    PromptRunContext,
    RankingSide,
    get_debate_generation_prompt,
    get_literature_review_query_generation_prompt,
    get_literature_review_synthesis_prompt,
    get_ranking_prompt,
    get_reflection_prompt,
    get_review_batch_prompt,
    get_review_prompt,
)
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.scheduling.models import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    stacked_task_values,
)
from co_scientist.scheduling.policy import (
    _check_meta_review_cadence,
    decide_next_task,
    stack_companions,
)
from co_scientist.schemas.planning import META_REVIEW_SCHEMA
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_review, make_state


async def test_no_reviews_returns_default_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = stub_call_llm_json(
        monkeypatch, meta_review, {"meta_review_summary": "should not appear"}
    )
    state = make_state(
        hypotheses=[make_hypothesis(text="aaa"), make_hypothesis(text="bbb")]
    )

    result = await meta_review_node(state)

    assert calls == []
    assert result == {
        "meta_review": {
            "summary": "No reviews available",
            "common_strengths": [],
            "common_weaknesses": [],
            "strategic_recommendations": [],
        }
    }
    assert "emerging_themes" not in result["meta_review"]
    assert "metrics" not in result
    assert "messages" not in result


async def test_with_reviews_maps_response_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = stub_call_llm_json(
        monkeypatch,
        meta_review,
        {
            "meta_review_summary": "overall the set is promising",
            "strengths": ["clear mechanism", "testable"],
            "weaknesses": ["narrow scope"],
            "strategic_recommendations": ["broaden the cohort"],
            "recurring_themes": [],
            "potential_connections": [
                {
                    "related_hypotheses": ["Hypothesis 1", "Hypothesis 2"],
                    "connection_type": "complementary_mechanism",
                    "synthesis_opportunity": "combine both interventions",
                }
            ],
        },
    )
    state = make_state(
        hypotheses=[
            make_hypothesis(text="reviewed hyp", reviews=[make_review()])
        ]
    )

    result = await meta_review_node(state)

    assert len(calls) == 1
    mr = result["meta_review"]
    assert mr["summary"] == "overall the set is promising"
    assert mr["common_strengths"] == ["clear mechanism", "testable"]
    assert mr["common_weaknesses"] == ["narrow scope"]
    assert mr["strategic_recommendations"] == ["broaden the cohort"]
    assert mr["potential_connections"][0]["synthesis_opportunity"] == (
        "combine both interventions"
    )
    assert "metrics" in result
    assert result["messages"][0]["metadata"]["phase"] == "meta_review"


async def test_candidate_and_existing_solutions_comparisons_map_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_call_llm_json(
        monkeypatch,
        meta_review,
        {
            "meta_review_summary": "s",
            "candidate_comparison": {
                "thematic_summary": "Two mechanistic themes emerge.",
                "axes": ["Off-target risk"],
                "ideas": [
                    {
                        "idea": "Hypothesis 1: NHE1 blockade",
                        "values": ["Low -- selective for cardiac NHE1."],
                    }
                ],
            },
            "existing_solutions_comparison": {
                "summary": "Current care slows rather than reverses.",
                "axes": ["Mechanism targeted"],
                "rows": [
                    {
                        "method": "Beta-blockade",
                        "values": ["Afterload, not the NHE1 axis."],
                    }
                ],
            },
        },
    )
    state = make_state(
        hypotheses=[
            make_hypothesis(text="reviewed hyp", reviews=[make_review()])
        ]
    )

    result = await meta_review_node(state)

    mr = result["meta_review"]
    assert mr["candidate_comparison"]["thematic_summary"] == (
        "Two mechanistic themes emerge."
    )
    assert mr["candidate_comparison"]["axes"] == ["Off-target risk"]
    assert mr["candidate_comparison"]["ideas"][0]["idea"] == (
        "Hypothesis 1: NHE1 blockade"
    )
    assert mr["candidate_comparison"]["ideas"][0]["values"] == [
        "Low -- selective for cardiac NHE1."
    ]
    assert mr["existing_solutions_comparison"]["summary"] == (
        "Current care slows rather than reverses."
    )
    assert mr["existing_solutions_comparison"]["rows"][0]["method"] == (
        "Beta-blockade"
    )


async def test_main_research_directions_maps_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_call_llm_json(
        monkeypatch,
        meta_review,
        {
            "meta_review_summary": "s",
            "main_research_directions": (
                "Paragraph one names **Direction A** and why it matters.\n\n"
                "Paragraph two names **Direction B** and closes on an"
                " unexpected cross-direction observation."
            ),
        },
    )
    state = make_state(
        hypotheses=[
            make_hypothesis(text="reviewed hyp", reviews=[make_review()])
        ]
    )

    result = await meta_review_node(state)

    assert result["meta_review"]["main_research_directions"] == (
        "Paragraph one names **Direction A** and why it matters.\n\n"
        "Paragraph two names **Direction B** and closes on an"
        " unexpected cross-direction observation."
    )


async def test_state_preferences_reach_the_rendered_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = stub_call_llm_json(
        monkeypatch, meta_review, {"meta_review_summary": "s"}
    )
    state = make_state(
        hypotheses=[
            make_hypothesis(text="reviewed hyp", reviews=[make_review()])
        ],
        preferences="prioritize wet-lab feasibility over novelty",
    )

    await meta_review_node(state)

    assert len(calls) == 1
    assert "prioritize wet-lab feasibility over novelty" in calls[0]["prompt"]


async def test_recurring_themes_flattened_to_emerging_themes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_call_llm_json(
        monkeypatch,
        meta_review,
        {
            "meta_review_summary": "summary",
            "recurring_themes": [
                {
                    "theme": "mitochondrial dysfunction",
                    "description": "x",
                    "frequency": 3,
                },
                "oxidative stress",
            ],
        },
    )
    state = make_state(
        hypotheses=[
            make_hypothesis(text="reviewed hyp", reviews=[make_review()])
        ]
    )

    result = await meta_review_node(state)

    assert result["meta_review"]["emerging_themes"] == [
        "mitochondrial dysfunction",
        "oxidative stress",
    ]


async def test_recurring_themes_carry_description_and_frequency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_call_llm_json(
        monkeypatch,
        meta_review,
        {
            "meta_review_summary": "summary",
            "recurring_themes": [
                {
                    "theme": "mitochondrial dysfunction",
                    "description": "recurs across the reviewed pool",
                    "frequency": 3,
                    "sub_themes": [
                        {
                            "theme": "temporal ordering",
                            "description": (
                                "cause is not separated from effect"
                            ),
                            "points": ["run a longitudinal arm"],
                        }
                    ],
                },
                "oxidative stress",
            ],
        },
    )
    state = make_state(
        hypotheses=[
            make_hypothesis(text="reviewed hyp", reviews=[make_review()])
        ]
    )

    result = await meta_review_node(state)

    assert result["meta_review"]["recurring_themes"] == [
        {
            "theme": "mitochondrial dysfunction",
            "description": "recurs across the reviewed pool",
            "frequency": "3",
            "sub_themes": [
                {
                    "theme": "temporal ordering",
                    "description": "cause is not separated from effect",
                    "points": ["run a longitudinal arm"],
                }
            ],
        },
        {
            "theme": "oxidative stress",
            "description": "",
            "frequency": "",
            "sub_themes": [],
        },
    ]


def test_review_collection_keeps_complete_history() -> None:
    hypothesis = make_hypothesis(
        text="reviewed hyp",
        reviews=[
            make_review(review_summary="first failure pattern"),
            make_review(review_summary="later reassessment"),
        ],
    )
    [record] = _collect_review_summaries([hypothesis])
    assert [review["review_summary"] for review in record["reviews"]] == [
        "first failure pattern",
        "later reassessment",
    ]


def test_review_collection_numbers_hypotheses_from_one() -> None:
    """Recommendations quote these user-facing idea numbers, not array
    offsets."""
    hypotheses = [
        make_hypothesis(text=f"hyp {i}", reviews=[make_review()])
        for i in range(3)
    ]

    records = _collect_review_summaries(hypotheses)

    assert [record["hypothesis_index"] for record in records] == [1, 2, 3]


def test_review_collection_includes_mature_review_findings() -> None:
    hypothesis = make_hypothesis(text="reviewed hyp", reviews=[make_review()])
    hypothesis.enrichments["full"] = {
        "verdict": "rejected",
        "justification": "circular pathway",
        "retrieved_articles": [{"title": "not for the synthesis"}],
    }
    hypothesis.enrichments["simulation"] = {
        "verdict": "breaks_down",
        "decisive_step": "binding fails",
    }

    [record] = _collect_review_summaries([hypothesis])

    assert record["mature_reviews"]["full"]["verdict"] == "rejected"
    assert record["mature_reviews"]["full"]["justification"] == (
        "circular pathway"
    )
    assert record["mature_reviews"]["simulation"]["verdict"] == "breaks_down"
    assert "retrieved_articles" not in str(record["mature_reviews"])


def test_review_collection_omits_mature_reviews_before_the_cascade() -> None:
    hypothesis = make_hypothesis(text="reviewed hyp", reviews=[make_review()])

    [record] = _collect_review_summaries([hypothesis])

    assert "mature_reviews" not in record


def test_feedback_collection_keeps_full_debate_transcript() -> None:
    transcript = [
        {"turn": 1, "reasoning": "A has stronger causal evidence."},
        {"turn": 2, "reasoning": "B has a cleaner falsification test."},
    ]
    records = _collect_feedback_records(
        [make_hypothesis(text="reviewed", reviews=[make_review()])],
        [
            {
                "hypothesis_a_id": "a",
                "hypothesis_b_id": "b",
                "winner_id": "b",
                "debate_turns": 2,
                "debate_transcript": transcript,
            }
        ],
    )
    debate = next(r for r in records if r["record_type"] == "ranking_debate")
    assert debate["debate_transcript"] == transcript


def _themes_node() -> dict[str, Any]:
    node = META_REVIEW_SCHEMA["schema"]["properties"]["recurring_themes"]
    assert isinstance(node, dict)
    return node


def test_schema_nests_sub_themes_under_each_theme() -> None:
    item = _themes_node()["items"]
    sub_themes = item["properties"]["sub_themes"]
    assert "sub_themes" in item["required"]

    sub_item = sub_themes["items"]
    assert set(sub_item["properties"]) == {"theme", "description", "points"}
    assert sub_item["properties"]["points"]["items"] == {"type": "string"}


def test_schema_caps_do_not_clip_the_published_taxonomy() -> None:
    themes = _themes_node()
    sub_themes = themes["items"]["properties"]["sub_themes"]
    points = sub_themes["items"]["properties"]["points"]

    assert themes["maxItems"] >= 5
    assert sub_themes["maxItems"] >= 8
    assert points["maxItems"] >= 5


def test_normalize_carries_the_nesting_through() -> None:
    normalized = normalize_recurring_themes(
        [
            {
                "theme": "Core Hypothesis and Mechanism",
                "description": "How the mechanism itself is argued.",
                "frequency": 4,
                "sub_themes": [
                    {
                        "theme": "Primary Driver vs. Consequence",
                        "description": "Proving the mechanism initiates.",
                        "points": ["Provide longitudinal evidence.", 7],
                    }
                ],
            }
        ]
    )

    assert normalized == [
        {
            "theme": "Core Hypothesis and Mechanism",
            "description": "How the mechanism itself is argued.",
            "frequency": "4",
            "sub_themes": [
                {
                    "theme": "Primary Driver vs. Consequence",
                    "description": "Proving the mechanism initiates.",
                    "points": ["Provide longitudinal evidence.", "7"],
                }
            ],
        }
    ]


def test_normalize_tolerates_a_flat_entry_from_an_older_checkpoint() -> None:
    """Checkpointed themes may predate the nested schema."""
    normalized = normalize_recurring_themes(
        [
            {
                "theme": "mitochondrial dysfunction",
                "description": "recurs across the reviewed pool",
                "frequency": "3",
            },
            "oxidative stress",
        ]
    )

    assert normalized == [
        {
            "theme": "mitochondrial dysfunction",
            "description": "recurs across the reviewed pool",
            "frequency": "3",
            "sub_themes": [],
        },
        {
            "theme": "oxidative stress",
            "description": "",
            "frequency": "",
            "sub_themes": [],
        },
    ]


def test_normalize_tolerates_junk_in_the_nested_positions() -> None:
    normalized = normalize_recurring_themes(
        [
            {"theme": "t", "sub_themes": "not a list"},
            {
                "theme": "u",
                "sub_themes": ["a bare sub-theme", {"points": "not a list"}],
            },
        ]
    )

    assert normalized[0]["sub_themes"] == []
    assert normalized[1]["sub_themes"] == [
        {"theme": "a bare sub-theme", "description": "", "points": []},
        {"theme": "", "description": "", "points": []},
    ]


_BUDGET = Budget(max_iterations=4, max_llm_calls=7000)


def _due_stats(**overrides: object) -> SchedulerStats:
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 0,
        "rankable_count": 6,
        "total_matches": 12,
        "match_coverage": 2.0,
        "owed_coverage_rounds": 3,
        "iteration": 1,
        "iterations_since_meta_review": 1,
        "feedback_since_meta_review": 6,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_cadence_fires_when_enabled_and_due() -> None:
    decision = _check_meta_review_cadence(_due_stats())
    assert decision is not None
    assert decision.next_task is TaskType.META_REVIEW


def test_cadence_suppressed_when_disabled_even_though_due() -> None:
    assert (
        _check_meta_review_cadence(_due_stats(meta_review_enabled=False))
        is None
    )


def test_disabled_cadence_stacks_no_meta_review_companion() -> None:
    enabled = _due_stats(unreviewed_count=0)
    stacked = stack_companions(
        decide_next_task(enabled, _BUDGET), enabled, _BUDGET
    )
    assert TaskType.META_REVIEW.value in stacked_task_values(
        stacked.queue_actions
    )

    disabled = _due_stats(unreviewed_count=0, meta_review_enabled=False)
    stacked_off = stack_companions(
        decide_next_task(disabled, _BUDGET), disabled, _BUDGET
    )
    assert TaskType.META_REVIEW.value not in stacked_task_values(
        stacked_off.queue_actions
    )


def test_evolve_still_enters_meta_review_when_cadence_disabled() -> None:
    """Evolution still needs critique when periodic meta-review is disabled."""
    evolve = SupervisorDecision(
        next_task=TaskType.EVOLVE, reason="evolution out-yields generation"
    )
    stacked = stack_companions(
        evolve, _due_stats(meta_review_enabled=False), _BUDGET
    )
    assert not stacked_task_values(stacked.queue_actions)


def test_state_flag_threads_into_scheduler_stats() -> None:
    on = _compute_stats(make_state(), {})
    assert on.meta_review_enabled is True
    off = _compute_stats(make_state(enable_meta_review=False), {})
    assert off.meta_review_enabled is False


# Distinctive markers unlikely to appear in a template by accident.
_META_REVIEW_PROMPT_THREADING_STRENGTH = (
    "UNIQUEMARKER-strength-mitochondrial-coupling"
)
_META_REVIEW_PROMPT_THREADING_WEAKNESS = (
    "UNIQUEMARKER-weakness-blood-brain-barrier-permeability"
)
_META_REVIEW_PROMPT_THREADING_RECOMMENDATION = (
    "UNIQUEMARKER-recommendation-add-orthogonal-probe"
)

_META_REVIEW_PROMPT_THREADING_META_REVIEW = {
    "common_strengths": [_META_REVIEW_PROMPT_THREADING_STRENGTH],
    "common_weaknesses": [_META_REVIEW_PROMPT_THREADING_WEAKNESS],
    "strategic_recommendations": [_META_REVIEW_PROMPT_THREADING_RECOMMENDATION],
}


def _meta_review_prompt_threading_assert_critique_present(prompt: str) -> None:
    assert "Meta-Review Context" in prompt
    assert _META_REVIEW_PROMPT_THREADING_WEAKNESS in prompt
    assert _META_REVIEW_PROMPT_THREADING_STRENGTH in prompt
    assert _META_REVIEW_PROMPT_THREADING_RECOMMENDATION in prompt


def test_generation_debate_prompt_includes_meta_review() -> None:
    prompt, _ = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="Find a synthetic-lethal target",
            transcript="",
            context=PromptRunContext(
                meta_review=_META_REVIEW_PROMPT_THREADING_META_REVIEW
            ),
        )
    )
    _meta_review_prompt_threading_assert_critique_present(prompt)


def test_reflection_prompt_includes_meta_review() -> None:
    prompt, _ = get_reflection_prompt(
        articles_with_reasoning="Some prior work.",
        hypothesis_text="Inhibiting X reduces Y.",
        context=PromptRunContext(
            meta_review=_META_REVIEW_PROMPT_THREADING_META_REVIEW
        ),
    )
    _meta_review_prompt_threading_assert_critique_present(prompt)


def test_review_prompt_includes_meta_review() -> None:
    prompt, _ = get_review_prompt(
        research_goal="Find a synthetic-lethal target",
        hypothesis_text="Inhibiting X reduces Y.",
        context=PromptRunContext(
            meta_review=_META_REVIEW_PROMPT_THREADING_META_REVIEW
        ),
    )
    _meta_review_prompt_threading_assert_critique_present(prompt)


def test_review_batch_prompt_includes_meta_review() -> None:
    prompt, _ = get_review_batch_prompt(
        research_goal="Find a synthetic-lethal target",
        hypotheses_list="1. Inhibiting X reduces Y.\n2. Blocking Z helps.",
        context=PromptRunContext(
            meta_review=_META_REVIEW_PROMPT_THREADING_META_REVIEW
        ),
    )
    _meta_review_prompt_threading_assert_critique_present(prompt)


def test_empty_meta_review_adds_no_context_section() -> None:
    prompt, _ = get_review_prompt(
        research_goal="Find a synthetic-lethal target",
        hypothesis_text="Inhibiting X reduces Y.",
        context=PromptRunContext(meta_review=None),
    )
    assert "Meta-Review Context" not in prompt


# Distinctive markers unlikely to appear in a template by accident.
_META_REVIEW_SURFACE_THREADING_STRENGTH = (
    "UNIQUEMARKER-strength-mechanistic-clarity"
)
_META_REVIEW_SURFACE_THREADING_WEAKNESS = (
    "UNIQUEMARKER-weakness-unvalidated-target"
)
_META_REVIEW_SURFACE_THREADING_RECOMMENDATION = (
    "UNIQUEMARKER-recommendation-search-missing-evidence"
)

_META_REVIEW_SURFACE_THREADING_META_REVIEW = {
    "common_strengths": [_META_REVIEW_SURFACE_THREADING_STRENGTH],
    "common_weaknesses": [_META_REVIEW_SURFACE_THREADING_WEAKNESS],
    "strategic_recommendations": [
        _META_REVIEW_SURFACE_THREADING_RECOMMENDATION
    ],
}

_ARTICLES = "Article 1: observation A supports pathway X."


def _meta_review_surface_threading_assert_critique_present(prompt: str) -> None:
    assert "Meta-Review Context" in prompt
    assert _META_REVIEW_SURFACE_THREADING_STRENGTH in prompt
    assert _META_REVIEW_SURFACE_THREADING_WEAKNESS in prompt
    assert _META_REVIEW_SURFACE_THREADING_RECOMMENDATION in prompt


def _assert_empty_state(prompt: str) -> None:
    assert "Meta-Review Context" not in prompt
    assert "{{MISSING" not in prompt


def _stub_proximity_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"similarity_clusters": []}

    monkeypatch.setattr(proximity, "call_llm_json", fake)
    return calls


@pytest.mark.asyncio()
async def test_proximity_prompt_includes_meta_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_proximity_llm(monkeypatch)
    state = make_state(
        hypotheses=[
            make_hypothesis(text="Inhibiting X reduces Y."),
            make_hypothesis(text="Blocking Z helps."),
        ],
        meta_review=_META_REVIEW_SURFACE_THREADING_META_REVIEW,
    )

    await proximity_node(state)

    assert calls, "the proximity LLM call never ran"
    _meta_review_surface_threading_assert_critique_present(calls[0]["prompt"])


@pytest.mark.asyncio()
async def test_proximity_prompt_empty_state_without_meta_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_proximity_llm(monkeypatch)
    state = make_state(
        hypotheses=[
            make_hypothesis(text="Inhibiting X reduces Y."),
            make_hypothesis(text="Blocking Z helps."),
        ]
    )

    await proximity_node(state)

    assert calls, "the proximity LLM call never ran"
    _assert_empty_state(calls[0]["prompt"])


def test_query_generation_prompt_includes_meta_review() -> None:
    prompt = get_literature_review_query_generation_prompt(
        "Reverse liver fibrosis",
        meta_review=_META_REVIEW_SURFACE_THREADING_META_REVIEW,
    )
    _meta_review_surface_threading_assert_critique_present(prompt)


def test_query_generation_prompt_empty_state() -> None:
    prompt = get_literature_review_query_generation_prompt(
        "Reverse liver fibrosis"
    )
    _assert_empty_state(prompt)


def test_pubmed_query_generation_prompt_includes_meta_review() -> None:
    prompt = get_literature_review_query_generation_prompt(
        "Reverse liver fibrosis",
        source_type="pubmed",
        meta_review=_META_REVIEW_SURFACE_THREADING_META_REVIEW,
    )
    _meta_review_surface_threading_assert_critique_present(prompt)


def test_synthesis_prompt_includes_meta_review() -> None:
    prompt = get_literature_review_synthesis_prompt(
        "Reverse liver fibrosis",
        [],
        meta_review=_META_REVIEW_SURFACE_THREADING_META_REVIEW,
    )
    _meta_review_surface_threading_assert_critique_present(prompt)


def test_synthesis_prompt_empty_state() -> None:
    prompt = get_literature_review_synthesis_prompt(
        "Reverse liver fibrosis", []
    )
    _assert_empty_state(prompt)


@pytest.mark.asyncio()
async def test_safety_decisions_carry_meta_review_context() -> None:
    unsafe = make_hypothesis(
        "Weaponize engineered pathogens for maximum spread", id="bad-1"
    )
    state = make_state(
        hypotheses=[unsafe],
        meta_review=_META_REVIEW_SURFACE_THREADING_META_REVIEW,
    )
    result = await safety_screen_node(state)

    decision = result["safety_decisions"][0]
    assert decision["outcome"] == "prohibited"
    _meta_review_surface_threading_assert_critique_present(
        decision["meta_review_context"]
    )


@pytest.mark.asyncio()
async def test_safety_decisions_empty_state_without_meta_review() -> None:
    unsafe = make_hypothesis(
        "Weaponize engineered pathogens for maximum spread", id="bad-1"
    )
    state = make_state(hypotheses=[unsafe])
    result = await safety_screen_node(state)

    decision = result["safety_decisions"][0]
    assert decision["outcome"] == "prohibited"
    assert "meta_review_context" not in decision


def _policy_pool() -> list[Any]:
    """Already-screened hypotheses carry stamps and are skipped on later
    screens."""
    return [
        make_hypothesis(
            "CRISPR-Cas9 targeting of BRCA1 mutations in breast cancer",
            id="safe-1",
        ),
        make_hypothesis(
            "Weaponize engineered pathogens for maximum spread", id="bad-1"
        ),
    ]


@pytest.mark.asyncio()
async def test_meta_review_context_never_overrides_safety_policy() -> None:
    """A favorable critique must never loosen admission policy."""
    praising = {
        "common_strengths": ["the pathogen work is promising"],
        "strategic_recommendations": ["keep the pathogen direction"],
    }
    with_context = await safety_screen_node(
        make_state(hypotheses=_policy_pool(), meta_review=praising)
    )
    without_context = await safety_screen_node(
        make_state(hypotheses=_policy_pool())
    )

    assert with_context["hypotheses"] == without_context["hypotheses"]
    assert [d["outcome"] for d in with_context["safety_decisions"]] == [
        d["outcome"] for d in without_context["safety_decisions"]
    ]
    assert [d["hypothesis_id"] for d in with_context["safety_decisions"]] == [
        "bad-1"
    ]


@pytest.mark.asyncio()
async def test_observation_review_node_threads_meta_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = stub_call_llm_json(
        monkeypatch,
        reflection,
        {"classification": "neutral", "reasoning": "no signal"},
    )
    state = make_state(
        hypotheses=[make_hypothesis(text="Inhibiting X reduces Y.")],
        articles_with_reasoning=_ARTICLES,
        meta_review=_META_REVIEW_SURFACE_THREADING_META_REVIEW,
    )

    await reflection_node(state)

    assert calls, "the observation LLM call never ran"
    _meta_review_surface_threading_assert_critique_present(calls[0]["prompt"])


@pytest.mark.asyncio()
async def test_observation_review_node_empty_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = stub_call_llm_json(
        monkeypatch,
        reflection,
        {"classification": "neutral", "reasoning": "no signal"},
    )
    state = make_state(
        hypotheses=[make_hypothesis(text="Inhibiting X reduces Y.")],
        articles_with_reasoning=_ARTICLES,
    )

    await reflection_node(state)

    assert calls, "the observation LLM call never ran"
    _assert_empty_state(calls[0]["prompt"])


_META = {
    "common_weaknesses": ["ignores blood-brain-barrier permeability"],
    "strategic_recommendations": ["address BBB"],
}

_PROBES = [
    {
        "question": "Is CXCR1/2 inhibition sufficient alone?",
        "answer": "Likely needs combination therapy.",
        "reasoning": "AML bypasses single-target inhibition.",
        "assumption_is_fundamental": True,
    }
]


def test_reflection_prompt_includes_meta_review_when_present() -> None:
    prompt, _ = get_reflection_prompt(
        articles_with_reasoning="lit",
        hypothesis_text="H",
        context=PromptRunContext(meta_review=_META),
    )
    assert "blood-brain-barrier" in prompt


def test_reflection_prompt_omits_meta_review_when_empty() -> None:
    prompt, _ = get_reflection_prompt(
        articles_with_reasoning="lit",
        hypothesis_text="H",
        context=PromptRunContext(meta_review=None),
    )
    assert "blood-brain-barrier" not in prompt


def test_ranking_prompt_includes_meta_review_when_present() -> None:
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="A"),
        side_b=RankingSide(text="B"),
        context=PromptRunContext(meta_review=_META),
    )
    assert "blood-brain-barrier" in prompt


def test_ranking_prompt_omits_meta_review_when_empty() -> None:
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="A"),
        side_b=RankingSide(text="B"),
        context=PromptRunContext(meta_review=None),
    )
    assert "Meta-Review Context" not in prompt


def test_ranking_prompt_empty_optional_slots_are_byte_clean() -> None:
    """Whitespace changes alter iteration-one prompt hashes and cache keys."""
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="A"),
        side_b=RankingSide(text="B"),
        context=PromptRunContext(meta_review=None),
    )
    assert (
        'Reasoning and conclusion (end with "better hypothesis: <1 or 2>"):'
        "\n\n## Output Format" in prompt
    )
    assert "\n\n\n" not in prompt


def test_ranking_prompt_includes_deep_verification_when_present() -> None:
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(
            text="A",
            deep_verification={"probes": _PROBES, "verdict": "weakened"},
        ),
        side_b=RankingSide(text="B"),
    )
    assert "Deep Verification" in prompt
    assert "weakened" in prompt
    assert "Is CXCR1/2 inhibition sufficient alone?" in prompt
    assert "fundamental assumption" in prompt


def test_ranking_prompt_omits_deep_verification_when_empty() -> None:
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="A"),
        side_b=RankingSide(text="B"),
    )
    assert "Deep Verification" not in prompt


def test_emerging_themes_render_as_covered_areas() -> None:
    prompt = _format_meta_review_context(
        {"emerging_themes": ["mitochondrial dysfunction pathway"]}
    )
    assert "Research Areas Already Covered" in prompt
    assert "mitochondrial dysfunction pathway" in prompt


def test_emerging_themes_absent_when_empty() -> None:
    prompt = _format_meta_review_context({"common_strengths": ["x"]})
    assert "Research Areas Already Covered" not in prompt


def test_potential_connections_render_as_open_directions() -> None:
    prompt = _format_meta_review_context(
        {
            "potential_connections": [
                {
                    "connection_type": "complementary_mechanism",
                    "synthesis_opportunity": (
                        "combine autophagy and proteasome targeting"
                    ),
                }
            ]
        }
    )
    assert "Open Directions Flagged for Further Exploration" in prompt
    assert "complementary_mechanism" in prompt
    assert "combine autophagy and proteasome targeting" in prompt


def test_potential_connections_absent_when_empty() -> None:
    prompt = _format_meta_review_context({"common_strengths": ["x"]})
    assert "Open Directions Flagged for Further Exploration" not in prompt


def test_potential_connection_tolerates_partial_fields() -> None:
    prompt = _format_meta_review_context(
        {
            "potential_connections": [
                {"synthesis_opportunity": "only an opportunity, no type"}
            ]
        }
    )
    assert "only an opportunity, no type" in prompt


def test_potential_connection_tolerates_non_dict_entries() -> None:
    prompt = _format_meta_review_context(
        {"potential_connections": ["a bare string connection"]}
    )
    assert "a bare string connection" in prompt


def test_no_meta_review_renders_nothing() -> None:
    assert _format_meta_review_context(None) == ""
    assert _format_meta_review_context({}) == ""

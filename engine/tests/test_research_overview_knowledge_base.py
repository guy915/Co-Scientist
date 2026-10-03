"""Offline contracts for research overview knowledge base."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.meta_review import (
    research_overview_knowledge_base as kb,
)
from co_scientist.agents.meta_review import (
    research_overview_knowledge_base as kbc,
)
from co_scientist.agents.meta_review import research_overview_review as ror
from co_scientist.constants import (
    KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS,
    KNOWLEDGE_BASE_THEME_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.llm import ModelCallStats, record_call, scoped_telemetry
from co_scientist.prompts import (
    get_knowledge_base_outline_prompt,
    get_knowledge_base_theme_prompt,
)
from co_scientist.prompts.planning import ThemeWritingMaterial
from co_scientist.schemas.synthesis import (
    KNOWLEDGE_BASE_MAX_THEMES,
    KNOWLEDGE_BASE_OUTLINE_SCHEMA,
    KNOWLEDGE_BASE_PRINCIPAL_SECTION_WORDS,
    KNOWLEDGE_BASE_SECTION_WORDS,
    KNOWLEDGE_BASE_TARGET_SECTIONS,
    KNOWLEDGE_BASE_THEME_SCHEMA,
)
from tests._state import make_hypothesis, make_state
from tests.test_research_overview import (
    _RESEARCH_OVERVIEW_OVERVIEW_RESPONSE as _OVERVIEW_RESPONSE,
)
from tests.test_research_overview import (
    _research_overview_grounded_articles as _grounded_articles,
)

_RESEARCH_OVERVIEW_KNOWLEDGE_BASE_CORPUS: dict[str, dict[str, Any]] = {
    "evidence-1": {
        "evidence_id": "evidence-1",
        "source_id": "PMID:1",
        "title": "Stellate cell plasticity",
        "abstract": "Quiescent stellate cells store retinoids.",
        "source": "pubmed",
        "url": "",
    },
    "evidence-2": {
        "evidence_id": "evidence-2",
        "source_id": "PMID:2",
        "title": "Matrix cross-linking",
        "abstract": "LOXL2 stabilises fibrillar collagen.",
        "source": "pubmed",
        "url": "",
    },
}

_THEMED_RESPONSE: dict[str, Any] = {
    "themes": [
        {
            "title": "Hepatic Stellate Cell Plasticity",
            "sections": [
                {
                    "heading": "Quiescent And Activated States",
                    "detail": "Quiescent cells store retinoids; injury "
                    "drives transdifferentiation.",
                    "evidence_ids": ["evidence-1", "invented"],
                },
                {
                    "heading": "Ungrounded Section",
                    "detail": "No source stands behind this.",
                    "evidence_ids": ["invented"],
                },
            ],
        },
        {
            "title": "Extracellular Matrix Architecture",
            "sections": [
                {
                    "heading": "Cross-Linking Constraints",
                    "detail": "LOXL2 raises the denaturation temperature.",
                    "evidence_ids": ["evidence-2"],
                }
            ],
        },
    ]
}


_MATERIAL = ThemeWritingMaterial(
    title="Extracellular Matrix Architecture",
    sections="- Cross-Linking Constraints (evidence: evidence-2)",
    outline="## Extracellular Matrix Architecture",
)


def _research_overview_knowledge_base_funded_state(**overrides: Any) -> Any:
    """State for a tier whose ceiling pays for the extra call."""
    return make_state(
        research_goal="g",
        supervisor_model_name="test/model",
        budget={"max_iterations": 3, "max_llm_calls": 7000},
        **overrides,
    )


def test_the_cheapest_tier_does_not_fund_the_extra_call() -> None:
    """Express declares 1200 calls; the deep synthesis is not sold there."""
    express = make_state(budget={"max_iterations": 1, "max_llm_calls": 1200})
    assert not kb.knowledge_base_is_funded(express)


def test_a_run_that_declares_no_ceiling_does_not_fund_it() -> None:
    """No declared tier is not a licence to spend the largest call."""
    assert not kb.knowledge_base_is_funded(make_state())
    assert not kb.knowledge_base_is_funded(
        make_state(budget={"max_iterations": 2})
    )


def test_standard_and_above_fund_it() -> None:
    """The gate is the tier's declared ceiling, read inside this node."""
    standard = make_state(budget={"max_iterations": 2, "max_llm_calls": 2500})
    assert kb.knowledge_base_is_funded(standard)
    assert kb.knowledge_base_is_funded(
        _research_overview_knowledge_base_funded_state()
    )


def test_the_schema_never_echoes_the_evidence_pool_back() -> None:
    """Output length must not scale with the corpus offered to the prompt.

    The trap proximity clustering hit: a schema that names its input by
    repeating its text truncates identically on every retry.
    """
    for schema in (KNOWLEDGE_BASE_OUTLINE_SCHEMA, KNOWLEDGE_BASE_THEME_SCHEMA):
        text = str(schema)
        assert "abstract" not in text
        assert "title of the" not in text
        assert schema["schema"]["additionalProperties"] is False


def test_themed_sections_reach_the_topic_list_grounded() -> None:
    """Each written section becomes one topic carrying its theme and refs.

    The flattening the report renders from, asserted against the response
    shape directly: which calls produce that shape is the split pass's
    concern, next door.
    """
    topics = kb.validate_themes(
        _THEMED_RESPONSE["themes"], _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_CORPUS
    )

    assert [topic["theme"] for topic in topics] == [
        "Hepatic Stellate Cell Plasticity",
        "Extracellular Matrix Architecture",
    ]
    assert [topic["title"] for topic in topics] == [
        "Quiescent And Activated States",
        "Cross-Linking Constraints",
    ]
    assert topics[0]["references"][0]["title"] == "Stellate cell plasticity"
    assert "Ungrounded Section" not in str(topics)


def test_a_theme_beyond_the_readable_count_is_never_flattened_in() -> None:
    """The report reads eight themes and stops; json_object mode may not."""
    themes = [
        {
            "title": f"Theme {index}",
            "sections": _THEMED_RESPONSE["themes"][1]["sections"],
        }
        for index in range(KNOWLEDGE_BASE_MAX_THEMES + 3)
    ]

    topics = kb.validate_themes(
        themes, _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_CORPUS
    )

    assert (
        len({topic["theme"] for topic in topics}) == KNOWLEDGE_BASE_MAX_THEMES
    )


async def test_an_empty_corpus_never_spends_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing to synthesize from is not something to pay a model for."""
    fake = AsyncMock(return_value=_THEMED_RESPONSE)
    monkeypatch.setattr(kbc, "call_llm_json", fake)

    topics, calls = await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_funded_state(),
        "1. (Elo 1200) an idea",
        {},
    )

    assert (topics, calls) == ([], 0)
    assert fake.await_count == 0


def test_the_section_word_band_starts_at_the_exemplar_mean() -> None:
    """The old band's floor is what the model actually wrote.

    Measured 2026-09-07: the published exemplar's 43 subject sections
    average 218 words (median 196, eleven above 250, top 505); production
    run ``d1273490`` wrote 38 sections averaging 164 (median 162, none
    above 213) against a prompt naming "150-250". A band is a floor, not
    a target, so the floor is now the exemplar's own mean.
    """
    assert KNOWLEDGE_BASE_SECTION_WORDS[0] >= 200
    assert KNOWLEDGE_BASE_PRINCIPAL_SECTION_WORDS[1] >= 500
    assert KNOWLEDGE_BASE_TARGET_SECTIONS[0] >= 40


def test_the_prompt_and_the_schema_carry_the_same_targets() -> None:
    """One measurement, stated in both places a downgraded model reads.

    Under the json_object downgrade the schema's own field descriptions
    ride with the request beside the prompt, so a band written in one and
    not the other is two instructions disagreeing.
    """
    outline, _ = get_knowledge_base_outline_prompt(
        "goal", "1. an idea", "corpus"
    )
    theme, _ = get_knowledge_base_theme_prompt("goal", _MATERIAL, "corpus")
    detail = KNOWLEDGE_BASE_THEME_SCHEMA["schema"]["properties"]["sections"][
        "items"
    ]["properties"]["detail"]
    # The word bands ride with the writing call, which is the only one
    # asked for prose; the counts ride with the outline, which is the only
    # one that decides how many sections there are.
    for bound in (
        *KNOWLEDGE_BASE_SECTION_WORDS,
        *KNOWLEDGE_BASE_PRINCIPAL_SECTION_WORDS,
    ):
        assert str(bound) in theme
        assert str(bound) in detail["description"]
    for bound in KNOWLEDGE_BASE_TARGET_SECTIONS:
        assert str(bound) in outline
    # A section total with no theme count invites a ninth theme, which
    # validate_themes slices off in silence -- and the json_object
    # downgrade's array trim does it before the slice ever sees it.
    assert f"no more than {KNOWLEDGE_BASE_MAX_THEMES} themes" in outline


def test_the_prompt_asks_for_the_density_the_exemplar_carries() -> None:
    """Three content kinds the measured gap is made of.

    The exemplar names a dozen markers in one sentence, states every
    number with its unit, and devotes whole subsections to interventions
    that failed and findings that contradict each other. Ours asked for
    none of the three by name.
    """
    theme, _ = get_knowledge_base_theme_prompt("goal", _MATERIAL, "corpus")
    outline, _ = get_knowledge_base_outline_prompt(
        "goal", "1. an idea", "corpus"
    )
    lowered = f"{theme}\n{outline}".lower()
    assert "not two or three representatives" in lowered
    assert "unit" in lowered
    assert "boundary conditions" in lowered
    assert "failed" in lowered


def test_the_prompt_adds_no_citation_apparatus() -> None:
    """The span carries zero citations by design, mirroring the exemplar."""
    theme, _ = get_knowledge_base_theme_prompt("goal", _MATERIAL, "corpus")
    assert "no citation markers" in theme.lower()
    assert "no bullet lists" in theme.lower()


_ASKED = "Theme to write:"
"""The line naming which theme one writing call is responsible for."""

_RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS: dict[str, dict[str, Any]] = {
    "evidence-1": {
        "evidence_id": "evidence-1",
        "source_id": "PMID:1",
        "title": "Stellate cell plasticity",
        "abstract": "Quiescent stellate cells store retinoids.",
        "source": "pubmed",
        "url": "",
    },
    "evidence-2": {
        "evidence_id": "evidence-2",
        "source_id": "PMID:2",
        "title": "Matrix cross-linking",
        "abstract": "LOXL2 stabilises fibrillar collagen.",
        "source": "pubmed",
        "url": "",
    },
}

_OUTLINE: dict[str, Any] = {
    "themes": [
        {
            "title": "Hepatic Stellate Cell Plasticity",
            "sections": [
                {
                    "heading": "Quiescent And Activated States",
                    "evidence_ids": ["evidence-1"],
                },
                {
                    "heading": "Ungrounded Section",
                    "evidence_ids": ["invented"],
                },
            ],
        },
        {
            "title": "Extracellular Matrix Architecture",
            "sections": [
                {
                    "heading": "Cross-Linking Constraints",
                    "evidence_ids": ["evidence-2"],
                }
            ],
        },
    ]
}

_THEME_SECTIONS: dict[str, dict[str, Any]] = {
    "Hepatic Stellate Cell Plasticity": {
        "sections": [
            {
                "heading": "Quiescent And Activated States",
                "detail": "Quiescent cells store retinoids.",
                "evidence_ids": ["evidence-1"],
            },
            {
                "heading": "Ungrounded Section",
                "detail": "No source stands behind this.",
                "evidence_ids": ["invented"],
            },
        ]
    },
    "Extracellular Matrix Architecture": {
        "sections": [
            {
                "heading": "Cross-Linking Constraints",
                "detail": "LOXL2 raises the denaturation temperature.",
                "evidence_ids": ["evidence-2"],
            }
        ]
    },
}


def _research_overview_knowledge_base_split_funded_state(
    **overrides: Any,
) -> Any:
    """State for a tier whose ceiling pays for the extra calls."""
    return make_state(
        research_goal="g",
        supervisor_model_name="test/model",
        budget={"max_iterations": 3, "max_llm_calls": 7000},
        **overrides,
    )


class _Responder:
    """Answers each part call from the fixtures above, recording the specs."""

    def __init__(self, failing_theme: str | None = None) -> None:
        self.failing_theme = failing_theme
        self.specs: list[Any] = []
        self.options: list[Any] = []
        self.prompts: list[str] = []

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        spec = kwargs["spec"]
        self.specs.append(spec)
        self.options.append(kwargs.get("options"))
        prompt = kwargs["prompt"]
        self.prompts.append(prompt)
        assert spec.json_schema is not None
        if spec.json_schema["name"] == "knowledge_base_outline":
            return _OUTLINE
        asked = next(
            line for line in prompt.splitlines() if line.startswith(_ASKED)
        )
        theme = next(title for title in _THEME_SECTIONS if title in asked)
        if theme == self.failing_theme:
            raise RuntimeError("stream dropped")
        return _THEME_SECTIONS[theme]


async def test_the_synthesis_is_one_outline_call_plus_one_call_per_theme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No single call can carry the section, so it is not asked to.

    The count is the whole cost argument. A full-size outline is eight
    themes, so this pass costs at most nine requests where it used to cost
    one: run ``e47a3ba1`` spent 291 LLM calls against standard's declared
    2,500, so the eight extra are 0.32% of that ceiling (0.11% of
    extended's 7,000) for a section that otherwise publishes nothing.
    """
    responder = _Responder()
    monkeypatch.setattr(kbc, "call_llm_json", responder)

    topics, calls = await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_split_funded_state(),
        "1. (Elo 1200) an idea",
        _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
    )

    assert calls == 1 + len(_OUTLINE["themes"])
    assert len(responder.specs) == calls
    assert topics


async def test_no_part_asks_for_more_output_than_the_clock_can_serve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every part is sized at or under an ordinary thinking call's budget.

    The 42,000-token ask was ~1,100-1,500s of generation at the throughput
    its own failing attempts measured, against a 600s per-call ceiling. The
    bound that matters is therefore not "does the model advertise this
    output size" but "can it be written inside one call", and the budget
    this deployment has actually proven is the thinking floor.
    """
    responder = _Responder()
    monkeypatch.setattr(kbc, "call_llm_json", responder)

    await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_split_funded_state(),
        "1. (Elo 1200) an idea",
        _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
    )

    assert KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS < KNOWLEDGE_BASE_THEME_MAX_TOKENS
    for spec in responder.specs:
        assert spec.max_tokens <= THINKING_FLOOR_MAX_TOKENS


async def test_every_part_bounds_its_own_chain_of_thought(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reasoning spent the whole clock and wrote nothing; it is bounded now.

    All three failed attempts of run ``e47a3ba1`` came back with
    ``completion_tokens == reasoning_tokens`` -- 10,080 to 20,949 tokens of
    chain of thought and not one answer token. Asking not to think is what
    reaches ``_minimal_reasoning_knob`` on this chain, which sends an
    explicit ``MINIMAL_REASONING_MAX_TOKENS`` bound rather than a disable
    the endpoint rejects.
    """
    responder = _Responder()
    monkeypatch.setattr(kbc, "call_llm_json", responder)

    await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_split_funded_state(),
        "1. (Elo 1200) an idea",
        _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
    )

    assert responder.options
    for options in responder.options:
        assert options is not None
        assert options.enable_thinking is False


async def test_the_assembled_topics_keep_the_outline_order_and_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parts reassemble into the same topic list the one call produced."""
    responder = _Responder()
    monkeypatch.setattr(kbc, "call_llm_json", responder)

    topics, _ = await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_split_funded_state(),
        "1. (Elo 1200) an idea",
        _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
    )

    assert [topic["theme"] for topic in topics] == [
        "Hepatic Stellate Cell Plasticity",
        "Extracellular Matrix Architecture",
    ]
    assert [topic["title"] for topic in topics] == [
        "Quiescent And Activated States",
        "Cross-Linking Constraints",
    ]
    assert [topic["id"] for topic in topics] == ["topic-1", "topic-2"]
    assert topics[0]["references"][0]["title"] == "Stellate cell plasticity"
    assert "Ungrounded Section" not in str(topics)


async def test_a_theme_that_does_not_answer_drops_only_its_own_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One dropped stream must not cancel the themes written beside it."""
    responder = _Responder(failing_theme="Hepatic Stellate Cell Plasticity")
    monkeypatch.setattr(kbc, "call_llm_json", responder)

    topics, calls = await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_split_funded_state(),
        "1. (Elo 1200) an idea",
        _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
    )

    assert calls == 1 + len(_OUTLINE["themes"])
    assert [topic["theme"] for topic in topics] == [
        "Extracellular Matrix Architecture"
    ]


async def test_a_failed_outline_never_spends_the_writing_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing to write from is not something to pay eight models for."""
    fake = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(kbc, "call_llm_json", fake)

    topics, calls = await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_split_funded_state(),
        "1. (Elo 1200) an idea",
        _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
    )

    assert (topics, calls) == ([], 1)
    assert fake.await_count == 1


@pytest.mark.parametrize(
    "outline",
    [
        {"themes": []},
        # A theme with no usable sections buys a writing call with nothing
        # to write, on a chain capped at ~100 requests per model per day.
        {"themes": [{"title": "Empty Theme", "sections": []}]},
    ],
)
async def test_an_outline_with_no_themes_stops_before_the_writing_calls(
    outline: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An answered-but-empty outline is the same dead end as a failed one."""
    fake = AsyncMock(return_value=outline)
    monkeypatch.setattr(kbc, "call_llm_json", fake)

    topics, calls = await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_split_funded_state(),
        "1. (Elo 1200) an idea",
        _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
    )

    assert (topics, calls) == ([], 1)
    assert fake.await_count == 1


async def test_a_writer_that_cites_nothing_falls_back_to_the_outline_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outline already chose the sources; a silent writer keeps them.

    Splitting the call splits the grounding decision away from the prose,
    so a writer that omits ``evidence_ids`` would drop a section the
    outline had grounded perfectly well -- the section is dropped for
    citing nothing, which reads as a thin corpus rather than a lost field.
    """

    async def responder(**kwargs: Any) -> dict[str, Any]:
        spec = kwargs["spec"]
        assert spec.json_schema is not None
        if spec.json_schema["name"] == "knowledge_base_outline":
            return {
                "themes": [
                    {
                        "title": "Extracellular Matrix Architecture",
                        "sections": [
                            {
                                "heading": "Cross-Linking Constraints",
                                "evidence_ids": ["evidence-2"],
                            }
                        ],
                    }
                ]
            }
        return {
            "sections": [
                {
                    "heading": "Cross-Linking Constraints",
                    "detail": "LOXL2 raises the denaturation temperature.",
                }
            ]
        }

    monkeypatch.setattr(kbc, "call_llm_json", responder)

    topics, _ = await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_split_funded_state(),
        "1. (Elo 1200) an idea",
        _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
    )

    assert [topic["title"] for topic in topics] == ["Cross-Linking Constraints"]
    assert topics[0]["references"][0]["title"] == "Matrix cross-linking"


async def test_each_writer_is_shown_the_whole_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Writers that cannot see each other's headings write the same section."""
    responder = _Responder()
    monkeypatch.setattr(kbc, "call_llm_json", responder)

    await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_split_funded_state(),
        "1. (Elo 1200) an idea",
        _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
    )

    for prompt in responder.prompts[1:]:
        for title in _THEME_SECTIONS:
            assert title in prompt


async def test_the_parts_are_attributed_to_their_own_telemetry_sub_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nine calls inside one node must not hide the tenth's own usage.

    Telemetry is folded per (phase, model) and the phase is the durable
    task name, so before this the outline and every theme landed in the
    same bucket as the research-overview draft they run beside -- and
    nothing logs a single call's tokens on the success path, so that
    bucket is the only record a production run leaves. The draft's own
    budget was reasoned about rather than measured for exactly this
    reason.
    """
    responder = _Responder()

    async def _recording(**kwargs: Any) -> dict[str, Any]:
        record_call("test/model", ModelCallStats(calls=1))
        return await responder(**kwargs)

    monkeypatch.setattr(kbc, "call_llm_json", _recording)

    with scoped_telemetry("research_overview") as accumulator:
        record_call("test/model", ModelCallStats(calls=1))
        _, calls = await kb.synthesize_knowledge_base(
            _research_overview_knowledge_base_split_funded_state(),
            "1. (Elo 1200) an idea",
            _RESEARCH_OVERVIEW_KNOWLEDGE_BASE_SPLIT_CORPUS,
        )

    snapshot = accumulator.snapshot()
    assert snapshot["research_overview::test/model"]["calls"] == 1
    assert (
        snapshot["research_overview.knowledge_base::test/model"]["calls"]
        == calls
    )


_DRAFT: dict[str, Any] = {
    "overview": {"summary": "Original summary.", "research_directions": []},
    "nih_specific_aims": {"disease_description": "i", "aims": []},
    "research_contacts": [],
    "knowledge_base": [],
}


def _revised(summary: str) -> dict[str, Any]:
    """A reviser response identical to ``_DRAFT`` but for the summary."""
    return {
        "overview": {"summary": summary, "research_directions": []},
        "nih_specific_aims": {"disease_description": "i", "aims": []},
        "research_contacts": [],
        "knowledge_base": [],
    }


def _reject(location: str = "overview.summary") -> dict[str, Any]:
    return {
        "accept": False,
        "notes": [{"location": location, "issue": "Unsupported claim."}],
    }


async def _run_loop(
    state: Any, draft: dict[str, Any] = _DRAFT
) -> tuple[dict[str, Any], dict[str, Any], int]:
    context = ror.OverviewReviewContext(
        state=state,
        research_goal="g",
        hypotheses_summary="1. (Elo 1600) h",
        contact_candidates_text="No verified literature authors available.",
        evidence_corpus_text="No verified evidence corpus available.",
    )
    return await ror.review_research_overview(context, draft)


async def test_accept_first_time_runs_no_reviser_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first-pass accept costs one call and leaves the draft untouched."""
    fake = AsyncMock(return_value={"accept": True})
    monkeypatch.setattr(ror, "call_llm_json", fake)

    state = make_state(supervisor_model_name="test/model")
    final, meta, calls = await _run_loop(state)

    assert fake.await_count == 1
    assert final is _DRAFT
    assert meta == {"reviewed": False, "rounds": 0}
    assert calls == 1


async def test_a_revision_round_changes_the_published_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejection followed by acceptance publishes the revised prose."""
    revised = _revised("Corrected, hedged summary.")
    fake = AsyncMock(side_effect=[_reject(), revised, {"accept": True}])
    monkeypatch.setattr(ror, "call_llm_json", fake)

    state = make_state(supervisor_model_name="test/model")
    final, meta, calls = await _run_loop(state)

    assert fake.await_count == 3
    assert final["overview"]["summary"] == "Corrected, hedged summary."
    assert final["overview"]["summary"] != _DRAFT["overview"]["summary"]
    assert meta == {"reviewed": True, "rounds": 1}
    assert calls == 3


async def test_the_cycle_cap_holds_when_the_reviewer_objects_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer is asked at most twice; the last revision publishes."""
    second_revision = _revised("Second revision.")
    fake = AsyncMock(
        side_effect=[
            _reject("overview.summary"),
            _revised("First revision."),
            _reject("aims[0]"),
            second_revision,
        ]
    )
    monkeypatch.setattr(ror, "call_llm_json", fake)

    state = make_state(supervisor_model_name="test/model")
    final, meta, calls = await _run_loop(state)

    # Two review calls, two revise calls -- no third review call spent on
    # a verdict that could not change the outcome.
    assert fake.await_count == 4
    assert calls == 4
    assert final["overview"]["summary"] == "Second revision."
    assert meta == {"reviewed": True, "rounds": 2}


_DIRECTIONS = len(_OVERVIEW_RESPONSE["overview"]["research_directions"])
"""Directions the canned draft names, each bought its own writing call."""


def _base_state(**overrides: Any) -> Any:
    h = make_hypothesis(
        text="HDAC inhibition reverses fibrosis", elo_rating=1700
    )
    return make_state(
        hypotheses=[h],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=_grounded_articles(),
        **overrides,
    )


async def test_review_disabled_by_default_skips_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``enable_overview_review`` flag means the loop never runs."""
    synth = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", synth)
    loop = AsyncMock(side_effect=AssertionError("loop must not run"))
    monkeypatch.setattr(ro, "review_research_overview", loop)

    out = await ro.research_overview_node(_base_state())

    loop.assert_not_awaited()
    assert out["research_overview"]["overview_review"] == {
        "reviewed": False,
        "rounds": 0,
    }
    # Two calls: the draft, plus the one call that develops its single
    # drafted direction (research_overview_direction_calls).
    assert out["metrics"].llm_calls == 2


async def test_a_review_round_changes_the_published_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revision the loop returns is what actually publishes."""
    synth = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", synth)
    revised = {
        **_OVERVIEW_RESPONSE,
        "overview": {
            **_OVERVIEW_RESPONSE["overview"],
            "summary": "Corrected, hedged summary.",
        },
    }
    loop = AsyncMock(return_value=(revised, {"reviewed": True, "rounds": 1}, 3))
    monkeypatch.setattr(ro, "review_research_overview", loop)

    out = await ro.research_overview_node(
        _base_state(enable_overview_review=True)
    )

    loop.assert_awaited_once()
    assert (
        out["research_overview"]["overview"]["summary"]
        == "Corrected, hedged summary."
    )
    assert out["research_overview"]["overview_review"] == {
        "reviewed": True,
        "rounds": 1,
    }
    # One synthesis call, the three the loop reports spending, and one
    # per drafted direction developed afterwards.
    assert out["metrics"].llm_calls == 4 + _DIRECTIONS


async def test_an_exception_in_the_review_loop_publishes_the_original_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A report that fails to publish is worse than one that is unreviewed.

    Any exception in the review loop must degrade to the drafted overview
    exactly as synthesized -- never raise out of the node.
    """
    synth = AsyncMock(return_value=_OVERVIEW_RESPONSE)
    monkeypatch.setattr(ro, "call_llm_json", synth)
    loop = AsyncMock(side_effect=RuntimeError("provider exploded"))
    monkeypatch.setattr(ro, "review_research_overview", loop)

    out = await ro.research_overview_node(
        _base_state(enable_overview_review=True)
    )

    loop.assert_awaited_once()
    assert out["research_overview"]["overview"]["summary"] == "S"
    assert out["research_overview"]["overview_review"] == {
        "reviewed": False,
        "rounds": 0,
    }
    # Two calls: the draft, plus the one call that develops its single
    # drafted direction (research_overview_direction_calls).
    assert out["metrics"].llm_calls == 2

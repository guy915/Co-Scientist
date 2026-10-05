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

_MATERIAL = ThemeWritingMaterial(
    title="Extracellular Matrix Architecture",
    sections="- Cross-Linking Constraints (evidence: evidence-2)",
    outline="## Extracellular Matrix Architecture",
)


def _research_overview_knowledge_base_funded_state(**overrides: Any) -> Any:
    return make_state(
        research_goal="g",
        supervisor_model_name="test/model",
        budget={"max_iterations": 3, "max_llm_calls": 7000},
        **overrides,
    )


@pytest.mark.parametrize(
    ("budget", "funded"),
    [
        ({"max_iterations": 1, "max_llm_calls": 1200}, False),
        ({"max_iterations": 2}, False),
        (None, False),
        ({"max_iterations": 2, "max_llm_calls": 2500}, True),
        ({"max_iterations": 3, "max_llm_calls": 7000}, True),
    ],
    ids=["express", "no-call-ceiling", "no-ceiling", "standard", "deep"],
)
def test_only_standard_and_deeper_runs_fund_the_knowledge_base_calls(
    budget: dict[str, int] | None, funded: bool
) -> None:
    state = make_state() if budget is None else make_state(budget=budget)

    assert kb.knowledge_base_is_funded(state) is funded


async def test_an_empty_corpus_never_spends_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = AsyncMock(return_value=_OUTLINE)
    monkeypatch.setattr(kbc, "call_llm_json", fake)

    result = await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_funded_state(),
        "1. (Elo 1200) an idea",
        {},
    )

    assert result == ([], 0)
    assert fake.await_count == 0


def test_the_prompt_and_the_schema_carry_the_same_targets() -> None:
    """Downgraded models read prompt and schema descriptions side by side."""
    outline, _ = get_knowledge_base_outline_prompt(
        "goal", "1. an idea", "corpus"
    )
    theme, _ = get_knowledge_base_theme_prompt("goal", _MATERIAL, "corpus")
    detail = KNOWLEDGE_BASE_THEME_SCHEMA["schema"]["properties"]["sections"][
        "items"
    ]["properties"]["detail"]
    # Writers need prose bands; only the outline controls section counts.
    for bound in (
        *KNOWLEDGE_BASE_SECTION_WORDS,
        *KNOWLEDGE_BASE_PRINCIPAL_SECTION_WORDS,
    ):
        assert str(bound) in theme
        assert str(bound) in detail["description"]
    for bound in KNOWLEDGE_BASE_TARGET_SECTIONS:
        assert str(bound) in outline
    # Extra themes may be silently trimmed before validation.
    assert f"no more than {KNOWLEDGE_BASE_MAX_THEMES} themes" in outline


_ASKED = "Theme to write:"
"""The line naming which theme one writing call is responsible for."""

_CORPUS: dict[str, dict[str, Any]] = {
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


class _Responder:
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


async def _synthesize(
    monkeypatch: pytest.MonkeyPatch, responder: Any
) -> tuple[list[dict[str, Any]], int]:
    monkeypatch.setattr(kbc, "call_llm_json", responder)
    return await kb.synthesize_knowledge_base(
        _research_overview_knowledge_base_funded_state(),
        "1. (Elo 1200) an idea",
        _CORPUS,
    )


async def test_the_synthesis_is_one_bounded_outline_call_plus_one_per_theme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Advertised output capacity can exceed what the per-call clock can serve,
    and unbounded reasoning can spend the clock without writing an answer."""
    responder = _Responder()

    topics, calls = await _synthesize(monkeypatch, responder)

    assert calls == 1 + len(_OUTLINE["themes"])
    assert len(responder.specs) == calls
    assert KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS < KNOWLEDGE_BASE_THEME_MAX_TOKENS
    assert all(
        spec.max_tokens <= THINKING_FLOOR_MAX_TOKENS for spec in responder.specs
    )
    assert all(
        options is not None and options.enable_thinking is False
        for options in responder.options
    )
    for prompt in responder.prompts[1:]:
        assert all(title in prompt for title in _THEME_SECTIONS)
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


async def test_a_theme_beyond_the_readable_count_is_never_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = {"heading": "Cross-Linking", "evidence_ids": ["evidence-2"]}
    outline = {
        "themes": [
            {"title": f"Theme {index}", "sections": [section]}
            for index in range(KNOWLEDGE_BASE_MAX_THEMES + 3)
        ]
    }
    writer = {
        "sections": [{"heading": "Cross-Linking", "detail": "LOXL2 binds."}]
    }

    async def responder(**kwargs: Any) -> dict[str, Any]:
        return (
            outline
            if kwargs["spec"].json_schema["name"] == "knowledge_base_outline"
            else writer
        )

    topics, calls = await _synthesize(monkeypatch, responder)

    assert calls == 1 + KNOWLEDGE_BASE_MAX_THEMES
    assert (
        len({topic["theme"] for topic in topics}) == KNOWLEDGE_BASE_MAX_THEMES
    )


async def test_a_theme_that_does_not_answer_drops_only_its_own_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topics, calls = await _synthesize(
        monkeypatch,
        _Responder(failing_theme="Hepatic Stellate Cell Plasticity"),
    )

    assert calls == 1 + len(_OUTLINE["themes"])
    assert [topic["theme"] for topic in topics] == [
        "Extracellular Matrix Architecture"
    ]


@pytest.mark.parametrize(
    "outline",
    [
        RuntimeError("boom"),
        {"themes": []},
        {"themes": [{"title": "Empty Theme", "sections": []}]},
    ],
    ids=["failed", "no-themes", "no-sections"],
)
async def test_an_unusable_outline_never_spends_the_writing_calls(
    outline: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = AsyncMock(
        side_effect=outline if isinstance(outline, Exception) else None,
        return_value=outline,
    )

    topics, calls = await _synthesize(monkeypatch, fake)

    assert (topics, calls) == ([], 1)
    assert fake.await_count == 1


async def test_a_writer_that_cites_nothing_falls_back_to_the_outline_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Splitting grounding and prose must not lose the outline-selected
    evidence."""
    section = {"heading": "Cross-Linking Constraints"}
    outline = {
        "themes": [
            {
                "title": "Extracellular Matrix Architecture",
                "sections": [{**section, "evidence_ids": ["evidence-2"]}],
            }
        ]
    }
    writer = {"sections": [{**section, "detail": "LOXL2 raises the Tm."}]}

    async def responder(**kwargs: Any) -> dict[str, Any]:
        named = kwargs["spec"].json_schema["name"]
        return outline if named == "knowledge_base_outline" else writer

    topics, _ = await _synthesize(monkeypatch, responder)

    assert [topic["title"] for topic in topics] == ["Cross-Linking Constraints"]
    assert topics[0]["references"][0]["title"] == "Matrix cross-linking"


async def test_the_parts_are_attributed_to_their_own_telemetry_sub_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase-folded telemetry otherwise hides outline and writer costs."""
    responder = _Responder()

    async def _recording(**kwargs: Any) -> dict[str, Any]:
        record_call("test/model", ModelCallStats(calls=1))
        return await responder(**kwargs)

    with scoped_telemetry("research_overview") as accumulator:
        record_call("test/model", ModelCallStats(calls=1))
        _, calls = await _synthesize(monkeypatch, _recording)

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
    assert out["metrics"].llm_calls == 2


async def test_a_review_round_changes_the_published_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert out["metrics"].llm_calls == 4 + _DIRECTIONS


async def test_an_exception_in_the_review_loop_publishes_the_original_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review failure must degrade to the draft rather than prevent
    publication."""
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
    assert out["metrics"].llm_calls == 2

"""F8: the Knowledge Base is synthesized by its own call, at published depth.

Google's published MASH Knowledge Base runs 9,702 words over 43 named
subject headings grouped under themed sections
(``references/.../research-overviews/mash-liver-fibrosis-reversal-
therapeutic-hypothesis.md``); one measured production report
(run ``f8db4d04``) rendered 2,079 words over 8 flat topics -- 4.7x
shorter, with no thematic grouping at all.

The *structure* was not a prompt-wording problem: the overview draft
already spends ~15.9k of its 24,000-token ceiling, and the published span
alone measures 19,084 tokens (cl100k). So the depth is bought with a
*second* call carrying its own budget, gated to the tiers whose ceiling
can pay for it, and degrading to the overview call's own flat topics
wherever it is not funded or does not answer.

The *depth inside* that structure was. Re-measured on run ``d1273490``
(2026-09-07): 8 themes and 38 sections, but 6,245 words to the exemplar's
9,387, with no section above 213 words against eleven of the exemplar's
above 250 -- an answer of ~11k tokens against a 42,000-token ceiling, so
what bounded it was the ask. The tests below assert both: the shape of
the call (gated, never echoing its input pool, grounded, degrading
visibly), and that the targets it asks for are the measured ones and are
stated identically in the prompt and in the schema a downgraded model
reads beside it.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import (
    research_overview_knowledge_base as kb,
)
from co_scientist.constants import (
    KNOWLEDGE_BASE_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.prompts import get_knowledge_base_prompt
from co_scientist.schemas.knowledge_base import (
    KNOWLEDGE_BASE_PRINCIPAL_SECTION_WORDS,
    KNOWLEDGE_BASE_SCHEMA,
    KNOWLEDGE_BASE_SECTION_WORDS,
    KNOWLEDGE_BASE_TARGET_SECTIONS,
)
from co_scientist.schemas.synthesis import KNOWLEDGE_BASE_MAX_THEMES
from tests._state import make_state

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


def _funded_state(**overrides: Any) -> Any:
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
    assert kb.knowledge_base_is_funded(_funded_state())


def test_the_schema_never_echoes_the_evidence_pool_back() -> None:
    """Output length must not scale with the corpus offered to the prompt.

    The trap proximity clustering hit: a schema that names its input by
    repeating its text truncates identically on every retry.
    """
    text = str(KNOWLEDGE_BASE_SCHEMA)
    assert "abstract" not in text
    assert "title of the" not in text
    assert KNOWLEDGE_BASE_SCHEMA["schema"]["additionalProperties"] is False


def test_the_budget_funds_the_thinking_floor_and_the_measured_answer() -> None:
    """The published span measures 19,084 tokens; the floor is 18,000.

    Read from the constant rather than restated, so a later change to the
    thinking floor moves this bound with it.
    """
    assert KNOWLEDGE_BASE_MAX_TOKENS >= THINKING_FLOOR_MAX_TOKENS + 19084


async def test_themed_sections_reach_the_topic_list_grounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each section becomes one topic carrying its theme and references."""
    fake = AsyncMock(return_value=_THEMED_RESPONSE)
    monkeypatch.setattr(kb, "call_llm_json", fake)

    topics, calls = await kb.synthesize_knowledge_base(
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
    )

    assert calls == 1
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


async def test_the_call_is_sized_from_its_own_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second call carries its own ceiling, not the overview's."""
    fake = AsyncMock(return_value=_THEMED_RESPONSE)
    monkeypatch.setattr(kb, "call_llm_json", fake)

    await kb.synthesize_knowledge_base(
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
    )

    assert fake.await_args is not None
    spec = fake.await_args.kwargs["spec"]
    assert spec.max_tokens == KNOWLEDGE_BASE_MAX_TOKENS


async def test_an_empty_corpus_never_spends_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing to synthesize from is not something to pay a model for."""
    fake = AsyncMock(return_value=_THEMED_RESPONSE)
    monkeypatch.setattr(kb, "call_llm_json", fake)

    topics, calls = await kb.synthesize_knowledge_base(
        _funded_state(), "1. (Elo 1200) an idea", {}
    )

    assert (topics, calls) == ([], 0)
    assert fake.await_count == 0


async def test_a_failed_call_leaves_the_flat_topics_standing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A report carrying a shallower section beats a report that fails."""
    monkeypatch.setattr(
        kb, "call_llm_json", AsyncMock(side_effect=RuntimeError("boom"))
    )

    topics, calls = await kb.synthesize_knowledge_base(
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
    )

    assert topics == []
    assert calls == 1


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
    prompt, _ = get_knowledge_base_prompt("goal", "1. an idea", "corpus")
    detail = KNOWLEDGE_BASE_SCHEMA["schema"]["properties"]["themes"]["items"][
        "properties"
    ]["sections"]["items"]["properties"]["detail"]
    for bound in (
        *KNOWLEDGE_BASE_SECTION_WORDS,
        *KNOWLEDGE_BASE_PRINCIPAL_SECTION_WORDS,
    ):
        assert str(bound) in prompt
        assert str(bound) in detail["description"]
    for bound in KNOWLEDGE_BASE_TARGET_SECTIONS:
        assert str(bound) in prompt
    # A section total with no theme count invites a ninth theme, which
    # validate_themes slices off in silence -- and the json_object
    # downgrade's array trim does it before the slice ever sees it.
    assert f"no more than {KNOWLEDGE_BASE_MAX_THEMES} themes" in prompt


def test_the_prompt_asks_for_the_density_the_exemplar_carries() -> None:
    """Three content kinds the measured gap is made of.

    The exemplar names a dozen markers in one sentence, states every
    number with its unit, and devotes whole subsections to interventions
    that failed and findings that contradict each other. Ours asked for
    none of the three by name.
    """
    prompt, _ = get_knowledge_base_prompt("goal", "1. an idea", "corpus")
    lowered = prompt.lower()
    assert "not two or three representatives" in lowered
    assert "unit" in lowered
    assert "boundary conditions" in lowered
    assert "failed" in lowered


def test_the_prompt_adds_no_citation_apparatus() -> None:
    """The span carries zero citations by design, mirroring the exemplar."""
    prompt, _ = get_knowledge_base_prompt("goal", "1. an idea", "corpus")
    assert "no citation markers" in prompt.lower()
    assert "no bullet lists" in prompt.lower()

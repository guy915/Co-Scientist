"""F8: the Knowledge Base is assembled from parts, because the clock is short.

The single 42,000-token call this replaces failed in three consecutive
production runs and never once answered. The reason is not a model output
ceiling -- ``minimax/minimax-m3:free`` advertises 943,718 completion
tokens, and only the ``google/gemma-4-31b-it:free`` fallback rung declares
less (32,768) than the call asked for. It is the wall clock:
``COSCIENTIST_LLM_TIMEOUT_SECONDS`` bounds one call at 600s, the failing
attempts measured 27-37 tokens/second (10,080 tokens in 366s, 20,949 in
563s), and 42,000 tokens at that rate needs 1,100-1,500s. Both runs ended
the retry loop on ``LLMTimeoutError`` -- the engine's own ceiling, not
provider weather -- and the upstream had already dropped the stream itself
at 366-563s on the attempts before it.

The section that has to come out of that call is ~20,000 tokens. The
largest *answer* any call produced in either run was 7,644 tokens
(meta-review, run ``bc77950f``), so no single call on this chain can
deliver the Knowledge Base whatever budget it is handed. It is therefore
outlined once and written one theme at a time, and these pin what that
buys: parts sized under a budget this deployment has proven, a bounded
chain of thought so reasoning cannot spend the clock before a word is
written, an assembly that preserves the outline's own order, and the flat
fallback still standing when a part does not answer.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.meta_review import (
    research_overview_knowledge_base as kb,
)
from co_scientist.agents.meta_review import (
    research_overview_knowledge_base_calls as kbc,
)
from co_scientist.constants import (
    KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS,
    KNOWLEDGE_BASE_THEME_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.llm import ModelCallStats, record_call, scoped_telemetry
from tests._state import make_state

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


def _funded_state(**overrides: Any) -> Any:
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
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
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
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
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
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
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
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
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
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
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
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
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
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
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
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
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
        _funded_state(), "1. (Elo 1200) an idea", _CORPUS
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
            _funded_state(), "1. (Elo 1200) an idea", _CORPUS
        )

    snapshot = accumulator.snapshot()
    assert snapshot["research_overview::test/model"]["calls"] == 1
    assert (
        snapshot["research_overview.knowledge_base::test/model"]["calls"]
        == calls
    )

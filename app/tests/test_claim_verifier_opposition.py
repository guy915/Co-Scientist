"""Semantic opposition through the public assessor and completion boundaries."""

from __future__ import annotations

import json
import types
from typing import Any

import litellm
import pytest
from co_scientist.cache import scoped_cache_override
from litellm.exceptions import RateLimitError

from app.claim_verifier import make_llm_assessor
from app.claims import EntailmentLabel, EvidencePassage, assess_claim

CLAIM = "Kinase X inhibition reduces tumor growth in AML cells."
QUOTE = "Kinase X inhibition increased tumor growth threefold in AML cells."


def install_replies(
    monkeypatch: pytest.MonkeyPatch, replies: list[Any]
) -> list[Any]:
    requests: list[Any] = []

    async def completion(**kwargs: Any) -> Any:
        requests.append(kwargs)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=json.dumps(reply))
                )
            ]
        )

    monkeypatch.setattr(litellm, "acompletion", completion)
    return requests


def draft(quote: str = QUOTE, passage: int = 1) -> dict[str, Any]:
    return {
        "label": "contradicts",
        "supporting": [],
        "contradicting": [{"passage": passage, "quote": quote}],
    }


def confirmation(index: int = 1, **kwargs: Any) -> dict[str, Any]:
    return {
        "index": index,
        "same_conditions": True,
        "mutually_exclusive": True,
        **kwargs,
    }


def test_directional_opposition_is_verified_and_located(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = install_replies(
        monkeypatch, [draft(), {"verdicts": [confirmation()]}]
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.CONTRADICTS
    assert result.verification_method == "model_opposition_verified"
    assert result.contradicting_passages[0].quote == QUOTE
    assert result.contradicting_passages[0].evidence_id == "ev-1"
    assert len(requests) == 2


def test_verified_opposition_preserves_numeric_source_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_replies(monkeypatch, [draft(), {"verdicts": [confirmation()]}])
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("12345", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.CONTRADICTS
    assert [s.evidence_id for s in result.contradicting_passages] == ["12345"]


def test_empty_verification_envelope_retries_before_confirming_opposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = install_replies(
        monkeypatch,
        [draft(), {}, {"verdicts": [confirmation()]}],
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.CONTRADICTS
    assert result.verification_method == "model_opposition_verified"
    assert len(requests) == 3


def test_batch_verifies_multiple_oppositions_in_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.claim_verifier_batch import make_llm_batch_assessor
    from app.claims import assess_claims_batch

    second_claim = "Drug A increases progression-free survival."
    second_quote = (
        "Drug A shortened progression-free survival from 9.2 to 6.1 months."
    )
    requests = install_replies(
        monkeypatch,
        [
            {
                "verdicts": [
                    {"index": 1, **draft()},
                    {"index": 2, **draft(second_quote, passage=2)},
                ]
            },
            {"verdicts": [confirmation(2), confirmation(1)]},
        ],
    )
    counter = [0]
    assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat", call_counter=counter
    )
    with scoped_cache_override(False):
        results = assess_claims_batch(
            [CLAIM, second_claim],
            [
                EvidencePassage("ev-1", QUOTE),
                EvidencePassage("ev-2", second_quote),
            ],
            batch_assessor=assessor,
            assessor_id=assessor_id,
        )
    assert [r.label for r in results] == [EntailmentLabel.CONTRADICTS] * 2
    assert [r.verification_method for r in results] == [
        "model_opposition_verified"
    ] * 2
    assert [r.contradicting_passages[0].evidence_id for r in results] == [
        "ev-1",
        "ev-2",
    ]
    assert len(requests) == counter[0] == 2


def test_batch_short_verification_envelope_retries_before_confirming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.claim_verifier_batch import make_llm_batch_assessor
    from app.claims import assess_claims_batch

    second_claim = "Drug A increases progression-free survival."
    second_quote = (
        "Drug A shortened progression-free survival from 9.2 to 6.1 months."
    )
    requests = install_replies(
        monkeypatch,
        [
            {
                "verdicts": [
                    {"index": 1, **draft()},
                    {"index": 2, **draft(second_quote, passage=2)},
                ]
            },
            {"verdicts": [confirmation(1)]},
            {"verdicts": [confirmation(1), confirmation(2)]},
        ],
    )
    assessor, assessor_id = make_llm_batch_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        results = assess_claims_batch(
            [CLAIM, second_claim],
            [
                EvidencePassage("ev-1", QUOTE),
                EvidencePassage("ev-2", second_quote),
            ],
            batch_assessor=assessor,
            assessor_id=assessor_id,
        )
    assert [result.label for result in results] == [
        EntailmentLabel.CONTRADICTS,
        EntailmentLabel.CONTRADICTS,
    ]
    assert len(requests) == 3


def test_two_malformed_verification_envelopes_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = install_replies(monkeypatch, [draft(), {}, {}])
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.verification_method == "model_opposition_unconfirmed"
    assert len(requests) == 3


def test_complete_negative_verification_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = install_replies(
        monkeypatch,
        [
            draft(),
            {
                "verdicts": [
                    confirmation(
                        same_conditions=False,
                        mutually_exclusive=False,
                    )
                ]
            },
        ],
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.verification_method == "model_opposition_unconfirmed"
    assert len(requests) == 2


@pytest.mark.parametrize(
    "verdicts",
    [
        [],
        [confirmation(same_conditions=False)],
        [confirmation(mutually_exclusive=False)],
        [confirmation(), confirmation()],
        [confirmation(99)],
        [confirmation(), confirmation(99)],
        [confirmation(), {}],
    ],
)
def test_unconfirmed_opposition_remains_insufficient(
    monkeypatch: pytest.MonkeyPatch,
    verdicts: list[dict[str, Any]],
) -> None:
    install_replies(
        monkeypatch,
        [draft(), {"verdicts": verdicts}, {"verdicts": verdicts}],
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.contradicting_passages == ()
    assert result.verification_method == "model_opposition_unconfirmed"


@pytest.mark.parametrize(
    "verdicts",
    [
        [confirmation(1), confirmation(2), confirmation(3)],
        [confirmation(1), confirmation(1)],
        [confirmation(1), confirmation(3)],
    ],
)
def test_complete_invalid_batch_verification_envelopes_remain_rejected(
    monkeypatch: pytest.MonkeyPatch,
    verdicts: list[dict[str, Any]],
) -> None:
    from app.claim_verifier_batch import make_llm_batch_assessor
    from app.claims import assess_claims_batch

    second_claim = "Drug A increases progression-free survival."
    second_quote = (
        "Drug A shortened progression-free survival from 9.2 to 6.1 months."
    )
    requests = install_replies(
        monkeypatch,
        [
            {
                "verdicts": [
                    {"index": 1, **draft()},
                    {"index": 2, **draft(second_quote)},
                ]
            },
            {"verdicts": verdicts},
        ],
    )
    assessor, assessor_id = make_llm_batch_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False):
        results = assess_claims_batch(
            [CLAIM, second_claim],
            [
                EvidencePassage("ev-1", QUOTE),
                EvidencePassage("ev-2", second_quote),
            ],
            batch_assessor=assessor,
            assessor_id=assessor_id,
        )
    assert [result.label for result in results] == [
        EntailmentLabel.INSUFFICIENT,
        EntailmentLabel.INSUFFICIENT,
    ]
    assert len(requests) == 2


@pytest.mark.parametrize(
    "quote",
    [
        "Invented kinase tumor growth quote.",
        "Photosynthesis oxygenates the atmosphere.",
    ],
)
def test_unlocated_or_unrelated_quotes_never_request_verification(
    monkeypatch: pytest.MonkeyPatch,
    quote: str,
) -> None:
    requests = install_replies(monkeypatch, [draft(quote)])
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    passage = QUOTE if quote.startswith("Invented") else QUOTE + " " + quote
    with scoped_cache_override(False):
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", passage)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert len(requests) == 1
    assert result.verification_method == "contradiction_guard_rejected"


def test_unavailable_verification_is_observable_without_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.llm_telemetry import scoped_telemetry

    install_replies(
        monkeypatch,
        [draft(), RuntimeError("unavailable"), RuntimeError("unavailable")],
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False), scoped_telemetry("test") as telemetry:
        result = assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.INSUFFICIENT
    rows = telemetry.snapshot().values()
    assert result.verification_method == "model_opposition_unconfirmed"
    assert (
        sum(
            r["errors"].get("opposition_verification_unavailable", 0)
            for r in rows
        )
        == 1
    )
    assert all(not r["deterministic_fallbacks"] for r in rows)


@pytest.mark.parametrize("kind", ["budget", "park"])
def test_verification_propagates_task_control_errors(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    from co_scientist.exceptions import (
        LLMCallBudgetExceededError,
        LLMRateLimitParkError,
    )

    error = (
        LLMCallBudgetExceededError(2, 1)
        if kind == "budget"
        else RateLimitError(
            message="free-models-per-day rate limit exceeded",
            llm_provider="openrouter",
            model="test-model",
        )
    )
    install_replies(monkeypatch, [draft(), error])
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    expected = (
        LLMCallBudgetExceededError
        if kind == "budget"
        else LLMRateLimitParkError
    )
    with scoped_cache_override(False), pytest.raises(expected):
        assess_claim(
            CLAIM,
            [EvidencePassage("ev-1", QUOTE)],
            assessor=assessor,
            assessor_id=assessor_id,
        )

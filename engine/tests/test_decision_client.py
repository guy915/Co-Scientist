import asyncio
import json
from dataclasses import replace
from typing import Any

import httpx
import pytest

from co_scientist.core.config import settings as shared_settings
from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.db import connect, decision_usage, transaction
from co_scientist.platform.db.decision_usage import DecisionQuotaExceededError
from co_scientist.platform.llm.admission.service import scoped_client
from co_scientist.platform.llm.decisions import (
    DecisionSettings,
    DecisionUnavailableError,
    Question,
    SystemOneClient,
    decision_or_fallback,
)
from co_scientist.platform.llm.decisions.calibration import (
    LabeledDecision,
    agreement_lower_bound,
    choose_threshold,
    expected_calibration_error,
)
from co_scientist.platform.llm.decisions.cascade import swapped_pair
from co_scientist.platform.llm.decisions.types import parse_result
from co_scientist.platform.llm.telemetry import scoped_telemetry

_SETTINGS = DecisionSettings(api_key="synthetic-liquid-key", enabled=True)
_QUESTIONS = {"relevant": Question("noul", "Is this paper relevant to the goal?")}


def _binary(probability: float = 0.95) -> dict[str, Any]:
    return {
        "model": "d1:free",
        "answers": {"relevant": {"type": "noul", "noul": probability}},
        "usage": {"input_tokens": 42, "output_tokens": 0},
    }


def _client(payload: Any, **overrides: Any) -> SystemOneClient:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    return SystemOneClient(replace(_SETTINGS, **overrides), transport=transport)


async def _fallback() -> str:
    return "original LLM path"


async def test_free_request_uses_liquid_and_records_physical_and_decision_usage() -> None:
    def reply(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.liquid.ai/decisions/v1/systemone"
        assert json.loads(request.content)["model"] == "d1:free"
        assert request.headers["Authorization"] == "Bearer synthetic-liquid-key"
        with transaction() as conn:
            assert conn.execute("SELECT calls FROM decision_usage").fetchone()[0] == 1
        return httpx.Response(200, json=_binary())

    client = SystemOneClient(_SETTINGS, transport=httpx.MockTransport(reply))
    with scoped_telemetry("review") as telemetry:
        result = await client.decide("goal and paper", _QUESTIONS)
    assert result.answers["relevant"].value is True
    assert result.note("relevant") == "Decided by d1:free, p=0.95"
    usage = telemetry.snapshot()["review::liquid/d1:free"]
    assert usage["calls"] == usage["decision_calls"] == usage["reported_usage_calls"] == 1
    assert usage["prompt_tokens"] == 42
    assert usage["completion_tokens"] == usage["cost_usd"] == 0


@pytest.mark.parametrize("threshold", [None, float("nan"), 0.5, 1.1])
async def test_missing_or_invalid_threshold_keeps_original_path(threshold: float | None) -> None:
    assert (
        await decision_or_fallback(
            "state", _QUESTIONS, threshold, lambda result: "decision", _fallback
        )
        == "original LLM path"
    )


async def test_accepted_and_uncertain_decisions_use_the_same_fallback_callback() -> None:
    for probability, expected in [(0.95, "decision"), (0.55, "original LLM path")]:
        assert (
            await decision_or_fallback(
                "state",
                _QUESTIONS,
                0.9,
                lambda result: "decision",
                _fallback,
                client=_client(_binary(probability)),
            )
            == expected
        )


@pytest.mark.parametrize("overrides", [{"enabled": False}, {"api_key": ""}, {"model": "d1"}])
async def test_disabled_missing_key_and_paid_models_do_not_dispatch(
    overrides: dict[str, Any],
) -> None:
    client = _client(_binary(), **overrides)
    with pytest.raises(DecisionUnavailableError):
        await client.decide("state", _QUESTIONS)
    assert "synthetic-liquid-key" not in repr(client.settings)


async def test_force_offline_refuses_real_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    with pytest.raises(DecisionUnavailableError):
        await SystemOneClient(_SETTINGS).decide("state", _QUESTIONS)


async def test_oversize_state_is_never_truncated_or_dispatched() -> None:
    state = "full mechanism " * 4000
    with pytest.raises(DecisionUnavailableError, match="context"):
        await _client(_binary()).decide(state, _QUESTIONS)
    assert state.endswith("full mechanism ")


async def test_every_question_reserves_its_own_input_tokens() -> None:
    questions = {f"paper_{i}": Question("noul", "Is it relevant?") for i in range(3)}
    payload: dict[str, Any] = {
        "model": "d1:free",
        "answers": {name: {"type": "noul", "noul": 0.9} for name in questions},
    }
    await _client(payload).decide("a" * 1000, questions)
    with connect() as conn:
        tokens = conn.execute("SELECT tokens FROM decision_usage").fetchone()[0]
    assert tokens > 3 * (1000 + 1024)


async def test_daily_cap_survives_client_recreation_and_cascades() -> None:
    await _client(_binary(), max_calls_per_day=1).decide("state", _QUESTIONS)
    assert (
        await decision_or_fallback(
            "state",
            _QUESTIONS,
            0.9,
            lambda result: "decision",
            _fallback,
            client=_client(_binary(), max_calls_per_day=1),
        )
        == "original LLM path"
    )


async def test_concurrent_calls_cannot_overdraw_durable_decision_cap() -> None:
    client = _client(_binary(), max_calls_per_day=3)
    results = await asyncio.gather(
        *(client.decide("state", _QUESTIONS) for _ in range(12)), return_exceptions=True
    )
    assert sum(not isinstance(result, BaseException) for result in results) == 3
    assert sum(isinstance(result, DecisionQuotaExceededError) for result in results) == 9


async def test_shared_provider_cap_still_stops_decisions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared_settings, "app_llm_global_calls_per_day", 1)
    client = _client(_binary())
    with scoped_client("owner", host="host"):
        await client.decide("state", _QUESTIONS)
        with pytest.raises(ProviderAdmissionError):
            await decision_or_fallback(
                "state", _QUESTIONS, 0.9, lambda result: "decision", _fallback, client=client
            )


async def test_rate_limit_blocks_following_decision_calls_and_uses_llm() -> None:
    calls = 0

    def rate_limit(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "3600"})

    client = SystemOneClient(_SETTINGS, transport=httpx.MockTransport(rate_limit))
    for _ in range(2):
        assert (
            await decision_or_fallback(
                "state", _QUESTIONS, 0.9, lambda result: "decision", _fallback, client=client
            )
            == "original LLM path"
        )
    assert calls == 1


async def test_timeout_keeps_reservation_and_cascades() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200, json=_binary())

    client = SystemOneClient(
        replace(_SETTINGS, timeout_seconds=0.01), transport=httpx.MockTransport(slow)
    )
    assert (
        await decision_or_fallback(
            "state", _QUESTIONS, 0.9, lambda result: "decision", _fallback, client=client
        )
        == "original LLM path"
    )
    with connect() as conn:
        assert conn.execute("SELECT calls FROM decision_usage").fetchone()[0] == 1


def test_rate_limit_cooldown_survives_midnight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decision_usage, "current_time", lambda: 86390)
    decision_usage.block_decisions(60, None)
    monkeypatch.setattr(decision_usage, "current_time", lambda: 86410)
    with pytest.raises(DecisionQuotaExceededError):
        decision_usage.reserve_decision(100, 3, 1000, None)
    monkeypatch.setattr(decision_usage, "current_time", lambda: 86451)
    decision_usage.reserve_decision(100, 3, 1000, None)


async def test_cancellation_propagates_instead_of_starting_fallback() -> None:
    async def cancelled(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    client = SystemOneClient(_SETTINGS, transport=httpx.MockTransport(cancelled))
    with pytest.raises(asyncio.CancelledError):
        await decision_or_fallback(
            "state", _QUESTIONS, 0.9, lambda result: "decision", _fallback, client=client
        )


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), -0.1, 1.1, True, "0.9"])
def test_invalid_probabilities_are_rejected(probability: Any) -> None:
    with pytest.raises(DecisionUnavailableError):
        parse_result(_binary(probability), _QUESTIONS)


def test_choice_and_score_validate_complete_distribution_and_confidence() -> None:
    questions = {
        "pick": Question("choice", "Pick", {"A": "first", "B": "second"}),
        "rubric": Question("score", "Rate", ("low", "high")),
    }
    payload: dict[str, Any] = {
        "model": "d1:free",
        "answers": {
            "pick": {
                "type": "choice",
                "choice": "A",
                "confidence": 0.99,
                "probabilities": {"A": 0.8, "B": 0.2},
            },
            "rubric": {
                "type": "score",
                "score": 0.9,
                "confidence": 0.9,
                "probabilities": {"0": 0.1, "1": 0.9},
            },
        },
    }
    result = parse_result(payload, questions)
    assert result.answers["pick"].confidence == 0.8
    assert result.answers["rubric"].value == 0.9
    del payload["answers"]["pick"]["probabilities"]["B"]
    with pytest.raises(DecisionUnavailableError):
        parse_result(payload, questions)


@pytest.mark.parametrize("reverse_choice,confidence", [("B", 0.9), ("A", 0)])
async def test_swapped_order_alignment_and_disagreement(
    reverse_choice: str, confidence: float
) -> None:
    calls = 0

    def reply(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        state = json.loads(request.content)["state"]
        choice = "A" if calls == 0 else reverse_choice
        assert state["A"] == ("first" if calls == 0 else "second")
        calls += 1
        return httpx.Response(
            200,
            json={
                "model": "d1:free",
                "answers": {
                    "winner": {
                        "type": "choice",
                        "choice": choice,
                        "confidence": 0.9,
                        "probabilities": {choice: 0.9, "B" if choice == "A" else "A": 0.1},
                    }
                },
            },
        )

    result = await swapped_pair(
        SystemOneClient(_SETTINGS, transport=httpx.MockTransport(reply)),
        "goal",
        "first",
        "second",
        Question("choice", "Which is stronger?", {"A": "A", "B": "B"}),
    )
    assert calls == 2
    assert result.answers["winner"].confidence == pytest.approx(confidence)


def test_threshold_requires_labels_and_rejects_confident_errors() -> None:
    assert choose_threshold([LabeledDecision(0.99, True)] * 99) is None
    labels = [LabeledDecision(0.8, False)] * 20 + [LabeledDecision(0.99, True)] * 80
    assert choose_threshold(labels) == 0.99
    assert agreement_lower_bound(labels, 0.8) < -0.02
    assert choose_threshold([LabeledDecision(1, False)] * 100) is None
    assert expected_calibration_error([LabeledDecision(0.8, True)] * 100) == pytest.approx(0.2)

"""Physical response observations survive usage aggregation and persistence."""

import pytest

from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
    scoped_telemetry,
)
from co_scientist.models.metrics import ExecutionMetrics, merge_metrics
from tests._llm_fake import install_fake_backend
from tests._llm_wrapper_fakes import (
    make_completion,
    make_message,
    make_usage,
    patch_acompletion,
)


@pytest.mark.parametrize("missing_model", [None, "  "])
async def test_response_identity_and_missing_usage_remain_distinguishable(
    monkeypatch: pytest.MonkeyPatch,
    missing_model: str | None,
) -> None:
    model = "openai/requested-model"
    response = make_completion(make_message("ok"), make_usage(7, 3))
    response.model = "unpriced-served-model"
    missing = make_completion(make_message("ok"))
    missing.model = missing_model
    patch_acompletion(monkeypatch, [response, missing], [])
    with scoped_telemetry("probe") as telemetry:
        for _ in range(2):
            assert (
                await call_llm(
                    "probe",
                    CompletionSpec(model),
                    options=LLMCallOptions(use_cache=False),
                )
                == "ok"
            )
    usage = telemetry.snapshot()
    observed = usage["probe::openai/unpriced-served-model"]
    assert observed["requested_models"] == {model: 1}
    assert observed["observed_model_calls"] == 1
    assert observed["reported_usage_calls"] == 1
    assert observed["priced_usage_calls"] == 0
    absent = usage[f"probe::{model}"]
    assert absent["observed_model_calls"] == 0
    assert absent["reported_usage_calls"] == 0
    assert absent["priced_usage_calls"] == 0
    assert absent["requested_models"] == {model: 1}

    delta = ExecutionMetrics(model_usage=usage)
    merged = merge_metrics(delta, delta)
    restored = ExecutionMetrics.from_dict(merged.to_dict())
    combined = restored.model_usage["probe::openai/unpriced-served-model"]
    assert combined["requested_models"] == {model: 2}
    assert combined["observed_model_calls"] == 2
    assert combined["reported_usage_calls"] == 2
    assert combined["priced_usage_calls"] == 0


async def test_known_zero_estimate_is_distinct_from_missing_cost_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "openrouter/campaign-probe"
    response = make_completion(make_message("ok"), make_usage(0, 0))
    response.model = "minimax/minimax-m3:free"
    patch_acompletion(monkeypatch, [response], [])
    with scoped_telemetry("probe") as telemetry:
        await call_llm(
            "probe",
            CompletionSpec(model),
            options=LLMCallOptions(use_cache=False),
        )
    entry = telemetry.snapshot()["probe::openrouter/minimax/minimax-m3:free"]
    assert entry["cost_usd"] == 0
    assert entry["priced_usage_calls"] == 1
    assert entry["reported_usage_calls"] == 1


async def test_failed_attempt_does_not_claim_observed_model_or_known_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    install_fake_backend(
        monkeypatch, AsyncMock(side_effect=ValueError("provider failed"))
    )
    with (
        scoped_telemetry("probe") as telemetry,
        pytest.raises(ValueError, match="provider failed"),
    ):
        await call_llm(
            "probe",
            CompletionSpec("openai/gpt-4o"),
            options=LLMCallOptions(use_cache=False),
            max_attempts=1,
        )
    entry = telemetry.snapshot()["probe::openai/gpt-4o"]
    assert entry["calls"] == 1
    assert entry["requested_models"] == {"openai/gpt-4o": 1}
    assert entry["observed_model_calls"] == 0
    assert entry["reported_usage_calls"] == 0
    assert entry["priced_usage_calls"] == 0
    assert entry["errors"] == {"ValueError": 1}


def test_legacy_usage_never_gains_observation_evidence_on_merge() -> None:
    old = ExecutionMetrics.from_dict(
        {"model_usage": {"probe::m": {"calls": 2, "cost_usd": 0.0}}}
    )
    new = ExecutionMetrics(
        model_usage={
            "probe::m": {
                "calls": 1,
                "observed_model_calls": 1,
                "reported_usage_calls": 1,
                "priced_usage_calls": 1,
                "requested_models": {"requested": 1},
            }
        }
    )
    merged = merge_metrics(old, new).to_dict()["model_usage"]["probe::m"]
    assert merged["calls"] == 3
    assert merged["observed_model_calls"] == 1
    assert merged["reported_usage_calls"] == 1
    assert merged["priced_usage_calls"] == 1
    assert merged["requested_models"] == {"requested": 1}

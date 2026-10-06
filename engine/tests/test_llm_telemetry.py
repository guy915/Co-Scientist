from __future__ import annotations

import dataclasses
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.constants import estimate_cost_usd
from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMThinkingOnlyError,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ModelCallStats,
    call_llm,
    call_llm_json,
    parse_tool_loop_json,
    record_call,
    scoped_telemetry,
    scoped_telemetry_phase,
)
from co_scientist.llm.attempts.escalation import (
    BudgetEscalation,
    escalation_for_error,
    log_escalation,
)
from co_scientist.llm.telemetry import (
    record_cache_result,
    record_completion_response,
    record_retry,
)
from co_scientist.models.metrics import (
    ExecutionMetrics,
    _merge_usage_entry,
    merge_metrics,
)
from tests._llm_fake import (
    disable_llm_cache,
    install_fake_backend,
    make_completion,
    make_message,
    make_usage,
    patch_acompletion,
    scripted_backend,
)

_MODEL = "deepseek/deepseek-v4-flash"
_INT_SCHEMA: dict[str, Any] = {
    "name": "ranking_judgment",
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}

# LiteLLM parse failures can append the entire original completion.
_HUGE_PROVIDER_ERROR = (
    "litellm.APIError: APIError: DeepseekException - Unable to get json "
    "response - Unterminated string starting at: line 1 column 184 "
    "(char 183), Original Response: " + ("{payload}" * 900)
)


def _answerless() -> Any:
    return make_completion(
        make_message(None),
        usage=make_usage(3938, 523, reasoning_tokens=523),
        finish_reason="stop",
    )


async def test_a_recovered_call_logs_one_failure_naming_what_was_sent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Layered duplicate records made a recovered run look like dozens of
    errors; the thinking floor can exceed the caller budget, and many call
    sites share a budget, so the record names both."""
    disable_llm_cache(monkeypatch)
    scripted_backend(
        monkeypatch,
        [_answerless(), make_completion(make_message('{"a":1}'))],
        repeat_last=True,
    )

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        result = await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL, max_tokens=8000, json_schema=_INT_SCHEMA
            ),
            max_attempts=5,
        )

    assert result == {"a": 1}
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    failures = [r for r in caplog.records if "LLM call failed" in r.message]
    assert len(failures) == 1
    assert failures[0].name == "co_scientist.llm.attempts.retry"
    message = failures[0].getMessage()
    assert "max_tokens 18000" in message
    assert "asked for 8000" in message
    assert "ranking_judgment" in message
    layers = {"co_scientist.llm", "co_scientist.llm.call"}
    assert not [
        r
        for r in caplog.records
        if r.name in layers and r.levelno >= logging.WARNING
    ]
    assert any(
        r.levelno == logging.INFO and "retrying llm call" in r.getMessage()
        for r in caplog.records
    )


async def test_a_provider_error_is_logged_at_a_bounded_length(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    disable_llm_cache(monkeypatch)
    scripted_backend(
        monkeypatch, [RuntimeError(_HUGE_PROVIDER_ERROR)], repeat_last=True
    )

    with (
        caplog.at_level(logging.DEBUG, logger="co_scientist"),
        pytest.raises(RuntimeError),
    ):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=1,
        )

    assert any("Unterminated string" in r.getMessage() for r in caplog.records)
    assert all(len(r.getMessage()) < 1000 for r in caplog.records)


def test_a_repaired_truncation_reports_the_phase_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        parsed = parse_tool_loop_json(
            '{"items": [{"a": 1}, {"a": 2', "items", "Draft phase"
        )

    assert parsed
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Draft phase" in warnings[0].getMessage()


# A declared mandatory-reasoning route redirects disable before transmission;
# an undeclared route reaches the wire with the literal disable knob.
_UNDISABLEABLE = "openrouter/minimax/minimax-m3:free"


@pytest.mark.parametrize(
    ("error", "rung", "model", "said", "not_said"),
    [
        (
            LLMThinkingOnlyError(),
            BudgetEscalation.NO_THINKING,
            _UNDISABLEABLE,
            "reasoning capped at",
            "thinking disabled",
        ),
        (
            LLMBudgetExhaustedError(),
            BudgetEscalation.NO_THINKING,
            _UNDISABLEABLE,
            "reasoning capped at",
            "thinking disabled",
        ),
        (
            LLMThinkingOnlyError(),
            BudgetEscalation.NO_THINKING,
            _MODEL,
            "thinking disabled",
            "capped",
        ),
        (
            RuntimeError("reasoning is mandatory... cannot be disabled"),
            BudgetEscalation.MINIMAL_REASONING_REQUIRED,
            _MODEL,
            "rejected disabled reasoning as mandatory",
            "capped",
        ),
    ],
)
def test_the_escalation_log_says_what_the_next_request_will_really_do(
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    rung: BudgetEscalation,
    model: str,
    said: str,
    not_said: str,
) -> None:
    with caplog.at_level(logging.WARNING):
        log_escalation(error, rung, model)

    message = caplog.records[-1].getMessage()
    assert said in message
    assert not_said not in message


@pytest.mark.parametrize("rung", list(BudgetEscalation))
def test_a_spent_budget_has_an_answer_at_every_rung_but_the_top_two(
    rung: BudgetEscalation,
) -> None:
    top = {
        BudgetEscalation.NO_THINKING,
        BudgetEscalation.MINIMAL_REASONING_REQUIRED,
    }

    answer = escalation_for_error(LLMBudgetExhaustedError("spent"), rung)

    assert (answer is None) == (rung in top)


def test_telemetry_is_recorded_per_phase_and_model_and_summed() -> None:
    record_call("outside-any-scope", ModelCallStats(calls=1))
    with scoped_telemetry("generate") as accumulator:
        record_call("model-a", ModelCallStats(calls=1, prompt_tokens=10))
        record_call("model-a", ModelCallStats(calls=1, prompt_tokens=20))
        record_call("model-b", ModelCallStats(errors={"TimeoutError": 1}))
        record_call(
            "model-b", ModelCallStats(errors={"TimeoutError": 1, "OSError": 1})
        )
        record_retry("model-a")
        record_cache_result("model-a", hit=True)
        record_cache_result("model-a", hit=False)

    snapshot = accumulator.snapshot()
    assert set(snapshot) == {"generate::model-a", "generate::model-b"}
    first = snapshot["generate::model-a"]
    assert first == {
        **ModelCallStats(
            calls=2, prompt_tokens=30, retries=1, cache_hits=1, cache_misses=1
        ).as_dict()
    }
    assert snapshot["generate::model-b"]["errors"] == {
        "TimeoutError": 2,
        "OSError": 1,
    }


def test_nested_scopes_stay_isolated_and_sub_phases_share_the_outer_one() -> (
    None
):
    with scoped_telemetry("outer") as outer:
        record_call("m", ModelCallStats(calls=1))
        with scoped_telemetry("inner") as inner:
            record_call("m", ModelCallStats(calls=1))
        with scoped_telemetry_phase("sub"), scoped_telemetry_phase("deeper"):
            record_call("m", ModelCallStats(calls=1))
        record_call("m", ModelCallStats(calls=1))

    assert set(inner.snapshot()) == {"inner::m"}
    assert {k: v["calls"] for k, v in outer.snapshot().items()} == {
        "outer::m": 2,
        "outer.sub.deeper::m": 1,
    }


def test_the_cached_share_of_a_prompt_reaches_telemetry() -> None:
    """Provider prompt-cache hits differ from engine response-cache hits and
    affect billed cost."""
    model = "openrouter/deepseek/deepseek-v4-flash"
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10_000,
            completion_tokens=100,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
            prompt_tokens_details=SimpleNamespace(cached_tokens=9_500),
        )
    )

    with scoped_telemetry("generate") as accumulator:
        record_completion_response(model, response, latency_seconds=0.0)

    stats = accumulator.snapshot()[f"generate::{model}"]
    assert stats["prompt_tokens"] == 10_000
    assert stats["cached_prompt_tokens"] == 9_500
    assert stats["cache_hits"] == 0
    assert stats["cost_usd"] < estimate_cost_usd(model, 10_000, 100)


def test_merging_fan_out_usage_keeps_every_field_stats_carries() -> None:
    """Omitted numeric fields silently erase usage from the most expensive
    fan-out phase."""
    numeric = {
        f.name: 2
        for f in dataclasses.fields(ModelCallStats)
        if f.name
        not in {"errors", "requested_models", "deterministic_fallbacks"}
    }
    merged = _merge_usage_entry({**numeric, "errors": {}}, {**numeric})

    for name in numeric:
        assert merged[name] == 4, f"{name} was dropped by the merge"


class _Response:
    def __init__(self, served: str | None) -> None:
        self.model = served
        self.usage = SimpleNamespace(
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            completion_tokens_details=None,
            prompt_tokens_details=None,
        )
        self.choices: list[Any] = []


@pytest.mark.parametrize(
    ("requested", "served", "attributed", "billed"),
    [
        (
            "openrouter/minimax/minimax-m3:free",
            "deepseek/deepseek-v4-pro",
            "openrouter/deepseek/deepseek-v4-pro",
            True,
        ),
        ("openai/gpt-4o", None, "openai/gpt-4o", True),
        (
            "openrouter/z-ai/glm-5.3-flash",
            "z-ai/glm-5.3-flash",
            "openrouter/z-ai/glm-5.3-flash",
            True,
        ),
        (
            "openrouter/z-ai/glm-5.3-flash",
            "minimax/minimax-m3:free",
            "openrouter/minimax/minimax-m3:free",
            False,
        ),
    ],
    ids=[
        "fallback-is-billed",
        "no-served-name",
        "gateway-prefix",
        "free-fallback",
    ],
)
def test_cost_follows_the_model_that_answered_on_the_route_that_billed_it(
    requested: str, served: str | None, attributed: str, billed: bool
) -> None:
    with scoped_telemetry("p") as accumulator:
        record_completion_response(requested, _Response(served), 1.0)

    stats = accumulator.snapshot()[f"p::{attributed}"]
    assert (stats["cost_usd"] > 0) is billed


@pytest.mark.parametrize("missing_model", [None, "  "])
async def test_response_identity_and_missing_usage_remain_distinguishable(
    monkeypatch: pytest.MonkeyPatch, missing_model: str | None
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
    response = make_completion(make_message("ok"), make_usage(0, 0))
    response.model = "minimax/minimax-m3:free"
    patch_acompletion(monkeypatch, [response], [])
    with scoped_telemetry("probe") as telemetry:
        await call_llm(
            "probe",
            CompletionSpec("openrouter/campaign-probe"),
            options=LLMCallOptions(use_cache=False),
        )
    entry = telemetry.snapshot()["probe::openrouter/minimax/minimax-m3:free"]
    assert entry["cost_usd"] == 0
    assert entry["priced_usage_calls"] == 1
    assert entry["reported_usage_calls"] == 1


async def test_failed_attempt_does_not_claim_observed_model_or_known_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fails(**_kwargs: Any) -> Any:
        raise ValueError("provider failed")

    install_fake_backend(monkeypatch, fails)
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

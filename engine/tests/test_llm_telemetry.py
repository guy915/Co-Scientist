from __future__ import annotations

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
    TelemetryAccumulator,
    record_cache_result,
    record_completion_response,
    record_retry,
)
from co_scientist.models.metrics import ExecutionMetrics, merge_metrics
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_fake import (
    install_fake_backend,
    make_completion,
    make_message,
    make_usage,
    patch_acompletion,
)
from tests._llm_fake import make_completion as _completion
from tests._llm_fake import make_message as _message
from tests._llm_fake import make_usage as _usage

_MODEL = "deepseek/deepseek-v4-flash"

_INT_SCHEMA: dict[str, Any] = {
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
    return _completion(
        _message(None),
        usage=_usage(3938, 523, reasoning_tokens=523),
        finish_reason="stop",
    )


def _serve(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> None:
    remaining = list(responses)

    async def fake(**_kwargs: Any) -> Any:
        item = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(item, Exception):
            raise item
        return item

    install_fake_backend(monkeypatch, fake)


async def test_a_recovered_call_logs_no_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless(), _completion(_message('{"a":1}'))])

    with caplog.at_level(logging.INFO, logger="co_scientist"):
        result = await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=5,
        )

    assert result == {"a": 1}
    assert [
        r.message for r in caplog.records if r.levelno >= logging.ERROR
    ] == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)

    assert any(
        r.levelno == logging.INFO and "retrying llm call" in r.getMessage()
        for r in caplog.records
    )


async def test_the_attempt_that_gives_up_still_logs_an_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless()])

    with (
        caplog.at_level(logging.DEBUG, logger="co_scientist"),
        pytest.raises(ValueError),
    ):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=2,
        )

    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_a_provider_error_is_logged_at_a_bounded_length(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [RuntimeError(_HUGE_PROVIDER_ERROR)])

    with (
        caplog.at_level(logging.DEBUG, logger="co_scientist"),
        pytest.raises(RuntimeError),
    ):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=1,
        )

    assert caplog.records
    for record in caplog.records:
        assert len(record.getMessage()) < 1000
    assert any("Unterminated string" in r.getMessage() for r in caplog.records)


def _llm_layer_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    """Lower layers may trace at debug; reader-facing diagnostics need one
    record per attempt."""
    return [
        r
        for r in caplog.records
        if r.name
        in (
            "co_scientist.llm",
            "co_scientist.llm.call",
            "co_scientist.llm.request.response",
        )
        and r.levelno >= logging.WARNING
    ]


async def test_one_failed_attempt_logs_one_failure_record(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Layered duplicate records made a recovered run look like dozens of
    errors."""
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless(), _completion(_message('{"a":1}'))])

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=5,
        )

    failures = [r for r in caplog.records if "LLM call failed" in r.message]
    assert len(failures) == 1
    assert failures[0].name == "co_scientist.llm.attempts.retry"
    assert _llm_layer_records(caplog) == []


async def test_the_failure_record_carries_the_budget_actually_sent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The thinking floor can exceed the caller budget; logging the latter
    misstates the request."""
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless(), _completion(_message('{"a":1}'))])

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL, max_tokens=8000, json_schema=_INT_SCHEMA
            ),
            max_attempts=5,
        )

    failure = next(r for r in caplog.records if "LLM call failed" in r.message)
    assert "max_tokens 18000" in failure.getMessage()
    assert "asked for 8000" in failure.getMessage()


async def test_the_failure_record_names_the_call_that_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Many call sites share a budget; its number cannot identify the failing
    node."""
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless(), _completion(_message('{"a":1}'))])

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL,
                json_schema={"name": "ranking_judgment", **_INT_SCHEMA},
            ),
            max_attempts=5,
        )

    failure = next(r for r in caplog.records if "LLM call failed" in r.message)
    assert "ranking_judgment" in failure.getMessage()


async def test_a_direct_call_llm_failure_logs_once_per_attempt(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from co_scientist.llm import call_llm

    _disable_cache(monkeypatch)
    _serve(monkeypatch, [RuntimeError("provider exploded")])

    with (
        caplog.at_level(logging.DEBUG, logger="co_scientist"),
        pytest.raises(RuntimeError),
    ):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_MODEL), max_attempts=3
        )

    failures = [r for r in caplog.records if "LLM call failed" in r.message]
    assert len(failures) == 3
    assert {r.name for r in failures} == {"co_scientist.llm.attempts.retry"}
    assert [r.levelno for r in failures] == [
        logging.WARNING,
        logging.WARNING,
        logging.ERROR,
    ]
    assert _llm_layer_records(caplog) == []


def test_a_repaired_truncation_reports_the_phase_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The repair strategy belongs at debug; readers need one warning naming
    the phase."""
    from co_scientist.llm import parse_tool_loop_json

    truncated = '{"items": [{"a": 1}, {"a": 2'

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        parsed = parse_tool_loop_json(truncated, "items", "Draft phase")

    assert parsed
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Draft phase" in warnings[0].getMessage()
    assert any(
        "major repair strategy" in r.getMessage() and r.levelno == logging.DEBUG
        for r in caplog.records
    )


# A declared mandatory-reasoning route redirects disable before transmission.
_UNDISABLEABLE_MODEL = "openrouter/minimax/minimax-m3:free"

# An undeclared route reaches the wire with the literal disable knob.
_DISABLEABLE_MODEL = "deepseek/deepseek-v4-flash"


def test_no_thinking_log_names_the_cap_for_an_undisableable_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        log_escalation(
            LLMThinkingOnlyError(),
            BudgetEscalation.NO_THINKING,
            _UNDISABLEABLE_MODEL,
        )
    message = caplog.records[-1].getMessage()
    assert "reasoning capped at" in message
    assert "thinking disabled" not in message


def test_no_thinking_log_names_disabled_for_model_that_can_disable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        log_escalation(
            LLMThinkingOnlyError(),
            BudgetEscalation.NO_THINKING,
            _DISABLEABLE_MODEL,
        )
    message = caplog.records[-1].getMessage()
    assert "thinking disabled" in message
    assert "capped" not in message


def test_budget_exhausted_no_thinking_log_matches_the_redirect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        log_escalation(
            LLMBudgetExhaustedError(),
            BudgetEscalation.NO_THINKING,
            _UNDISABLEABLE_MODEL,
        )
    message = caplog.records[-1].getMessage()
    assert "reasoning capped at" in message
    assert "thinking disabled" not in message


def test_minimal_reasoning_required_log_always_follows_a_real_rejection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        log_escalation(
            RuntimeError("reasoning is mandatory... cannot be disabled"),
            BudgetEscalation.MINIMAL_REASONING_REQUIRED,
            _DISABLEABLE_MODEL,
        )
    message = caplog.records[-1].getMessage()
    assert "rejected disabled reasoning as mandatory" in message


@pytest.mark.parametrize("rung", list(BudgetEscalation))
def test_a_budget_exhausted_attempt_has_an_answer_at_every_rung(
    rung: BudgetEscalation,
) -> None:
    escalation_for_error(LLMBudgetExhaustedError("spent"), rung)


@pytest.mark.parametrize(
    "rung",
    [BudgetEscalation.NO_THINKING, BudgetEscalation.MINIMAL_REASONING_REQUIRED],
)
def test_the_top_rungs_stop_escalating(rung: BudgetEscalation) -> None:
    assert escalation_for_error(LLMBudgetExhaustedError("spent"), rung) is None


def test_record_call_outside_scope_is_a_noop() -> None:
    record_call("some-model", ModelCallStats(calls=1))


def test_scoped_telemetry_records_under_its_phase() -> None:
    with scoped_telemetry("generate") as accumulator:
        record_call("test-model", ModelCallStats(calls=1, prompt_tokens=10))

    snapshot = accumulator.snapshot()
    assert snapshot == {
        "generate::test-model": {
            "calls": 1,
            "observed_model_calls": 0,
            "reported_usage_calls": 0,
            "priced_usage_calls": 0,
            "requested_models": {},
            "deterministic_fallbacks": {},
            "prompt_tokens": 10,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "cached_prompt_tokens": 0,
            "cost_usd": 0.0,
            "latency_seconds": 0.0,
            "retries": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": {},
        }
    }


def test_scoped_telemetry_sums_repeated_calls() -> None:
    with scoped_telemetry("review") as accumulator:
        record_call("m", ModelCallStats(calls=1, prompt_tokens=10))
        record_call("m", ModelCallStats(calls=1, prompt_tokens=20))

    entry = accumulator.snapshot()["review::m"]
    assert entry["calls"] == 2
    assert entry["prompt_tokens"] == 30


def test_scoped_telemetry_separates_different_models() -> None:
    with scoped_telemetry("evolve") as accumulator:
        record_call("model-a", ModelCallStats(calls=1))
        record_call("model-b", ModelCallStats(calls=1))

    assert set(accumulator.snapshot()) == {"evolve::model-a", "evolve::model-b"}


def test_scoped_telemetry_merges_error_kinds() -> None:
    with scoped_telemetry("p") as accumulator:
        record_call("m", ModelCallStats(errors={"TimeoutError": 1}))
        record_call(
            "m", ModelCallStats(errors={"TimeoutError": 1, "ValueError": 1})
        )

    errors = accumulator.snapshot()["p::m"]["errors"]
    assert errors == {"TimeoutError": 2, "ValueError": 1}


def test_scope_exit_restores_the_outer_context() -> None:
    with scoped_telemetry("p"):
        record_call("m", ModelCallStats(calls=1))
    record_call("m", ModelCallStats(calls=1))


def test_nested_scope_isolated_from_outer_accumulator() -> None:
    with scoped_telemetry("outer") as outer_accumulator:
        record_call("m", ModelCallStats(calls=1))
        with scoped_telemetry("inner") as inner_accumulator:
            record_call("m", ModelCallStats(calls=1))
        assert inner_accumulator.snapshot() == {
            "inner::m": ModelCallStats(calls=1).as_dict()
        }
        record_call("m", ModelCallStats(calls=1))

    assert outer_accumulator.snapshot()["outer::m"]["calls"] == 2


def test_record_retry_and_cache_result_helpers() -> None:
    with scoped_telemetry("p") as accumulator:
        record_retry("m")
        record_cache_result("m", hit=True)
        record_cache_result("m", hit=False)

    entry = accumulator.snapshot()["p::m"]
    assert entry["retries"] == 1
    assert entry["cache_hits"] == 1
    assert entry["cache_misses"] == 1


def test_telemetry_accumulator_starts_empty() -> None:
    assert TelemetryAccumulator().snapshot() == {}


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
    import dataclasses

    from co_scientist.models.metrics import _merge_usage_entry

    numeric = {
        f.name: 2
        for f in dataclasses.fields(ModelCallStats)
        if f.name
        not in {"errors", "requested_models", "deterministic_fallbacks"}
    }
    merged = _merge_usage_entry({**numeric, "errors": {}}, {**numeric})

    for name in numeric:
        assert merged[name] == 4, f"{name} was dropped by the merge"


def test_sub_phase_records_into_the_outer_accumulator() -> None:
    """A nested scope hides its counters from the node; sub-phases share the
    outer accumulator."""
    with scoped_telemetry("research_overview") as accumulator:
        record_call("m", ModelCallStats(calls=1))
        with scoped_telemetry_phase("knowledge_base"):
            record_call("m", ModelCallStats(calls=1))
        record_call("m", ModelCallStats(calls=1))

    snapshot = accumulator.snapshot()
    assert snapshot["research_overview::m"]["calls"] == 2
    assert snapshot["research_overview.knowledge_base::m"]["calls"] == 1


def test_sub_phase_nests_under_a_sub_phase() -> None:
    with (
        scoped_telemetry("outer") as accumulator,
        scoped_telemetry_phase("a"),
        scoped_telemetry_phase("b"),
    ):
        record_call("m", ModelCallStats(calls=1))

    assert "outer.a.b::m" in accumulator.snapshot()


class _Usage:
    prompt_tokens = 1_000_000
    completion_tokens = 1_000_000
    cached_tokens = 0
    reasoning_tokens = 0
    completion_tokens_details = None
    prompt_tokens_details = None


class _Response:
    def __init__(self, served: str | None) -> None:
        self.model = served
        self.usage = _Usage()
        self.choices: list[Any] = []


def test_cost_follows_the_model_that_answered(monkeypatch: Any) -> None:
    """Fallback cost belongs to the served model, retaining the gateway
    billing route."""
    from co_scientist.llm import telemetry

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        telemetry,
        "record_call",
        lambda model, stats: seen.update(model=model, stats=stats),
    )

    record_completion_response(
        "openrouter/minimax/minimax-m3:free",
        _Response("deepseek/deepseek-v4-pro"),
        1.0,
    )

    assert seen["model"] == "openrouter/deepseek/deepseek-v4-pro"
    assert seen["stats"].cost_usd > 0


def test_a_response_naming_no_model_keeps_the_requested_name(
    monkeypatch: Any,
) -> None:
    """Some providers omit the served name; attribution must retain the
    requested name."""
    from co_scientist.llm import telemetry

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        telemetry,
        "record_call",
        lambda model, stats: seen.update(model=model, stats=stats),
    )

    record_completion_response("openai/gpt-4o", _Response(None), 1.0)

    assert seen["model"] == "openai/gpt-4o"


def test_the_served_name_keeps_the_route_that_billed_it(
    monkeypatch: Any,
) -> None:
    """Gateway responses omit their route prefix; unprefixed names miss the
    pricing table."""
    from co_scientist.llm import telemetry

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        telemetry,
        "record_call",
        lambda model, stats: seen.update(model=model, stats=stats),
    )

    record_completion_response(
        "openrouter/z-ai/glm-5.3-flash",
        _Response("z-ai/glm-5.3-flash"),
        1.0,
    )

    assert seen["model"] == "openrouter/z-ai/glm-5.3-flash"
    assert seen["stats"].cost_usd > 0


def test_a_fallback_is_still_named_as_itself(monkeypatch: Any) -> None:
    from co_scientist.llm import telemetry

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        telemetry,
        "record_call",
        lambda model, stats: seen.update(model=model, stats=stats),
    )

    record_completion_response(
        "openrouter/z-ai/glm-5.3-flash",
        _Response("minimax/minimax-m3:free"),
        1.0,
    )

    assert seen["model"] == "openrouter/minimax/minimax-m3:free"


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


def test_delayed_sub_phase_uses_current_outer_scope() -> None:
    delayed = scoped_telemetry_phase("sub")
    with scoped_telemetry("later") as accumulator, delayed:
        record_call("m", ModelCallStats(calls=1))
    assert accumulator.snapshot()["later.sub::m"]["calls"] == 1

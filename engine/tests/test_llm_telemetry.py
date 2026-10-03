"""Offline contracts for llm telemetry."""

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

# The shape of the real offender: litellm's DeepSeek json-mode parse failure
# appends "Original Response: {...}" carrying the entire completion.
_HUGE_PROVIDER_ERROR = (
    "litellm.APIError: APIError: DeepseekException - Unable to get json "
    "response - Unterminated string starting at: line 1 column 184 "
    "(char 183), Original Response: " + ("{payload}" * 900)
)


def _answerless() -> Any:
    """A completion that reasoned, stopped normally, and wrote no answer."""
    return _completion(
        _message(None),
        usage=_usage(3938, 523, reasoning_tokens=523),
        finish_reason="stop",
    )


def _serve(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> None:
    """Patch the completion seam to return ``responses`` in order.

    An entry that is an exception is raised instead of returned; the last
    entry repeats once the list is spent.
    """
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
    """An answerless completion the ladder recovers from is not an error."""
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless(), _completion(_message('{"a":1}'))])

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        result = await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=5,
        )

    assert result == {"a": 1}
    assert [
        r.message for r in caplog.records if r.levelno >= logging.ERROR
    ] == []
    # The retry is still reported -- demoting it must not make it silent.
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_the_attempt_that_gives_up_still_logs_an_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Severity is about the remedy, so exhausting the ladder is an error."""
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
    """No log record carries the whole completion the provider echoed back."""
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
    # The head identifies the failure, so truncation must keep it.
    assert any("Unterminated string" in r.getMessage() for r in caplog.records)


def _llm_layer_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    """Failure records from below the retry loop, which must stay silent.

    Scoped to WARNING and above: those layers still trace at debug, and
    the point is that a reader's diagnostics panel sees one record, not
    that the modules never speak.
    """
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
    """Three layers saw the same failure and all three wrote it down.

    ``llm.request.response`` logged the empty completion, ``call_llm`` logged
    the call, and the retry loop logged the attempt -- one answerless
    completion, three records saying the same sentence. A production export of a
    run that recovered fine read as 27 errors and 29 warnings, which is what a
    reader has to page through to find a real fault.
    """
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
    """The surviving record reports the floored budget, not the asked one.

    The thinking floor raises the budget before the request goes out, so a
    record printing the call site's own number sat beside a reasoning-token
    count larger than it and read as a provider fault. Folding three
    records into one must not drop the number that settles that.
    """
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
    """One shared loop logs every node's failures, so it must say which.

    A production export of fifteen answerless completions could be
    narrowed no further than the budget constant the request carried, and
    ten call sites ask for the commonest one. The schema name is the
    fallback label because every structured call has one.
    """
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
    """Silencing the raw call layer under the retry loop must not silence it.

    ``debate`` and the literature-review synthesis call ``call_llm``
    directly, and ``call_llm`` runs on the same attempt loop
    (``llm.attempts.retry``) as ``call_llm_json`` -- so a repeated failure
    logs once per attempt, not once per underlying raw call PLUS once per
    attempt, and the raw call layer itself
    (``co_scientist.llm``/``co_scientist.llm.attempts.json_attempt``) stays
    silent
    under it exactly as it does under ``call_llm_json``.
    """
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
    """Two layers wrote down one truncated response; only one should.

    The repair helper named the strategy index and its caller named the
    phase, both at warning, so every truncated completion cost a reader
    two records to learn one fact. The phase is the fact; the strategy
    index is for someone debugging the repair strategies.
    """
    from co_scientist.llm import parse_tool_loop_json

    truncated = '{"items": [{"a": 1}, {"a": 2'

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        parsed = parse_tool_loop_json(truncated, "items", "Draft phase")

    assert parsed
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Draft phase" in warnings[0].getMessage()
    # The strategy index survives, at a level a reader is not paging past.
    assert any(
        "major repair strategy" in r.getMessage() and r.levelno == logging.DEBUG
        for r in caplog.records
    )


# Declared as a gateway route with the default ``reasoning_can_disable
# =False`` -- the deployed free-chain primary, and the exact model the
# 7aaf3682 redirect was written for.
_UNDISABLEABLE_MODEL = "openrouter/minimax/minimax-m3:free"

# Not a declared gateway model at all, so nothing redirects its disable
# request -- a plain ``enable_thinking=False`` genuinely reaches the wire.
_DISABLEABLE_MODEL = "deepseek/deepseek-v4-flash"


def test_no_thinking_log_names_the_cap_for_an_undisableable_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A model redirected to minimal effort must not be logged as disabled."""
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
    """A model whose disable actually lands must still be logged as disabled."""
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
    """The ``LLMBudgetExhaustedError`` phrasing gets the same fix."""
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
    """The MINIMAL_REASONING_REQUIRED rung's own message is unambiguous.

    ``escalation_for_error`` only ever raises this rung in answer to a
    live "reasoning is mandatory" 400 (see ``_is_reasoning_mandatory_
    error``), never as a declaration made ahead of one -- so the model
    name plays no part in its wording, and the message is identical
    regardless of which model triggered it.
    """
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
    """Calling record_call with no active scope raises nothing and drops it."""
    record_call("some-model", ModelCallStats(calls=1))  # must not raise


def test_scoped_telemetry_records_under_its_phase() -> None:
    """A call made inside the scope lands under the scope's phase key."""
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
    """Two calls to the same (phase, model) accumulate additively."""
    with scoped_telemetry("review") as accumulator:
        record_call("m", ModelCallStats(calls=1, prompt_tokens=10))
        record_call("m", ModelCallStats(calls=1, prompt_tokens=20))

    entry = accumulator.snapshot()["review::m"]
    assert entry["calls"] == 2
    assert entry["prompt_tokens"] == 30


def test_scoped_telemetry_separates_different_models() -> None:
    """Two models called under the same phase get separate entries."""
    with scoped_telemetry("evolve") as accumulator:
        record_call("model-a", ModelCallStats(calls=1))
        record_call("model-b", ModelCallStats(calls=1))

    assert set(accumulator.snapshot()) == {"evolve::model-a", "evolve::model-b"}


def test_scoped_telemetry_merges_error_kinds() -> None:
    """Error-kind counts merge across calls rather than overwriting."""
    with scoped_telemetry("p") as accumulator:
        record_call("m", ModelCallStats(errors={"TimeoutError": 1}))
        record_call(
            "m", ModelCallStats(errors={"TimeoutError": 1, "ValueError": 1})
        )

    errors = accumulator.snapshot()["p::m"]["errors"]
    assert errors == {"TimeoutError": 2, "ValueError": 1}


def test_scope_exit_restores_the_outer_context() -> None:
    """After the scope exits, further recording is a no-op again."""
    with scoped_telemetry("p"):
        record_call("m", ModelCallStats(calls=1))
    record_call("m", ModelCallStats(calls=1))  # outside any scope: dropped


def test_nested_scope_isolated_from_outer_accumulator() -> None:
    """A fresh nested scope gets its own accumulator, not the outer one."""
    with scoped_telemetry("outer") as outer_accumulator:
        record_call("m", ModelCallStats(calls=1))
        with scoped_telemetry("inner") as inner_accumulator:
            record_call("m", ModelCallStats(calls=1))
        assert inner_accumulator.snapshot() == {
            "inner::m": ModelCallStats(calls=1).as_dict()
        }
        # Back in the outer scope: recording resumes against it.
        record_call("m", ModelCallStats(calls=1))

    assert outer_accumulator.snapshot()["outer::m"]["calls"] == 2


def test_record_retry_and_cache_result_helpers() -> None:
    """The convenience wrappers record the field they name."""
    with scoped_telemetry("p") as accumulator:
        record_retry("m")
        record_cache_result("m", hit=True)
        record_cache_result("m", hit=False)

    entry = accumulator.snapshot()["p::m"]
    assert entry["retries"] == 1
    assert entry["cache_hits"] == 1
    assert entry["cache_misses"] == 1


def test_telemetry_accumulator_starts_empty() -> None:
    """A fresh accumulator's snapshot is an empty dict."""
    assert TelemetryAccumulator().snapshot() == {}


def test_the_cached_share_of_a_prompt_reaches_telemetry() -> None:
    """A run cannot be costed from counters that never see the cache.

    ``cache_hits`` counts this engine's own response cache, so a call that
    reached the provider and was served almost entirely from *its* prompt
    cache reads as a plain miss. That is the normal case for a tool loop,
    and without this field the run's reported cost prices every re-sent
    transcript at the full input rate.
    """
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
    """A field the merge forgets is zeroed, not partially counted.

    Fan-out is how the most expensive phase in a run aggregates its
    per-item telemetry, so a numeric field missing from the merge is
    silently dropped for exactly the phase whose cost matters most. The
    merge therefore reads its field list off ``ModelCallStats``; this
    fails if the two ever drift apart again.
    """
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
    """A sub-phase relabels the phase without starting a new accumulator.

    This is the difference from ``scoped_telemetry`` above, which is a
    whole new scope: a nested *scope* keeps its numbers to itself, so the
    node boundary that folds the outer snapshot into its metrics never
    sees them. Attribution inside one node -- which call in a multi-call
    node spent what -- needs the opposite: its own key, in the node's own
    accumulator.
    """
    with scoped_telemetry("research_overview") as accumulator:
        record_call("m", ModelCallStats(calls=1))
        with scoped_telemetry_phase("knowledge_base"):
            record_call("m", ModelCallStats(calls=1))
        record_call("m", ModelCallStats(calls=1))

    snapshot = accumulator.snapshot()
    assert snapshot["research_overview::m"]["calls"] == 2
    assert snapshot["research_overview.knowledge_base::m"]["calls"] == 1


def test_sub_phase_nests_under_a_sub_phase() -> None:
    """Sub-phases compose, so a wave inside a wave is still attributable."""
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
    """A completion answered by a different model than was requested."""

    def __init__(self, served: str | None) -> None:
        self.model = served
        self.usage = _Usage()
        self.choices: list[Any] = []


def test_cost_follows_the_model_that_answered(monkeypatch: Any) -> None:
    """A fallback's price is charged to the fallback, not to the primary.

    The free primary here costs nothing; the model that actually answered
    is priced. Attributing to the requested name reports zero for a call
    that was billed, which is the failure this pins. The fallback keeps
    the route it was reached by, since a call served through a gateway is
    billed as a gateway call whichever rung answered it.
    """
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
    """The requested name stays the fallback when the provider omits one.

    Not every provider echoes the served model, and a missing field must
    not blank out a run's whole cost attribution.
    """
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
    """A gateway names the model without the route prefix it was reached by.

    ``openrouter/z-ai/glm-5.3-flash`` comes back as ``z-ai/glm-5.3-flash``,
    which matches no key in ``MODEL_PRICING`` -- so reading the served name
    naively prices every call at zero, reproducing the exact failure that
    reading the requested name caused. Measured on a live run: 53 calls,
    every one of them $0.0000.

    The route is a property of how the call was billed, so it is carried
    over from the request; only the model part comes from the response.
    """
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
    """Carrying the route must not collapse a fallback onto its primary.

    The whole point of reading the served model is telling them apart, so
    re-prefixing has to keep the model half the response reported.
    """
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

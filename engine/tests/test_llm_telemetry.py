"""Tests for ``co_scientist.llm_telemetry``'s in-memory accumulator.

The dispatch-boundary integration (does a real ``call_llm`` populate this)
is covered by ``test_task_runtime.py`` (see
``test_execute_task_node_captures_llm_telemetry_by_phase``), which drives
the real code path end to end. These tests pin the accumulator's own
aggregation and scoping contract in isolation.
"""

from types import SimpleNamespace

from co_scientist.constants_pricing import estimate_cost_usd
from co_scientist.llm_telemetry import (
    ModelCallStats,
    TelemetryAccumulator,
    record_cache_result,
    record_call,
    record_completion_response,
    record_retry,
    scoped_telemetry,
)


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

    from co_scientist.models_metrics import _merge_usage_entry

    numeric = {
        f.name: 2
        for f in dataclasses.fields(ModelCallStats)
        if f.name != "errors"
    }
    merged = _merge_usage_entry({**numeric, "errors": {}}, {**numeric})

    for name in numeric:
        assert merged[name] == 4, f"{name} was dropped by the merge"

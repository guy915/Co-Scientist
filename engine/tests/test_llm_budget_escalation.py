"""Offline contracts for llm budget escalation."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError

from co_scientist import constants
from co_scientist.agents.supervisor.orchestrator import _compute_stats
from co_scientist.constants import (
    BUDGET_ESCALATION_MAX_INCREMENT,
    BUDGET_ESCALATION_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMCallBudgetExceededError,
    LLMThinkingOnlyError,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    current_run_call_count,
    release_run_call_budget,
    scoped_llm_call_budget,
)
from co_scientist.llm.admission.call_budget import (
    _MAX_TRACKED_RUNS,
    record_provider_request,
)
from co_scientist.llm.attempts.escalation import (
    BudgetEscalation,
    escalated_max_tokens,
)
from co_scientist.state import WorkflowState
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_fake import install_fake_backend
from tests._llm_fake import make_completion as _completion
from tests._llm_fake import make_message as _message
from tests._llm_fake import make_usage as _usage


async def test_call_llm_recovers_on_a_raised_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plain ``call_llm``, budget-exhausted on attempt 1, answers on attempt 2.

    Fails against the pre-fix ``call_llm``, which made exactly one attempt
    and raised ``LLMBudgetExhaustedError`` immediately -- see
    ``test_budget_exhaustion_is_its_own_error`` in the ladder-classification
    file for that behavior.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch,
        [
            _exhausted(THINKING_FLOOR_MAX_TOKENS),
            _completion(_message("the text")),
        ],
    )

    result = await call_llm(
        "a prompt",
        CompletionSpec(
            model_name=_LLM_BUDGET_ESCALATION_MODEL, max_tokens=8000
        ),
        max_attempts=5,
    )

    assert result == "the text"
    assert len(calls) == 2
    assert calls[1]["max_tokens"] == BUDGET_ESCALATION_MAX_TOKENS
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled"]


async def test_call_llm_recovers_with_thinking_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plain ``call_llm`` recovers a thinking-only attempt 1 with thinking off.

    Fails against the pre-fix ``call_llm`` the same way as the budget-raise
    case above -- see ``test_thinking_without_answering_is_its_own_error``.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch,
        [_thinking_only(1149), _completion(_message("the text"))],
    )

    result = await call_llm(
        "a prompt",
        CompletionSpec(model_name=_LLM_BUDGET_ESCALATION_MODEL),
        max_attempts=5,
    )

    assert result == "the text"
    assert len(calls) == 2
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "disabled"]


async def test_call_llm_default_max_attempts_exhausts_the_ladder_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default makes exactly the 3 attempts that walk the whole ladder.

    The ladder has three rungs that change the request -- the original
    call, RAISED_BUDGET, then NO_THINKING (see
    ``llm.attempts.escalation.BudgetEscalation``) -- so three attempts is the
    point past which every further attempt would resend the identical
    NO_THINKING request. ``call_llm_json`` keeps a default of 5 because a
    schema or parse failure holds its current rung and genuinely benefits
    from asking again; plain ``call_llm`` has neither failure kind, so its
    default must stop where the ladder does.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)]
    )

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_LLM_BUDGET_ESCALATION_MODEL)
        )

    assert len(calls) == 3
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled", "disabled"]


async def test_call_llm_caches_the_escalated_result_under_the_original_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A call that only succeeds after escalating still populates its cache key.

    ``call_llm`` must cache under the caller's original (unescalated) request
    -- mirroring ``call_llm_json``'s ``_cache_validated_result``, which caches
    under ``ctx.spec.max_tokens`` rather than whatever rung finally answered.
    Otherwise a call that always needs escalation would never populate the
    cache key its own future calls look up under: the second call here would
    re-run the whole (failing-then-escalating) ladder instead of hitting the
    cache in one lookup.
    """
    import co_scientist.cache as cache_mod

    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    monkeypatch.setenv("COSCIENTIST_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cache_mod, "_global_cache", None)

    calls = _record_acompletion(
        monkeypatch,
        [_exhausted(THINKING_FLOOR_MAX_TOKENS), _completion(_message("ok"))],
    )

    spec = CompletionSpec(
        model_name=_LLM_BUDGET_ESCALATION_MODEL, max_tokens=8000
    )
    first = await call_llm("a prompt", spec, max_attempts=5)
    second = await call_llm("a prompt", spec, max_attempts=5)

    assert first == "ok"
    assert second == "ok"
    assert len(calls) == 2  # not 3: the second call hit the cache

    monkeypatch.setattr(cache_mod, "_global_cache", None)


_LLM_CALL_BUDGET_MODEL = "deepseek/deepseek-v4-flash"
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}


def _record(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[SimpleNamespace | Exception],
) -> list[dict[str, Any]]:
    """Patches the completion seam, recording each call and its kwargs.

    An ``Exception`` entry is raised instead of returned, so a caller can
    script "fails N times, then answers" without a second fake.
    """
    calls: list[dict[str, Any]] = []
    queue = iter(responses)

    async def fake(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        item = next(queue)
        if isinstance(item, Exception):
            raise item
        return item

    install_fake_backend(monkeypatch, fake)
    return calls


def _flaky(
    fail_times: int, ok: SimpleNamespace
) -> list[SimpleNamespace | Exception]:
    """A response sequence that fails for the first N calls, then answers."""
    failures: list[SimpleNamespace | Exception] = [
        ValueError("transient provider hiccup") for _ in range(fail_times)
    ]
    return [*failures, ok]


# --- unit: the counter module itself ----------------------------------------


def test_no_run_id_never_raises_and_counts_nothing() -> None:
    """A call made with no scope entered is a pure no-op."""
    record_provider_request()  # must not raise
    record_provider_request()


def test_scope_with_none_run_id_is_also_a_no_op() -> None:
    with scoped_llm_call_budget(None, ceiling=1):
        record_provider_request()
        record_provider_request()
        record_provider_request()  # would exceed ceiling=1 if it counted


def test_counts_increment_within_a_scope() -> None:
    run_id = "run-count-1"
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
        record_provider_request()
    assert current_run_call_count(run_id) == 2
    release_run_call_budget(run_id)


def test_under_ceiling_is_untouched() -> None:
    run_id = "run-under-1"
    with scoped_llm_call_budget(run_id, ceiling=100):
        for _ in range(3):
            record_provider_request()
    assert current_run_call_count(run_id) == 3
    release_run_call_budget(run_id)


def test_exceeding_ceiling_raises_with_count_and_ceiling() -> None:
    run_id = "run-over-1"
    with scoped_llm_call_budget(run_id, ceiling=2):
        record_provider_request()
        record_provider_request()
        with pytest.raises(LLMCallBudgetExceededError) as excinfo:
            record_provider_request()
    assert excinfo.value.count == 3
    assert excinfo.value.ceiling == 2
    release_run_call_budget(run_id)


def test_reentering_a_run_scope_keeps_its_running_count() -> None:
    """A durable run is many tasks; each enters its own scope on one run id."""
    run_id = "run-reenter-1"
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
    assert current_run_call_count(run_id) == 2
    release_run_call_budget(run_id)


def test_first_ceiling_seen_wins_on_reentry() -> None:
    """A later task's ceiling argument does not override an already-set one."""
    run_id = "run-reenter-ceiling"
    with scoped_llm_call_budget(run_id, ceiling=1):
        record_provider_request()
    with (
        scoped_llm_call_budget(run_id, ceiling=1000),
        pytest.raises(LLMCallBudgetExceededError),
    ):
        record_provider_request()
    release_run_call_budget(run_id)


def test_two_concurrent_runs_are_counted_independently() -> None:
    """Two threads, each its own event loop's worth of scope, do not mix."""
    results: dict[str, int] = {}

    def _drive(run_id: str, n: int) -> None:
        with scoped_llm_call_budget(run_id, ceiling=None):
            for _ in range(n):
                record_provider_request()
        results[run_id] = current_run_call_count(run_id)

    t1 = threading.Thread(target=_drive, args=("run-a", 5))
    t2 = threading.Thread(target=_drive, args=("run-b", 9))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results == {"run-a": 5, "run-b": 9}
    release_run_call_budget("run-a")
    release_run_call_budget("run-b")


def test_release_drops_the_counter() -> None:
    run_id = "run-release-1"
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
    assert current_run_call_count(run_id) == 1
    release_run_call_budget(run_id)
    assert current_run_call_count(run_id) == 0


def test_release_of_an_unseen_run_does_not_raise() -> None:
    release_run_call_budget("run-never-seen")


def test_tracking_cap_evicts_the_oldest_run() -> None:
    """Past the cap, the process cannot grow the tracker unboundedly."""
    run_ids = [f"run-evict-{i}" for i in range(_MAX_TRACKED_RUNS + 1)]
    try:
        for run_id in run_ids:
            with scoped_llm_call_budget(run_id, ceiling=None):
                record_provider_request()
        assert current_run_call_count(run_ids[0]) == 0
        assert current_run_call_count(run_ids[-1]) == 1
    finally:
        for run_id in run_ids:
            release_run_call_budget(run_id)


# --- integration: the seam, through call_llm/call_llm_json/tool loop -------


async def test_call_llm_json_counts_one_per_provider_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every retried attempt is a real request and must be counted."""
    _disable_cache(monkeypatch)
    ok = _completion(_message('{"a": 1}'))
    _record(monkeypatch, _flaky(2, ok))
    run_id = "run-json-attempts"

    with scoped_llm_call_budget(run_id, ceiling=None):
        result = await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_LLM_CALL_BUDGET_MODEL, json_schema=_SCHEMA
            ),
            max_attempts=5,
        )

    assert result == {"a": 1}
    assert current_run_call_count(run_id) == 3
    release_run_call_budget(run_id)


async def test_ceiling_exceeded_escapes_call_llm_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget error must reach the caller, not be retried into oblivion."""
    _disable_cache(monkeypatch)
    _record(monkeypatch, [_completion(_message('{"a": 1}'))])
    run_id = "run-json-ceiling"

    with (
        scoped_llm_call_budget(run_id, ceiling=0),
        pytest.raises(LLMCallBudgetExceededError),
    ):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_LLM_CALL_BUDGET_MODEL, json_schema=_SCHEMA
            ),
            max_attempts=5,
        )
    release_run_call_budget(run_id)


async def test_ceiling_exceeded_escapes_call_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _record(monkeypatch, [_completion(_message("hello"))])
    run_id = "run-text-ceiling"

    with (
        scoped_llm_call_budget(run_id, ceiling=0),
        pytest.raises(LLMCallBudgetExceededError),
    ):
        await call_llm(
            "a prompt",
            CompletionSpec(model_name=_LLM_CALL_BUDGET_MODEL),
            max_attempts=3,
        )
    release_run_call_budget(run_id)


async def test_under_ceiling_call_llm_json_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _record(monkeypatch, [_completion(_message('{"a": 1}'))])
    run_id = "run-json-under"

    with scoped_llm_call_budget(run_id, ceiling=100):
        result = await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_LLM_CALL_BUDGET_MODEL, json_schema=_SCHEMA
            ),
        )

    assert result == {"a": 1}
    assert current_run_call_count(run_id) == 1
    release_run_call_budget(run_id)


async def test_tool_loop_turns_are_each_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A multi-turn tool loop counts one request per turn, not per loop."""
    from tests._llm_fake import SEARCH_TOOL, make_tool_call

    _disable_cache(monkeypatch)

    async def _executor(tc: Any) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": tc.id, "content": "result"}

    _record(
        monkeypatch,
        [
            _completion(
                _message(
                    None,
                    tool_calls=[
                        make_tool_call("call-1", "search_pubmed", "{}")
                    ],
                )
            ),
            _completion(_message("final answer")),
        ],
    )
    run_id = "run-tool-loop"

    with scoped_llm_call_budget(run_id, ceiling=None):
        text, _ = await call_llm_with_tools(
            prompt="a prompt",
            spec=CompletionSpec(
                model_name=_LLM_CALL_BUDGET_MODEL, max_tokens=8000
            ),
            loop=ToolLoop(tools=SEARCH_TOOL, executor=_executor),
        )

    assert text == "final answer"
    assert current_run_call_count(run_id) == 2
    release_run_call_budget(run_id)


def test_between_task_check_reads_the_seam_count_not_the_self_report() -> None:
    """``_compute_stats`` sees the seam's count even when metrics reports 0.

    Pins the fix for the under-counting bug: a dozen nodes never wrote
    ``metrics.llm_calls`` at all, so the self-reported figure could sit at
    0 through an entire run that made hundreds of real requests. With no
    ``metrics`` key in state (mirroring a node that never reported), the
    scheduler's own observed ``llm_calls`` must still reflect the seam.
    """
    run_id = "run-between-tasks"
    with scoped_llm_call_budget(run_id, ceiling=None):
        for _ in range(7):
            record_provider_request()
    try:
        state = cast(WorkflowState, {"hypotheses": [], "run_id": run_id})
        stats = _compute_stats(state, {})
        assert stats.llm_calls == 7
    finally:
        release_run_call_budget(run_id)


async def test_no_run_id_llm_options_does_not_crash_or_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A call under no scope must not raise and must not touch any run."""
    _disable_cache(monkeypatch)
    _record(monkeypatch, [_completion(_message('{"a": 1}'))])

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name=_LLM_CALL_BUDGET_MODEL, json_schema=_SCHEMA),
        options=LLMCallOptions(),
    )

    assert result == {"a": 1}


_LLM_BUDGET_ESCALATION_MODEL = "deepseek/deepseek-v4-flash"

_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}


def _exhausted(budget: int) -> SimpleNamespace:
    """A completion that spent ``budget`` tokens reasoning and answered none."""
    return _completion(
        _message(None),
        usage=_usage(500, budget, reasoning_tokens=budget),
        finish_reason="length",
    )


def _thinking_only(reasoning: int) -> SimpleNamespace:
    """A completion that reasoned, stopped normally, and wrote no answer."""
    return _completion(
        _message(None),
        usage=_usage(3136, reasoning, reasoning_tokens=reasoning),
        finish_reason="stop",
    )


def _provider_error(reasoning: int) -> SimpleNamespace:
    """A completion OpenRouter aborted mid-stream after some reasoning."""
    return _completion(
        _message(None),
        usage=_usage(3378, reasoning, reasoning_tokens=reasoning),
        finish_reason="error",
    )


def _record_acompletion(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    """Patch the completion seam, recording each call's kwargs.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        responses: Completion namespaces to return on successive calls. The
            last one repeats, so a test needs only as many entries as the
            distinct responses it cares about.

    Returns:
        The list the fake appends each call's kwargs to, in call order.
    """
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        index = min(len(calls) - 1, len(responses) - 1)
        return responses[index]

    install_fake_backend(monkeypatch, fake_acompletion)
    return calls


# --- classifying the empty response -----------------------------------------


async def test_budget_exhaustion_is_its_own_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty response at ``finish_reason="length"`` is budget exhaustion."""
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)])

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_LLM_BUDGET_ESCALATION_MODEL)
        )


async def test_thinking_without_answering_is_its_own_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reasoning spent, no answer, stopped normally: a different failure.

    The model chose to stop, so it did not want for room -- production
    spent 1149 tokens of an 18000 budget this way. Classifying it as
    budget exhaustion would answer it with a bigger allowance it never
    needed.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_thinking_only(1149)])

    with pytest.raises(LLMThinkingOnlyError):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_LLM_BUDGET_ESCALATION_MODEL)
        )


async def test_an_empty_response_with_no_reasoning_stays_ordinary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty answer from a call that never reasoned is a plain hiccup.

    Nothing about the request explains it, so nothing about the request
    should change; a plain retry is the remedy.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(
        monkeypatch,
        [
            _completion(
                _message("   "), usage=_usage(500, 0), finish_reason="stop"
            )
        ],
    )

    with pytest.raises(ValueError) as caught:
        await call_llm(
            "a prompt", CompletionSpec(model_name=_LLM_BUDGET_ESCALATION_MODEL)
        )
    assert type(caught.value) is ValueError


async def test_a_mid_stream_provider_error_is_not_thinking_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``finish_reason="error"`` is a provider failure, not a chosen stop.

    OpenRouter reports an upstream failure mid-stream this way; the model
    never chose to stop, so this must not be classified (and escalated) as
    a thinking-only response. Every attempt hits the same failure here, so
    the loop exhausts its attempts and the last error surfaces -- what
    matters is which type that is.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_provider_error(519)])

    with pytest.raises(ValueError) as caught:
        await call_llm(
            "a prompt", CompletionSpec(model_name=_LLM_BUDGET_ESCALATION_MODEL)
        )
    assert not isinstance(caught.value, LLMThinkingOnlyError)
    assert not isinstance(caught.value, LLMBudgetExhaustedError)


async def test_the_failure_log_reports_the_budget_actually_sent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The failure line names the floored budget, not the call site's number.

    An 8000-token call site logging "max_tokens 8000" beside
    "reasoning_tokens=18001" reads as a provider fault. The wire carried
    the floor.

    Captured at WARNING because attempt 1 of ``call_llm``'s own escalation
    loop is a non-final attempt (default ``max_attempts=3``), which logs at
    WARNING rather than ERROR (see ``test_llm_failure_logging``). The
    assertions read the WARNING and ERROR lines of all three attempts
    concatenated, so attempt 1's floored number (this test's target) and
    later attempts' escalated numbers can coexist in the same string --
    the budget reported by attempt 1 is the property under test.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)])

    with caplog.at_level("WARNING"), pytest.raises(LLMBudgetExhaustedError):
        await call_llm(
            "a prompt",
            CompletionSpec(
                model_name=_LLM_BUDGET_ESCALATION_MODEL, max_tokens=8000
            ),
        )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert f"max_tokens {THINKING_FLOOR_MAX_TOKENS}" in logged
    assert "call site asked for 8000" in logged


# --- the ladder --------------------------------------------------------------


async def test_the_ladder_raises_the_budget_then_drops_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each exhausted attempt changes the next request, in ladder order."""
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)]
    )

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_LLM_BUDGET_ESCALATION_MODEL,
                max_tokens=8000,
                json_schema=_INT_SCHEMA,
            ),
            max_attempts=3,
        )

    assert len(calls) == 3
    budgets = [call["max_tokens"] for call in calls]
    assert budgets == [
        THINKING_FLOOR_MAX_TOKENS,
        BUDGET_ESCALATION_MAX_TOKENS,
        BUDGET_ESCALATION_MAX_TOKENS,
    ]
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled", "disabled"]


async def test_the_top_rung_holds_for_every_further_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past the last rung the loop stops changing the request, not retrying.

    The ladder is finite and the attempt budget is not spent on it: a
    fourth and fifth attempt still go out, just at the settled rung.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)]
    )

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_LLM_BUDGET_ESCALATION_MODEL, json_schema=_INT_SCHEMA
            ),
            max_attempts=5,
        )

    assert len(calls) == 5
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled"] + ["disabled"] * 3


async def test_escalating_recovers_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised budget that lets the answer through ends the loop there."""
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch,
        [
            _exhausted(THINKING_FLOOR_MAX_TOKENS),
            _completion(_message('{"a":1}')),
        ],
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_LLM_BUDGET_ESCALATION_MODEL, json_schema=_INT_SCHEMA
        ),
        max_attempts=5,
    )

    assert result == {"a": 1}
    assert len(calls) == 2
    assert calls[1]["max_tokens"] == BUDGET_ESCALATION_MAX_TOKENS


async def test_a_call_already_sized_at_the_constant_still_gets_more_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rung must not resend a caller's own budget unchanged.

    ``RESEARCH_OVERVIEW_MAX_TOKENS`` sits exactly at
    ``BUDGET_ESCALATION_MAX_TOKENS`` (both 24000), so a raise expressed as
    ``max(max_tokens, BUDGET_ESCALATION_MAX_TOKENS)`` returns 24000 for
    24000: the identical request, billed again on the ``RAISED_BUDGET``
    attempt for nothing. This call site is sized the same way to catch
    exactly that regression.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_exhausted(BUDGET_ESCALATION_MAX_TOKENS)]
    )

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_LLM_BUDGET_ESCALATION_MODEL,
                max_tokens=BUDGET_ESCALATION_MAX_TOKENS,
                json_schema=_INT_SCHEMA,
            ),
            max_attempts=3,
        )

    assert len(calls) == 3
    budgets = [call["max_tokens"] for call in calls]
    # Attempt 1 sends the caller's own budget; attempt 2 (RAISED_BUDGET)
    # must send strictly more, not the same number again; attempt 3
    # (NO_THINKING) uses the same raised formula.
    assert budgets[0] == BUDGET_ESCALATION_MAX_TOKENS
    assert budgets[1] > BUDGET_ESCALATION_MAX_TOKENS
    assert budgets[2] == budgets[1]


async def test_thinking_only_skips_straight_to_disabling_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The intermediate rung is skipped: room was never the problem.

    Production ran this failure three attempts deep at identical
    settings. Spending an attempt on a raised budget would only prove
    what the finish reason already said.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(monkeypatch, [_thinking_only(1149)])

    with pytest.raises(LLMThinkingOnlyError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_LLM_BUDGET_ESCALATION_MODEL, json_schema=_INT_SCHEMA
            ),
            max_attempts=3,
        )

    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "disabled", "disabled"]


async def test_disabling_thinking_recovers_a_thinking_only_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once thinking is off the model writes the answer, and the loop ends."""
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_thinking_only(1149), _completion(_message('{"a":2}'))]
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_LLM_BUDGET_ESCALATION_MODEL, json_schema=_INT_SCHEMA
        ),
        max_attempts=5,
    )

    assert result == {"a": 2}
    assert len(calls) == 2
    assert "reasoning_effort" not in calls[1]


async def test_a_provider_error_recovers_without_disabling_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-stream provider error is a plain retry, not a ladder rung.

    Unlike a genuine thinking-only response, this must not climb to
    ``NO_THINKING`` -- the provider errored, the model never chose to stop,
    and disabling thinking for a call that needed no such thing would be
    the wrong remedy for every attempt after it.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_provider_error(519), _completion(_message('{"a":3}'))]
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_LLM_BUDGET_ESCALATION_MODEL, json_schema=_INT_SCHEMA
        ),
        max_attempts=5,
    )

    assert result == {"a": 3}
    assert len(calls) == 2
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled"]


async def test_a_schema_failure_leaves_the_budget_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only budget exhaustion escalates; a bad answer is answered by feedback.

    Raising the budget for a schema failure would spend more tokens per
    attempt on a problem more tokens do not solve.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch,
        [_completion(_message('{"a": "not an integer"}'))],
    )

    with pytest.raises(ValidationError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_LLM_BUDGET_ESCALATION_MODEL, json_schema=_INT_SCHEMA
            ),
            max_attempts=3,
        )

    budgets = {call["max_tokens"] for call in calls}
    assert budgets == {THINKING_FLOOR_MAX_TOKENS}


# --- the raised-budget formula itself ----------------------------------------


def test_escalated_max_tokens_at_below_at_and_above_the_constant() -> None:
    """Pins the three shapes a caller's own budget can take.

    8000 sits below ``BUDGET_ESCALATION_MAX_TOKENS`` and lands on the
    floor, as it always did. 24000 sits exactly at it -- the case that
    used to no-op -- and must come back strictly larger. 60000 sits above
    both the floor and ``BUDGET_ESCALATION_MAX_INCREMENT``, so the
    increment itself is what caps the raise, at ``max_tokens +
    BUDGET_ESCALATION_MAX_INCREMENT``.
    """
    assert (
        escalated_max_tokens(8000, BudgetEscalation.RAISED_BUDGET)
        == BUDGET_ESCALATION_MAX_TOKENS
        == 24000
    )
    assert (
        escalated_max_tokens(
            BUDGET_ESCALATION_MAX_TOKENS, BudgetEscalation.RAISED_BUDGET
        )
        == 36000
    )
    assert escalated_max_tokens(60000, BudgetEscalation.RAISED_BUDGET) == 84000


def test_a_caller_sized_above_the_floor_is_never_cut_down() -> None:
    """The promise the docstrings make, checked past the constant itself.

    Any budget at or above ``BUDGET_ESCALATION_MAX_TOKENS`` must come back
    strictly larger -- never equal (the old no-op) and never smaller.
    """
    for max_tokens in (
        BUDGET_ESCALATION_MAX_TOKENS,
        BUDGET_ESCALATION_MAX_TOKENS + 1,
        200_000,
    ):
        raised = escalated_max_tokens(
            max_tokens, BudgetEscalation.RAISED_BUDGET
        )
        assert raised > max_tokens
        assert raised <= max_tokens + BUDGET_ESCALATION_MAX_INCREMENT


def test_none_escalation_leaves_the_budget_untouched() -> None:
    """The first attempt is not a rung, so nothing here should apply to it."""
    assert escalated_max_tokens(8000, BudgetEscalation.NONE) == 8000
    assert escalated_max_tokens(60000, BudgetEscalation.NONE) == 60000


def _declared_caps() -> dict[str, int]:
    """Every ``*_MAX_TOKENS_CAP`` constant, found by name not by list."""
    return {
        name: value
        for name, value in vars(constants).items()
        if name.endswith("_MAX_TOKENS_CAP")
        and not name.startswith("_")
        and isinstance(value, int)
    }


def test_every_scaled_cap_clears_the_thinking_floor() -> None:
    """No cap may sit below the floor, because such a cap says two things.

    Reasoning is billed against ``max_tokens`` alongside the answer, so
    ``_apply_thinking_args`` lifts every thinking call to the floor. A cap
    beneath it is therefore overwritten on the DeepSeek-family models this
    engine deploys on, and enforced as written on a provider with no
    thinking mode -- one constant, two different ceilings, and the one that
    is silently discarded is the one production uses.

    ``DRAFT_MAX_TOKENS_CAP`` was that cap at 16000, discovered only by
    reading the arithmetic. Asserted over every cap the module declares so
    the next one is discovered by a failing test instead.
    """
    caps = _declared_caps()

    assert caps, "no *_MAX_TOKENS_CAP constants found; did they get renamed?"
    below = {
        name: value
        for name, value in caps.items()
        if value <= THINKING_FLOOR_MAX_TOKENS
    }
    assert not below, (
        f"caps at or below THINKING_FLOOR_MAX_TOKENS "
        f"({THINKING_FLOOR_MAX_TOKENS}): {below}. A cap under the floor is "
        "overwritten wherever the model reasons; raise it above the floor or "
        "delete it."
    )


def test_the_floor_is_the_thinking_budget_under_another_name() -> None:
    """The two names are one derived number, not two tuned ones.

    ``THINKING_FLOOR_MAX_TOKENS`` is the budget the nodes sized for thinking
    from the start already run against, which is the whole argument for
    raising every other thinking call to it: it asks for nothing this
    deployment has not already proven. Splitting the values would quietly
    retire that argument, so the tie is asserted rather than left implicit.
    """
    assert THINKING_FLOOR_MAX_TOKENS == constants.THINKING_MAX_TOKENS


def test_base_budgets_below_the_floor_are_the_designed_case() -> None:
    """A base under the floor is the floor working, not a defect.

    The counterpart to the cap rule, kept next to it so the two are read
    together: bases describe what a call's answer costs and are *meant* to
    be superseded, caps describe a ceiling and must not be. Without this,
    "every budget must clear the floor" is the obvious over-correction, and
    it would mean sending 18000 to a literature-review query call that
    answers in a few hundred tokens on a provider that never reasons.
    """
    for base in (
        constants.DEFAULT_MAX_TOKENS,
        constants.EXTENDED_MAX_TOKENS,
        constants.LONG_MAX_TOKENS,
    ):
        assert base < THINKING_FLOOR_MAX_TOKENS


def test_the_draft_budget_never_reaches_its_own_cap() -> None:
    """The draft cap is a runaway backstop, not a ceiling runs meet.

    The base dominates the sum at every count a run tier can ask for, so
    the cap's value is free to be chosen for coherence with the floor and
    its sibling caps rather than tuned. Pinned because that freedom is
    exactly what stops holding if per-hypothesis pricing is ever raised.

    The count is the largest tier's ``initial_hypotheses_count`` (ultra, in
    the app's ``run_modes.RUN_TIER_DEFAULTS``), restated rather than
    imported because the engine is a library that knows nothing about the
    app's tiers. It is also generous: the coordinator routes only about half
    of a batch to the tool-based path, so a real draft call asks for fewer.
    """
    largest_tier_count = 16
    budget = constants.scaled_max_tokens(
        constants.DEEP_HYPOTHESIS_MAX_TOKENS,
        largest_tier_count,
        per_item=constants.DRAFT_TOKENS_PER_HYPOTHESIS,
        cap=constants.DRAFT_MAX_TOKENS_CAP,
    )

    assert budget < constants.DRAFT_MAX_TOKENS_CAP
    assert budget < THINKING_FLOOR_MAX_TOKENS


def test_deep_hypothesis_budget_is_a_base_below_the_floor() -> None:
    """The K6 generation budget funds the answer; the floor funds thinking.

    ``DEEP_HYPOTHESIS_MAX_TOKENS`` raised the generation family's answer
    budget above ``EXTENDED_MAX_TOKENS`` without becoming a ceiling on a
    thinking model: it must stay below the floor so ``_apply_thinking_args``
    still replaces it there, exactly like the other answer bases, while
    non-thinking providers honor the larger answer allowance.
    """
    assert constants.EXTENDED_MAX_TOKENS < constants.DEEP_HYPOTHESIS_MAX_TOKENS
    assert constants.DEEP_HYPOTHESIS_MAX_TOKENS < THINKING_FLOOR_MAX_TOKENS


def test_research_overview_budget_clears_the_floor() -> None:
    """The K6 overview budget must bind on thinking models too.

    The overview's depth guidance asks for a multi-paragraph strategy
    document plus an NIH aims page; on a thinking model the chain of
    thought and that answer share one allowance, so a budget at or below
    the floor would leave the answer whatever the reasoning did not spend.
    The budget sits at the largest scaled batch cap already proven in
    production, nowhere beyond it.
    """
    assert THINKING_FLOOR_MAX_TOKENS < constants.RESEARCH_OVERVIEW_MAX_TOKENS
    assert constants.RESEARCH_OVERVIEW_MAX_TOKENS <= (
        constants.REVIEW_BATCH_MAX_TOKENS_CAP
    )

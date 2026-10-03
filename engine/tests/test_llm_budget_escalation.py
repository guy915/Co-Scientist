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
    """Plain calls have three rungs; JSON parsing failures have a separate
    retry budget."""
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
    """Future callers use the original request key, not the successful retry
    budget."""
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
    assert len(calls) == 2

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
    failures: list[SimpleNamespace | Exception] = [
        ValueError("transient provider hiccup") for _ in range(fail_times)
    ]
    return [*failures, ok]


def test_no_run_id_never_raises_and_counts_nothing() -> None:
    record_provider_request()
    record_provider_request()


def test_scope_with_none_run_id_is_also_a_no_op() -> None:
    with scoped_llm_call_budget(None, ceiling=1):
        record_provider_request()
        record_provider_request()
        record_provider_request()


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
    run_id = "run-reenter-1"
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
    with scoped_llm_call_budget(run_id, ceiling=None):
        record_provider_request()
    assert current_run_call_count(run_id) == 2
    release_run_call_budget(run_id)


def test_first_ceiling_seen_wins_on_reentry() -> None:
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


async def test_call_llm_json_counts_one_per_provider_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    return _completion(
        _message(None),
        usage=_usage(500, budget, reasoning_tokens=budget),
        finish_reason="length",
    )


def _thinking_only(reasoning: int) -> SimpleNamespace:
    """More room cannot fix thinking-only output; recovery must change
    reasoning."""
    return _completion(
        _message(None),
        usage=_usage(3136, reasoning, reasoning_tokens=reasoning),
        finish_reason="stop",
    )


def _provider_error(reasoning: int) -> SimpleNamespace:
    """Transport failures must not be mistaken for reasoning exhaustion."""
    return _completion(
        _message(None),
        usage=_usage(3378, reasoning, reasoning_tokens=reasoning),
        finish_reason="error",
    )


def _record_acompletion(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        index = min(len(calls) - 1, len(responses) - 1)
        return responses[index]

    install_fake_backend(monkeypatch, fake_acompletion)
    return calls


async def test_budget_exhaustion_is_its_own_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)])

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_LLM_BUDGET_ESCALATION_MODEL)
        )


async def test_thinking_without_answering_is_its_own_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_thinking_only(1149)])

    with pytest.raises(LLMThinkingOnlyError):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_LLM_BUDGET_ESCALATION_MODEL)
        )


async def test_an_empty_response_with_no_reasoning_stays_ordinary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    """More room cannot fix thinking-only output; recovery must change
    reasoning."""
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
    """Logs must name the sent floor rather than the smaller caller budget."""
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


async def test_the_ladder_raises_the_budget_then_drops_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    """The finite token ladder is separate from the configured attempt
    budget."""
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
    """Repeating an identical exhausted budget buys another identical
    failure."""
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
    assert budgets[0] == BUDGET_ESCALATION_MAX_TOKENS
    assert budgets[1] > BUDGET_ESCALATION_MAX_TOKENS
    assert budgets[2] == budgets[1]


async def test_thinking_only_skips_straight_to_disabling_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """More room cannot fix thinking-only output; recovery must change
    reasoning."""
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
    """More room cannot fix thinking-only output; recovery must change
    reasoning."""
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
    """Transport failures must not be mistaken for reasoning exhaustion."""
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
    """Extra tokens do not repair a schema mismatch; feedback does."""
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


def test_escalated_max_tokens_at_below_at_and_above_the_constant() -> None:
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
    assert escalated_max_tokens(8000, BudgetEscalation.NONE) == 8000
    assert escalated_max_tokens(60000, BudgetEscalation.NONE) == 60000


def _declared_caps() -> dict[str, int]:
    return {
        name: value
        for name, value in vars(constants).items()
        if name.endswith("_MAX_TOKENS_CAP")
        and not name.startswith("_")
        and isinstance(value, int)
    }


def test_every_scaled_cap_clears_the_thinking_floor() -> None:
    """A cap below the floor gives thinking and ordinary calls different
    ceilings."""
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
    assert THINKING_FLOOR_MAX_TOKENS == constants.THINKING_MAX_TOKENS


def test_base_budgets_below_the_floor_are_the_designed_case() -> None:
    """Base budgets fund answers; the floor additionally funds reasoning."""
    for base in (
        constants.DEFAULT_MAX_TOKENS,
        constants.EXTENDED_MAX_TOKENS,
        constants.LONG_MAX_TOKENS,
    ):
        assert base < THINKING_FLOOR_MAX_TOKENS


def test_the_draft_budget_never_reaches_its_own_cap() -> None:
    """The engine cannot import app tier definitions; this pins the
    production sizing."""
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
    """Tournament entrants require completed review stamps."""
    assert constants.EXTENDED_MAX_TOKENS < constants.DEEP_HYPOTHESIS_MAX_TOKENS
    assert constants.DEEP_HYPOTHESIS_MAX_TOKENS < THINKING_FLOOR_MAX_TOKENS


def test_research_overview_budget_clears_the_floor() -> None:
    """Reasoning and prose share the same completion budget."""
    assert THINKING_FLOOR_MAX_TOKENS < constants.RESEARCH_OVERVIEW_MAX_TOKENS
    assert constants.RESEARCH_OVERVIEW_MAX_TOKENS <= (
        constants.REVIEW_BATCH_MAX_TOKENS_CAP
    )

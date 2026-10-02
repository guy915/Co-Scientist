"""Tool turns share bounded retries, but retain their request shaping.

The retry boundary stops before execution: tools from completed turns are
not replayed. Mandatory reasoning still uses the tool request's raised
budget rather than changing its effort.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from litellm.exceptions import BadRequestError
from litellm.exceptions import ContextWindowExceededError as ContextWindow

from co_scientist.exceptions import (
    FreeModelEligibilityError,
    LLMBudgetExhaustedError,
    LLMCallBudgetExceededError,
    LLMTimeoutError,
)
from tests._llm_attempt_fakes import (
    GATEWAY_MODEL,
    TOOLS,
    Driver,
    call_ceiling,
    echo_executor,
    exhausted,
    ok,
    reasoning_mandatory,
    thinking_only,
    timed_out,
    too_big,
)
from tests._llm_attempt_fakes import drive as drive
from tests._llm_wrapper_fakes import (
    make_completion,
    make_message,
    make_tool_call,
)


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (timed_out, LLMTimeoutError),
        (call_ceiling, LLMCallBudgetExceededError),
        (too_big, ContextWindow),
        (lambda: FreeModelEligibilityError("no"), FreeModelEligibilityError),
    ],
    ids=[
        "timeout",
        "call-budget-ceiling",
        "context-window",
        "free-eligibility",
    ],
)
async def test_a_tool_turn_failure_no_rung_answers_propagates_at_once(
    drive: Driver,
    failure: Callable[[], Exception],
    error_type: type[Exception],
) -> None:
    run = await drive(TOOLS, [failure()])

    assert type(run.error) is error_type
    assert len(run.calls) == 1
    assert run.slept == []
    assert run.throttled == 0
    assert run.retries == 0
    assert run.retry_debug == []
    assert run.logged == (
        []
        if error_type is FreeModelEligibilityError
        else [("terminal", "ERROR")]
    )


async def test_a_tool_turn_climbs_the_ladder_and_gives_up_at_the_top(
    drive: Driver,
) -> None:
    run = await drive(TOOLS, [exhausted()])

    assert isinstance(run.error, LLMBudgetExhaustedError)
    assert len(run.calls) == 3, "the top rung is not resent"
    assert run.thinking == ["enabled", "enabled", "disabled"]
    first, raised, last = run.max_tokens
    assert raised > first
    assert last == raised
    assert run.slept == []
    assert run.retries == 2
    assert len(run.retry_debug) == 2
    assert run.logged == [
        ("failed", "WARNING"),
        ("escalated", "WARNING"),
        ("failed", "WARNING"),
        ("escalated", "WARNING"),
        ("failed", "ERROR"),
    ]


async def test_a_tool_turn_thinking_only_answer_skips_to_thinking_off(
    drive: Driver,
) -> None:
    run = await drive(TOOLS, [thinking_only(), ok(TOOLS)])

    assert run.error is None
    assert run.thinking == ["enabled", "disabled"]
    assert run.retries == 1
    assert run.logged == [("failed", "WARNING"), ("escalated", "WARNING")]


async def test_a_tool_turn_mandatory_reasoning_rung_sends_no_minimal_effort(
    drive: Driver,
) -> None:
    entry = replace(TOOLS, model=GATEWAY_MODEL)

    run = await drive(entry, [reasoning_mandatory(), ok(entry)])

    assert run.error is None
    assert len(run.calls) == 2
    # Unlike call_llm and call_llm_json, the tool turn resends the very
    # reasoning request it sent before (no minimal-effort tier), at the
    # raised budget.
    assert run.reasoning == [{"enabled": True, "effort": "high"}] * 2
    assert run.max_tokens[1] > run.max_tokens[0]
    assert run.logged == [("failed", "WARNING"), ("escalated", "WARNING")]


async def test_mandatory_reasoning_refusals_exhaust_a_tool_turn(
    drive: Driver,
) -> None:
    entry = replace(TOOLS, model=GATEWAY_MODEL)

    run = await drive(entry, [reasoning_mandatory()])

    assert isinstance(run.error, BadRequestError)
    assert len(run.calls) == 3
    assert run.logged == [
        ("failed", "WARNING"),
        ("escalated", "WARNING"),
        ("failed", "WARNING"),
        ("failed", "ERROR"),
    ]


async def test_a_tool_turn_retry_never_spans_tool_execution(
    drive: Driver,
) -> None:
    asked_for_a_tool = make_completion(
        make_message(None, tool_calls=[make_tool_call("c1", "search", "{}")])
    )
    executed: list[str] = []

    async def executor(tc: Any) -> dict[str, Any]:
        executed.append(tc.id)
        return await echo_executor(tc)

    entry = replace(TOOLS, executor=executor)

    run = await drive(entry, [asked_for_a_tool, exhausted(), ok(entry)])

    assert run.error is None
    assert len(run.calls) == 3
    assert executed == ["c1"], "the answerless turn must not rerun the tools"
    # The retried turn is the second one, and it resends the same transcript.
    roles = [m["role"] for m in run.calls[2]["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert run.calls[1]["messages"] == run.calls[2]["messages"]
    # The rung resets for the next turn: it starts at the caller's budget.
    assert run.max_tokens[1] == run.max_tokens[0]
    assert run.max_tokens[2] > run.max_tokens[1]

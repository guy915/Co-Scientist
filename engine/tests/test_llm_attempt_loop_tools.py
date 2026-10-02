"""What the tool turn of ``call_llm_with_tools`` answers a failure with.

Two behaviours here look like omissions and are pinned as they are, not as
they should be, because changing either is an open product decision:

* A tool turn retries a failure only when the escalation ladder has a rung
  for it. A 429, a provider outage, a platform cap and an ordinary provider
  error each propagate on the first attempt -- no throttle wait, no
  rate-limit park (the raw 429 comes back, not ``LLMRateLimitParkError``),
  no retry telemetry. Every failure is logged once, at ERROR, as ``Error in
  LLM tool call loop``.
* At the mandatory-reasoning rung it resends the reasoning request it
  already sent, at the raised budget. ``call_llm`` and ``call_llm_json``
  send minimal effort there.

What a tool turn does share with the other entry points is the ladder, and
the rule that a retry never spans tool execution: a turn that answers
nothing is resent, the tools it asked for on an earlier turn are not rerun.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from litellm.exceptions import APIError, BadRequestError, RateLimitError
from litellm.exceptions import ContextWindowExceededError as ContextWindow

from co_scientist.exceptions import (
    FreeModelEligibilityError,
    LLMBudgetExhaustedError,
    LLMCallBudgetExceededError,
    LLMThinkingOnlyError,
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
    overloaded,
    rate_limited,
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
        (rate_limited, RateLimitError),
        (lambda: rate_limited(reset_in=7200), RateLimitError),
        (overloaded, APIError),
        (lambda: RuntimeError("provider exploded"), RuntimeError),
        (timed_out, LLMTimeoutError),
        (call_ceiling, LLMCallBudgetExceededError),
        (too_big, ContextWindow),
        (lambda: FreeModelEligibilityError("no"), FreeModelEligibilityError),
    ],
    ids=[
        "throttle",
        "platform-cap",
        "outage",
        "ordinary",
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
    assert run.logged == [("tool-terminal", "ERROR")]


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
    assert run.retries == 0, "tool turns record no retry telemetry"
    assert run.retry_debug == []
    assert run.logged == [
        ("escalated", "WARNING"),
        ("escalated", "WARNING"),
        ("tool-terminal", "ERROR"),
    ]


async def test_a_tool_turn_thinking_only_answer_skips_to_thinking_off(
    drive: Driver,
) -> None:
    run = await drive(TOOLS, [thinking_only(), ok(TOOLS)])

    assert run.error is None
    assert run.thinking == ["enabled", "disabled"]
    assert run.retries == 0
    assert run.logged == [("escalated", "WARNING")]


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
    assert run.logged == [("escalated", "WARNING")]


async def test_a_second_mandatory_reasoning_refusal_ends_a_tool_turn(
    drive: Driver,
) -> None:
    entry = replace(TOOLS, model=GATEWAY_MODEL)

    run = await drive(entry, [reasoning_mandatory()])

    assert isinstance(run.error, BadRequestError)
    assert len(run.calls) == 2
    assert run.logged == [("escalated", "WARNING"), ("tool-terminal", "ERROR")]


@pytest.mark.parametrize("mandatory_first", [False, True])
async def test_alternating_reasoning_failures_stop_before_revisiting_a_rung(
    drive: Driver, mandatory_first: bool
) -> None:
    entry = replace(TOOLS, model=GATEWAY_MODEL)
    mandatory = reasoning_mandatory()
    pair = (
        [mandatory, thinking_only()]
        if mandatory_first
        else [thinking_only(), mandatory]
    )
    # A finite reproducer: the old loop reaches "fine" on attempt 21.
    run = await drive(entry, pair * 10 + [ok(entry)])

    if mandatory_first:
        assert run.error is mandatory, (
            f"expected current refusal; attempts={len(run.calls)}, "
            f"result={run.result!r}"
        )
    else:
        assert isinstance(run.error, LLMThinkingOnlyError), (
            f"expected current thinking failure; attempts={len(run.calls)}, "
            f"result={run.result!r}"
        )
    assert run.result is None, "the success sentinel must remain unreachable"
    assert len(run.calls) == 3 <= 4
    enabled = {"enabled": True, "effort": "high"}
    disabled = {"enabled": False}
    assert run.reasoning == (
        [enabled, enabled, disabled]
        if mandatory_first
        else [enabled, disabled, enabled]
    )
    assert run.max_tokens == [18000, 24000, 24000]
    assert all(c["messages"] == run.calls[0]["messages"] for c in run.calls)
    assert run.slept == []
    assert run.throttled == run.retries == 0
    assert run.retry_debug == []
    assert not any(kind == "park" for kind, _ in run.logged)
    assert run.logged[-1] == ("tool-terminal", "ERROR")


async def test_a_tool_turn_can_recover_on_the_fourth_distinct_rung(
    drive: Driver,
) -> None:
    entry = replace(TOOLS, model=GATEWAY_MODEL)
    run = await drive(
        entry, [exhausted(), exhausted(), reasoning_mandatory(), ok(entry)]
    )

    assert run.error is None
    assert run.result[0] == "fine"
    assert len(run.calls) == 4
    assert run.max_tokens == [18000, 24000, 24000, 24000]
    assert run.reasoning == [
        {"enabled": True, "effort": "high"},
        {"enabled": True, "effort": "high"},
        {"enabled": False},
        {"enabled": True, "effort": "high"},
    ]
    assert run.slept == []
    assert run.throttled == run.retries == 0


async def test_each_tool_turn_can_visit_the_entire_ladder_independently(
    drive: Driver,
) -> None:
    asked_for_a_tool = make_completion(
        make_message(None, tool_calls=[make_tool_call("c1", "search", "{}")])
    )
    executed: list[str] = []

    async def executor(tc: Any) -> dict[str, Any]:
        executed.append(tc.id)
        return await echo_executor(tc)

    entry = replace(TOOLS, model=GATEWAY_MODEL, executor=executor)
    recovery = [exhausted(), exhausted(), reasoning_mandatory()]
    run = await drive(
        entry, [*recovery, asked_for_a_tool, *recovery, ok(entry)]
    )

    assert run.error is None
    assert run.result[0] == "fine"
    assert len(run.calls) == 8
    assert run.max_tokens == [18000, 24000, 24000, 24000] * 2
    assert run.reasoning[:4] == run.reasoning[4:]
    assert executed == ["c1"]
    for call in run.calls[4:]:
        assert [m["role"] for m in call["messages"]] == [
            "user",
            "assistant",
            "tool",
        ]
    assert run.slept == []
    assert run.throttled == run.retries == 0


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

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError
from litellm.exceptions import APIError, BadRequestError, RateLimitError
from litellm.exceptions import ContextWindowExceededError as ContextWindow

from co_scientist.exceptions import (
    FreeModelEligibilityError,
    LLMBudgetExhaustedError,
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
    LLMThinkingOnlyError,
    LLMTimeoutError,
)
from co_scientist.llm import LLMCallOptions
from co_scientist.llm.attempts.escalation import BudgetEscalation
from co_scientist.llm.attempts.retry import (
    Accepted,
    Attempt,
    AttemptPlan,
    Judge,
    Rejected,
    run_attempts,
)
from tests._llm_fake import (
    GATEWAY_MODEL,
    JSON,
    SCHEMA_FEEDBACK,
    STANDARD,
    TOOLS,
    WAITED_THEN_GAVE_UP,
    Driver,
    Entry,
    call_ceiling,
    echo_executor,
    exhausted,
    make_completion,
    make_message,
    make_tool_call,
    ok,
    overloaded,
    rate_limited,
    reasoning_mandatory,
    thinking_only,
    timed_out,
    too_big,
    wrong_type,
)
from tests._llm_fake import drive as drive

__all__ = ["drive"]


@STANDARD
async def test_a_throttled_call_waits_a_growing_jittered_interval(
    drive: Driver, entry: Entry
) -> None:
    run = await drive(entry, [rate_limited()])

    assert isinstance(run.error, RateLimitError)
    assert len(run.calls) == 3
    assert len(run.slept) == 2, "every retry but the last waits first"
    assert 1.0 <= run.slept[0] <= 2.0
    assert 2.0 <= run.slept[1] <= 4.0
    assert run.throttled == 2
    assert run.retries == 2
    assert run.retry_announcements == [("retry", "INFO")] * 2
    assert run.logged == WAITED_THEN_GAVE_UP
    assert len(set(run.max_tokens)) == 1, "a throttle does not change the rung"
    assert set(run.thinking) == {"enabled"}


@STANDARD
async def test_a_throttled_call_recovers_after_one_wait(
    drive: Driver, entry: Entry
) -> None:
    run = await drive(entry, [rate_limited(), ok(entry)])

    assert run.error is None
    assert run.result == ("fine" if entry.kind == "text" else {"a": 1})
    assert len(run.calls) == 2
    assert len(run.slept) == 1
    assert run.throttled == 1
    assert run.retries == 1
    assert run.retry_announcements == [("retry", "INFO")]
    assert run.logged == [("failed", "WARNING"), ("waited", "WARNING")]


@STANDARD
async def test_a_platform_cap_parks_the_task_without_waiting_or_retrying(
    drive: Driver, entry: Entry
) -> None:
    run = await drive(entry, [rate_limited(reset_in=7200)])

    assert isinstance(run.error, LLMRateLimitParkError)
    assert run.error.reason == "x_ratelimit_reset_header"
    assert run.error.resume_at == pytest.approx(time.time() + 7200, abs=5.0)
    assert len(run.calls) == 1
    assert run.slept == []
    assert run.throttled == 0
    assert run.retries == 0
    assert run.logged == [("park", "WARNING")]


@STANDARD
async def test_a_provider_outage_waits_minutes_and_is_not_throttling(
    drive: Driver, entry: Entry
) -> None:
    run = await drive(entry, [overloaded()])

    assert isinstance(run.error, APIError)
    assert len(run.calls) == 3
    assert len(run.slept) == 2
    assert 15.0 <= run.slept[0] <= 30.0
    assert 30.0 <= run.slept[1] <= 60.0
    assert run.throttled == 0, "an overload must not shrink the next wave"
    assert run.retries == 2
    assert run.logged == WAITED_THEN_GAVE_UP
    assert len(set(run.max_tokens)) == 1


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (timed_out, LLMTimeoutError),
        (call_ceiling, LLMCallBudgetExceededError),
        (too_big, ContextWindow),
    ],
    ids=["timeout", "call-budget-ceiling", "context-window"],
)
@STANDARD
async def test_a_failure_the_same_request_cannot_survive_is_never_retried(
    drive: Driver,
    entry: Entry,
    failure: Callable[[], Exception],
    error_type: type[Exception],
) -> None:
    run = await drive(entry, [failure()])

    assert isinstance(run.error, error_type)
    assert len(run.calls) == 1
    assert run.slept == []
    assert run.throttled == 0
    assert run.retries == 0
    assert run.logged == [("terminal", "ERROR")]


@STANDARD
async def test_a_free_model_eligibility_failure_is_re_raised_silently(
    drive: Driver, entry: Entry
) -> None:
    run = await drive(entry, [FreeModelEligibilityError("route is not free")])

    assert isinstance(run.error, FreeModelEligibilityError)
    assert len(run.calls) == 1
    assert run.slept == []
    assert run.retries == 0
    assert run.logged == []


@STANDARD
async def test_an_ordinary_provider_error_is_retried_in_place_without_waiting(
    drive: Driver, entry: Entry
) -> None:
    run = await drive(entry, [RuntimeError("provider exploded")])

    assert isinstance(run.error, RuntimeError)
    assert len(run.calls) == 3
    assert run.slept == []
    assert run.retries == 2
    assert run.logged == [
        ("failed", "WARNING"),
        ("failed", "WARNING"),
        ("failed", "ERROR"),
    ]
    assert len(set(run.max_tokens)) == 1
    assert set(run.thinking) == {"enabled"}


@STANDARD
async def test_budget_exhaustion_climbs_to_thinking_off_and_then_gives_up(
    drive: Driver, entry: Entry
) -> None:
    run = await drive(entry, [exhausted()])

    assert isinstance(run.error, LLMBudgetExhaustedError)
    assert len(run.calls) == 3
    assert run.thinking == ["enabled", "enabled", "disabled"]
    first, raised, last = run.max_tokens
    assert raised > first
    assert last == raised, "the top rung resends the raised budget"
    assert run.slept == []
    assert run.retries == 2
    assert run.logged == [
        ("failed", "WARNING"),
        ("escalated", "WARNING"),
        ("failed", "WARNING"),
        ("escalated", "WARNING"),
        ("failed", "ERROR"),
    ]


@STANDARD
async def test_a_thinking_only_attempt_skips_to_thinking_off_and_recovers(
    drive: Driver, entry: Entry
) -> None:
    run = await drive(entry, [thinking_only(), ok(entry)])

    assert run.error is None
    assert run.thinking == ["enabled", "disabled"]
    assert run.slept == []
    assert run.retries == 1
    assert run.retry_announcements == [("retry", "INFO")]
    assert run.logged == [("failed", "WARNING"), ("escalated", "WARNING")]


@STANDARD
async def test_standard_plans_can_revisit_rungs_within_their_attempt_budget(
    drive: Driver, entry: Entry
) -> None:
    entry = replace(entry, model=GATEWAY_MODEL)
    run = await drive(
        entry,
        [thinking_only(), reasoning_mandatory()] * 2 + [ok(entry)],
        max_attempts=5,
    )

    assert run.error is None
    assert run.result == ("fine" if entry.kind == "text" else {"a": 1})
    assert len(run.calls) == 5
    assert run.retries == 4
    assert run.slept == []
    assert run.reasoning == [
        {"enabled": True, "effort": "high"},
        {"enabled": False},
        {"enabled": True, "effort": "low"},
        {"enabled": False},
        {"enabled": True, "effort": "low"},
    ]


@STANDARD
async def test_a_mandatory_reasoning_refusal_is_answered_by_minimal_effort(
    drive: Driver, entry: Entry
) -> None:
    entry = replace(
        entry,
        model=GATEWAY_MODEL,
        options=LLMCallOptions(enable_thinking=False),
    )

    run = await drive(entry, [reasoning_mandatory(), ok(entry)])

    assert run.error is None
    assert run.reasoning == [
        {"enabled": False},
        {"enabled": True, "effort": "low"},
    ]
    assert run.max_tokens[1] > run.max_tokens[0]
    assert run.slept == []
    assert run.logged == [("failed", "WARNING"), ("escalated", "WARNING")]


@STANDARD
async def test_a_repeated_mandatory_reasoning_refusal_exhausts_the_attempts(
    drive: Driver, entry: Entry
) -> None:
    entry = replace(
        entry,
        model=GATEWAY_MODEL,
        options=LLMCallOptions(enable_thinking=False),
    )

    run = await drive(entry, [reasoning_mandatory()])

    assert isinstance(run.error, BadRequestError)
    assert len(run.calls) == 3
    assert run.reasoning == [
        {"enabled": False},
        {"enabled": True, "effort": "low"},
        {"enabled": True, "effort": "low"},
    ]
    assert run.slept == [], "a 400 is a request problem, not a wait"
    assert run.logged == [
        ("failed", "WARNING"),
        ("escalated", "WARNING"),
        ("failed", "WARNING"),
        ("failed", "ERROR"),
    ]


async def test_a_schema_failure_retries_at_once_with_feedback_on_the_same_rung(
    drive: Driver,
) -> None:
    run = await drive(JSON, [wrong_type(), ok(JSON)])

    assert run.result == {"a": 1}
    assert len(run.calls) == 2
    assert run.slept == []
    assert run.retries == 1
    assert run.retry_announcements == [("retry", "INFO")]
    first, second = run.prompts
    assert SCHEMA_FEEDBACK not in first
    assert second.startswith("a prompt")
    assert SCHEMA_FEEDBACK in second
    assert run.max_tokens[0] == run.max_tokens[1]
    assert run.thinking == ["enabled", "enabled"]
    assert run.logged == [("schema", "WARNING")]
    assert ("feedback-debug", "DEBUG") in run.lines


async def test_a_schema_failure_on_every_attempt_raises_the_validation_error(
    drive: Driver,
) -> None:
    run = await drive(JSON, [wrong_type()])

    assert isinstance(run.error, ValidationError)
    assert "after 3 attempts" in run.error.message
    assert len(run.calls) == 3
    assert run.slept == []
    assert run.logged[:3] == [("schema", "WARNING")] * 3
    assert {level for _, level in run.logged[3:]} == {"ERROR"}
    assert run.prompts[2].count(SCHEMA_FEEDBACK) == 1


async def test_a_schema_failure_holds_the_rung_an_escalation_reached(
    drive: Driver,
) -> None:
    script = [exhausted(), wrong_type(), ok(JSON)]

    run = await drive(JSON, script, max_attempts=4)

    assert run.result == {"a": 1}
    first, raised, held = run.max_tokens
    assert raised > first
    assert held == raised
    assert run.thinking == ["enabled", "enabled", "enabled"]


async def test_feedback_outlives_an_attempt_that_failed_before_judging(
    drive: Driver,
) -> None:
    script = [wrong_type(), RuntimeError("blip"), ok(JSON)]

    run = await drive(JSON, script, max_attempts=4)

    assert run.result == {"a": 1}
    assert SCHEMA_FEEDBACK in run.prompts[1]
    assert run.prompts[2] == run.prompts[1]


async def test_a_final_attempt_call_failure_is_not_a_parse_error(
    drive: Driver,
) -> None:
    script = [wrong_type(), RuntimeError("provider exploded")]

    run = await drive(JSON, script, max_attempts=2)

    assert isinstance(run.error, RuntimeError)
    assert len(run.calls) == 2


@pytest.mark.parametrize("mandatory_first", [False, True])
async def test_escalation_only_plan_stops_before_revisiting_a_rung(
    monkeypatch: pytest.MonkeyPatch,
    mandatory_first: bool,
) -> None:
    import asyncio

    from co_scientist.exceptions import LLMThinkingOnlyError
    from co_scientist.llm import rate_limited_attempt_count, scoped_telemetry
    from co_scientist.llm.attempts.escalation import BudgetEscalation
    from co_scientist.llm.attempts.retry import (
        AttemptPlan,
        run_attempts,
    )

    mandatory = reasoning_mandatory()
    thinking = LLMThinkingOnlyError("reasoning stopped without an answer")
    failures = (
        [mandatory, thinking] if mandatory_first else [thinking, mandatory]
    )
    script: list[Any] = failures * 10 + ["success sentinel"]
    attempts: list[Attempt] = []
    waited: list[float] = []

    async def make_attempt(attempt: Attempt) -> str:
        attempts.append(attempt)
        result = script.pop(0)
        if isinstance(result, Exception):
            raise result
        return str(result)

    async def sleep(delay: float) -> None:
        waited.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    throttled_before = rate_limited_attempt_count()
    with (
        scoped_telemetry("escalation-only") as telemetry,
        pytest.raises(type(failures[0])) as raised,
    ):
        await run_attempts(
            make_attempt, AttemptPlan.escalation_only(GATEWAY_MODEL)
        )
    assert raised.value is failures[0]
    assert len(attempts) == 3 <= 4
    expected = [
        BudgetEscalation.MINIMAL_REASONING_REQUIRED,
        BudgetEscalation.NO_THINKING,
    ]
    assert [attempt.rung for attempt in attempts] == [
        BudgetEscalation.NONE,
        *(expected if mandatory_first else expected[::-1]),
    ]
    assert not waited
    assert rate_limited_attempt_count() == throttled_before
    assert sum(usage["retries"] for usage in telemetry.snapshot().values()) == 0
    assert "success sentinel" in script


async def test_escalation_only_ladder_is_finite_and_call_local() -> None:
    from co_scientist.llm.attempts.escalation import BudgetEscalation
    from co_scientist.llm.attempts.retry import AttemptPlan, run_attempts

    attempts: list[Attempt] = []
    for _ in range(2):
        failures = [
            LLMBudgetExhaustedError("ceiling"),
            LLMBudgetExhaustedError("raised ceiling"),
            reasoning_mandatory(),
        ]

        async def make_attempt(
            attempt: Attempt, failures: list[Exception] = failures
        ) -> str:
            attempts.append(attempt)
            if failures:
                raise failures.pop(0)
            return "fine"

        assert (
            await run_attempts(
                make_attempt, AttemptPlan.escalation_only(GATEWAY_MODEL)
            )
            == "fine"
        )
    assert [attempt.rung for attempt in attempts] == [
        BudgetEscalation.NONE,
        BudgetEscalation.RAISED_BUDGET,
        BudgetEscalation.NO_THINKING,
        BudgetEscalation.MINIMAL_REASONING_REQUIRED,
    ] * 2
    assert [attempt.number for attempt in attempts] == [1, 2, 3, 4] * 2


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
async def test_a_tool_turn_unretryable_failure_propagates_at_once(
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
    assert run.retry_announcements == []
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
    assert run.retry_announcements == [("retry", "INFO")] * 2
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
    assert run.retry_announcements == [("retry", "INFO")]
    assert run.logged == [("failed", "WARNING"), ("escalated", "WARNING")]


async def test_a_tool_turn_mandatory_reasoning_rung_sends_no_minimal_effort(
    drive: Driver,
) -> None:
    entry = replace(TOOLS, model=GATEWAY_MODEL)

    run = await drive(entry, [reasoning_mandatory(), ok(entry)])

    assert run.error is None
    assert len(run.calls) == 2
    # Tool recovery raises budget while retaining the same reasoning request.
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


@pytest.mark.parametrize("mandatory_first", [False, True])
async def test_alternating_reasoning_failures_exhaust_the_tool_attempt_budget(
    drive: Driver, mandatory_first: bool
) -> None:
    entry = replace(TOOLS, model=GATEWAY_MODEL)
    mandatory = reasoning_mandatory()
    pair = (
        [mandatory, thinking_only()]
        if mandatory_first
        else [thinking_only(), mandatory]
    )
    # The old loop needed 21 attempts; the finite script detects an unbounded
    # recovery path.
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
    assert len(run.calls) == 3
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
    assert run.throttled == 0
    assert run.retries == 2
    assert run.retry_announcements == [("retry", "INFO")] * 2
    assert not any(kind == "park" for kind, _ in run.logged)
    assert run.logged[-1] == ("failed", "ERROR")


async def test_a_tool_turn_budget_stops_before_a_fourth_recovery_attempt(
    drive: Driver,
) -> None:
    entry = replace(TOOLS, model=GATEWAY_MODEL)
    refusal = reasoning_mandatory()
    run = await drive(entry, [exhausted(), exhausted(), refusal, ok(entry)])

    assert run.error is refusal
    assert run.result is None, (
        "a fourth-attempt success must remain unreachable"
    )
    assert len(run.calls) == 3
    assert run.max_tokens == [18000, 24000, 24000]
    assert run.reasoning == [
        {"enabled": True, "effort": "high"},
        {"enabled": True, "effort": "high"},
        {"enabled": False},
    ]
    assert run.slept == []
    assert run.throttled == 0
    assert run.retries == 2


async def test_each_tool_turn_receives_its_own_three_attempt_budget(
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
    recovery = [exhausted(), exhausted()]
    run = await drive(
        entry, [*recovery, asked_for_a_tool, *recovery, ok(entry)]
    )

    assert run.error is None
    assert run.result[0] == "fine"
    assert len(run.calls) == 6
    assert run.max_tokens == [18000, 24000, 24000] * 2
    assert run.reasoning[:3] == run.reasoning[3:]
    assert executed == ["c1"]
    for call in run.calls[3:]:
        assert [m["role"] for m in call["messages"]] == [
            "user",
            "assistant",
            "tool",
        ]
    assert run.slept == []
    assert run.throttled == 0
    assert run.retries == 4


@pytest.mark.parametrize("failure", [exhausted, rate_limited, overloaded])
async def test_a_tool_turn_retry_never_spans_tool_execution(
    drive: Driver,
    failure: Callable[[], Any],
) -> None:
    asked_for_a_tool = make_completion(
        make_message(None, tool_calls=[make_tool_call("c1", "search", "{}")])
    )
    executed: list[str] = []

    async def executor(tc: Any) -> dict[str, Any]:
        executed.append(tc.id)
        return await echo_executor(tc)

    entry = replace(TOOLS, executor=executor)

    run = await drive(entry, [asked_for_a_tool, failure(), ok(entry)])

    assert run.error is None
    assert len(run.calls) == 3
    assert executed == ["c1"], "the answerless turn must not rerun the tools"
    roles = [m["role"] for m in run.calls[2]["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert run.calls[1]["messages"] == run.calls[2]["messages"]
    assert run.max_tokens[1] == run.max_tokens[0]
    if failure is exhausted:
        assert run.max_tokens[2] > run.max_tokens[1]
    else:
        assert run.max_tokens[2] == run.max_tokens[1]


def _rejecting_judge() -> Judge[str, str]:

    def verdict(response: str, attempt: Attempt) -> Accepted[str] | Rejected:
        return Rejected(
            ValueError(f"bad {attempt.number}"),
            response_text=response,
            feedback=f"feedback {attempt.number}",
        )

    def exhausted(last: Rejected) -> str:
        return f"gave up: {last.error} / {last.response_text}"

    return Judge(verdict, exhausted)


async def test_each_attempt_is_told_its_number_rung_and_feedback() -> None:
    seen: list[Attempt] = []

    async def make_attempt(attempt: Attempt) -> str:
        seen.append(attempt)
        return f"response {attempt.number}"

    result = await run_attempts(
        make_attempt, AttemptPlan("m", max_attempts=3), _rejecting_judge()
    )

    assert result == "gave up: bad 3 / response 3"
    assert [a.number for a in seen] == [1, 2, 3]
    assert [a.is_final for a in seen] == [False, False, True]
    assert [a.feedback for a in seen] == [None, "feedback 1", "feedback 2"]
    assert {a.rung for a in seen} == {BudgetEscalation.NONE}


async def test_a_judge_that_accepts_ends_the_loop_with_its_value() -> None:
    calls = 0

    async def make_attempt(attempt: Attempt) -> str:
        nonlocal calls
        calls += 1
        return f"response {attempt.number}"

    def verdict(response: str, attempt: Attempt) -> Accepted[int] | Rejected:
        if attempt.number == 2:
            return Accepted(len(response))
        return Rejected(ValueError("no"))

    def exhausted(_last: Rejected) -> int:
        raise AssertionError("an accepted response must not exhaust")

    result = await run_attempts(
        make_attempt,
        AttemptPlan("m", max_attempts=5),
        Judge(verdict, exhausted),
    )

    assert (result, calls) == (len("response 2"), 2)


async def test_exhaustion_reports_the_last_response_text_any_attempt_gave() -> (
    None
):
    async def make_attempt(attempt: Attempt) -> str:
        return f"response {attempt.number}"

    def verdict(_response: str, attempt: Attempt) -> Accepted[str] | Rejected:
        text = "the only text" if attempt.number == 1 else None
        return Rejected(ValueError(f"bad {attempt.number}"), text)

    def exhausted(last: Rejected) -> str:
        return f"{last.error} / {last.response_text}"

    result = await run_attempts(
        make_attempt,
        AttemptPlan("m", max_attempts=2),
        Judge(verdict, exhausted),
    )

    assert result == "bad 2 / the only text"


async def test_a_final_attempt_failure_is_raised_not_handed_to_the_judge() -> (
    None
):
    async def make_attempt(attempt: Attempt) -> str:
        if attempt.is_final:
            raise RuntimeError("provider exploded")
        return "response"

    def exhausted(_last: Rejected) -> str:
        raise AssertionError("a failure is raised, never judged")

    with pytest.raises(RuntimeError, match="provider exploded"):
        await run_attempts(
            make_attempt,
            AttemptPlan("m", max_attempts=2),
            Judge(_rejecting_judge().verdict, exhausted),
        )


async def test_no_attempts_still_resolves_through_the_judge() -> None:
    async def make_attempt(_attempt: Attempt) -> str:
        raise AssertionError("no attempt may be made")

    result = await run_attempts(
        make_attempt, AttemptPlan("m", max_attempts=0), _rejecting_judge()
    )

    assert result == "gave up: no attempt was made / None"


async def test_an_escalation_only_plan_raises_a_failure_no_rung_answers() -> (
    None
):
    calls = 0

    async def make_attempt(_attempt: Attempt) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider exploded")

    with pytest.raises(RuntimeError, match="provider exploded"):
        await run_attempts(make_attempt, AttemptPlan.escalation_only("m"))

    assert calls == 1


async def test_an_escalation_only_plan_climbs_the_ladder_then_raises() -> None:
    rungs: list[BudgetEscalation] = []

    async def make_attempt(attempt: Attempt) -> str:
        rungs.append(attempt.rung)
        raise LLMBudgetExhaustedError("answerless")

    with pytest.raises(LLMBudgetExhaustedError):
        await run_attempts(make_attempt, AttemptPlan.escalation_only("m"))

    assert rungs == [
        BudgetEscalation.NONE,
        BudgetEscalation.RAISED_BUDGET,
        BudgetEscalation.NO_THINKING,
    ]


async def test_an_escalation_only_plan_never_marks_an_attempt_final() -> None:
    finals: list[bool] = []

    async def make_attempt(attempt: Attempt) -> str:
        finals.append(attempt.is_final)
        if attempt.number < 3:
            raise LLMBudgetExhaustedError("answerless")
        return "answered"

    result = await run_attempts(make_attempt, AttemptPlan.escalation_only("m"))

    assert result == "answered"
    assert finals == [False, False, False]


@pytest.mark.parametrize("failure", [rate_limited, overloaded])
async def test_tool_turn_recovers_a_transient_failure(
    drive: Driver, failure: Callable[[], Exception]
) -> None:
    run = await drive(TOOLS, [failure(), ok(TOOLS)])

    assert run.error is None
    assert len(run.calls) == 2
    assert len(run.slept) == 1 and run.slept[0] > 0
    assert run.retries == 1
    assert run.retry_announcements == [("retry", "INFO")]
    assert run.calls[0] == run.calls[1]


@pytest.mark.parametrize("failure", [rate_limited, overloaded])
async def test_tool_turn_stops_after_three_attempts(
    drive: Driver, failure: Callable[[], Exception]
) -> None:
    run = await drive(TOOLS, [failure()])

    assert isinstance(run.error, (RateLimitError, APIError))
    assert len(run.calls) == 3
    assert len(run.slept) == 2
    assert run.retries == 2


async def test_tool_turn_parks_a_platform_quota(drive: Driver) -> None:
    run = await drive(TOOLS, [rate_limited(reset_in=7200)])

    assert isinstance(run.error, LLMRateLimitParkError)
    assert len(run.calls) == 1
    assert run.slept == []
    assert run.retries == 0

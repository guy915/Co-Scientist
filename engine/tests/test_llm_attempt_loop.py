"""What ``call_llm`` and ``call_llm_json`` answer a failed attempt with.

Both entry points share one attempt loop: a failure no rung of the
escalation ladder answers is retried in place up to ``max_attempts``, a
throttle or an outage is waited out first (a platform-wide cap parks the
task instead), and a failure the same request cannot survive is never
retried. This file drives each through scripted failure sequences against
a fake provider and a fake sleep and pins attempt count, waits, the rung
each attempt was sent at, the final exception and the level of every retry
line -- see ``_llm_attempt_fakes`` for the harness. Tool turns' bounded
recovery and distinct request shaping are pinned in
``test_llm_attempt_loop_tools.py``.

``call_llm_json`` adds one thing the loop cannot decide alone: a response
that arrives but breaks the schema is retried at once, on the same rung,
with the validation error appended to the prompt.
"""

import time
from collections.abc import Callable
from dataclasses import replace

import pytest
from jsonschema.exceptions import ValidationError
from litellm.exceptions import APIError, BadRequestError, RateLimitError
from litellm.exceptions import ContextWindowExceededError as ContextWindow

from co_scientist.exceptions import (
    FreeModelEligibilityError,
    LLMBudgetExhaustedError,
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
    LLMTimeoutError,
)
from co_scientist.llm import LLMCallOptions
from tests._llm_attempt_fakes import (
    GATEWAY_MODEL,
    JSON,
    SCHEMA_FEEDBACK,
    STANDARD,
    WAITED_THEN_GAVE_UP,
    Driver,
    Entry,
    call_ceiling,
    exhausted,
    ok,
    overloaded,
    rate_limited,
    reasoning_mandatory,
    thinking_only,
    timed_out,
    too_big,
    wrong_type,
)
from tests._llm_attempt_fakes import drive as drive

# --- call_llm and call_llm_json: the standard policy ------------------------


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
    assert len(run.retry_debug) == 2
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


# --- call_llm_json: what only the judge can ask for -------------------------


async def test_a_schema_failure_retries_at_once_with_feedback_on_the_same_rung(
    drive: Driver,
) -> None:
    run = await drive(JSON, [wrong_type(), ok(JSON)])

    assert run.result == {"a": 1}
    assert len(run.calls) == 2
    assert run.slept == []
    assert run.retries == 1
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
    # What follows is the exhausted-retries diagnostics dump, all at ERROR.
    assert {level for _, level in run.logged[3:]} == {"ERROR"}
    # Feedback replaces itself rather than stacking.
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
    from typing import Any

    from co_scientist.exceptions import LLMThinkingOnlyError
    from co_scientist.llm import rate_limited_attempt_count, scoped_telemetry
    from co_scientist.llm.attempts.contract import Attempt, AttemptPlan
    from co_scientist.llm.attempts.escalation import BudgetEscalation
    from co_scientist.llm.attempts.retry import run_attempts

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
    from co_scientist.llm.attempts.contract import Attempt, AttemptPlan
    from co_scientist.llm.attempts.escalation import BudgetEscalation
    from co_scientist.llm.attempts.retry import run_attempts

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

"""The attempt loop's own interface: ``run_attempts`` with a scripted attempt.

``test_llm_attempt_loop.py`` pins what the three entry points do with a
failure through the real provider boundary. These tests drive the loop
directly, with no provider at all, to pin the contract a caller relies on:
what each attempt is told, what a judge's rejection carries forward, and
what a plan with no attempt budget does.
"""

import pytest

from co_scientist.exceptions import LLMBudgetExhaustedError
from co_scientist.llm.attempts.contract import (
    Accepted,
    Attempt,
    AttemptPlan,
    Judge,
    Rejected,
)
from co_scientist.llm.attempts.escalation import BudgetEscalation
from co_scientist.llm.attempts.retry import run_attempts


def _rejecting_judge() -> Judge[str, str]:
    """A judge that rejects every response with feedback, then gives up."""

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

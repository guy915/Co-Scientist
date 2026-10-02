"""The one attempt loop: run attempts at escalating rungs.

Every LLM call that can be answered by sending something different or
sending it again goes through ``run_attempts``: ``call_llm`` (no judge),
``call_llm_json`` (a judge that parses, repairs and validates the response)
and the tool turn of ``call_llm_with_tools``. A caller supplies two things,
in the vocabulary of
``llm.attempts.contract``:

* how to make one attempt at a given ``Attempt`` -- its rung of
  ``BudgetEscalation`` and any retry feedback -- and
* optionally a ``Judge`` of the response: ``Accepted``, or ``Rejected``
  with feedback for the next attempt.

This module owns everything else about what a failed attempt is answered
with, so there is one place to read it and one place to change it:

* the rung sequence (``llm.attempts.escalation`` defines the ladder; this
  module climbs it, and keeps the current rung across a rejected response
  because more tokens do not fix a wrong answer);
* the failures that are never retried, because the identical request
  cannot succeed (a timeout, an exceeded call ceiling, an oversized
  prompt), and the free-model eligibility refusal, which is re-raised as
  is;
* the platform rate-limit park, which hands the task back to the worker
  instead of spending attempts against a cap that has not reset;
* the wait before retrying a throttle or an outage, on separate schedules
  (``llm.attempts.backoff``), and the process-wide throttle counter;
* retry telemetry and log severity: a failure another attempt will answer
  is a warning, and only giving up is an error.

Nothing else writes a failed attempt down. ``llm.request.response`` and
the raw single-attempt call stay silent under this loop (see
``LLMCallOptions.log_failures``), so the one line per attempt written here
carries the call's own name and the budget it actually sent.
"""

import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Generic, cast, overload

from litellm.exceptions import ContextWindowExceededError

from co_scientist.exceptions import (
    FreeModelEligibilityError,
    LLMCallBudgetExceededError,
    LLMTimeoutError,
    short_error_text,
)
from co_scientist.llm.attempts.backoff import (
    _rate_limit_backoff_seconds,
    provider_outage_backoff_seconds,
)
from co_scientist.llm.attempts.contract import (
    Accepted,
    Attempt,
    AttemptPlan,
    Judge,
    R,
    Rejected,
    T,
)
from co_scientist.llm.attempts.escalation import (
    BudgetEscalation,
    escalation_for_error,
    is_transient_provider_error,
    log_escalation,
)
from co_scientist.llm.attempts.park import (
    is_rate_limited,
    platform_rate_limit_park,
)
from co_scientist.llm.request.thinking import failure_context_text
from co_scientist.llm.telemetry import record_retry

logger = logging.getLogger(__name__)

# Count of throttled attempts observed in this process. Read by callers
# that size their own fan-out (see agents/ranking/ranking_debate.py) so a
# provider that is pushing back can shrink the next wave instead of having
# every extra call spend its time asleep in backoff. A plain counter, not
# an asyncio primitive, so it is safe to share across the worker cohort's
# several event loops.
_rate_limited_attempts = 0


def rate_limited_attempt_count() -> int:
    """Return how many throttled attempts this process has backed off from."""
    return _rate_limited_attempts


# The failures that are never retried: the identical request cannot
# succeed, so a retry is one doomed call repeated by the attempt count.
# A timeout: a provider that accepted the request and then stopped
# answering will not answer it faster next time -- the unbounded stall the
# timeout ceiling exists to prevent. An exceeded call ceiling: the run is
# already over its ``max_llm_calls``, so another attempt only adds to the
# overrun. An oversized prompt: a live run rejected single simulation
# prompts of 1.18M to 1.65M tokens and re-sent them eleven times
# unchanged, and nothing in a retry can shorten the caller's transcript --
# raising hands it back to the one layer that can.
_NEVER_RETRIED: tuple[tuple[type[Exception], str], ...] = (
    (
        LLMCallBudgetExceededError,
        "LLM-call ceiling exceeded on attempt %s; not retrying",
    ),
    (LLMTimeoutError, "LLM call timed out on attempt %s; not retrying"),
    (
        ContextWindowExceededError,
        "Prompt exceeded the model's context window on attempt %s;"
        " not retrying, since the same prompt cannot fit on a retry",
    ),
)


def _raise_if_platform_cap(error: Exception, attempt: Attempt) -> None:
    """Raises ``LLMRateLimitParkError`` when this 429 is a platform cap.

    Checked ahead of the ordinary logging and backoff, and regardless of
    attempt number: a platform-wide cap will not have reset by the next
    attempt (or the final one), so there is nothing left in this call's own
    retry budget that answers it. Raising -- rather than waiting -- means a
    caller with somewhere to park a unit of work (the durable task worker)
    can do so without this call spending further attempts against a cap
    that has not reset.

    Args:
        error: The call failure raised by this attempt.
        attempt: Which attempt this is.
    """
    if not is_rate_limited(error):
        return
    park = platform_rate_limit_park(error)
    if park is None:
        return
    logger.warning(
        "Platform rate limit cap hit on attempt %s (%s); parking "
        "until %.0f (epoch seconds) instead of retrying",
        attempt.number,
        park.reason,
        park.resume_at,
    )
    raise park


def _raise_if_unretryable(error: Exception, attempt: Attempt) -> None:
    """Raises a failure that no further attempt can answer.

    Args:
        error: The call failure raised by this attempt.
        attempt: Which attempt this is.
    """
    for kind, line in _NEVER_RETRIED:
        if isinstance(error, kind):
            logger.error(line, attempt.number)
            raise error
    if isinstance(error, FreeModelEligibilityError):
        raise error
    _raise_if_platform_cap(error, attempt)


def _log_failure(error: Exception, attempt: Attempt) -> None:
    """Writes down one failed attempt, at the severity its remedy earns.

    This is the one layer that knows whether the failure is terminal, so it
    is the one that decides: an attempt another attempt will answer is a
    warning, and only giving up is an error. Logging every attempt at error
    made a run that recovered read as a broken one -- one recovered
    answerless completion produced four ERROR records.

    The line reads off the error, which was annotated with the call's own
    name and the budget it actually sent rather than recomputed here. The
    name is what makes a count of these attributable: this loop is shared by
    every node, and a production export of fifteen answerless completions
    could only be narrowed to a budget constant that ten call sites share.

    Args:
        error: The call failure raised by this attempt.
        attempt: Which attempt this is.
    """
    log = logger.error if attempt.is_final else logger.warning
    log(
        "LLM call failed on attempt %s%s: %s",
        attempt.number,
        failure_context_text(error),
        short_error_text(error),
    )


async def _wait_before_retry(error: Exception, attempt: Attempt) -> None:
    """Space the next attempt out from the condition that caused this one.

    Two kinds are answered by waiting rather than by re-asking: throttling,
    and a transient provider failure such as an upstream overload (see
    ``is_transient_provider_error`` for the incident that added the
    second). Retrying either at once feeds the condition that caused it,
    and an unjittered backoff would release every waiting caller together,
    reproducing it. Everything else returns immediately: a schema failure's
    next attempt carries corrective feedback, and an answerless completion
    is answered by the escalation ladder changing the request.

    The two waits are sized separately (``llm.attempts.backoff``), because a
    burst clears in seconds and an outage does not: waiting out an outage
    on the throttle's schedule spends the whole attempt budget before the
    provider is back, which is how run 49a509b0 lost its report. Only the
    throttled kind bumps ``_rate_limited_attempts``, which sizes callers'
    fan-out against a provider rationing them -- an overload is not that,
    and shrinking the next wave would not help if it were.

    Args:
        error: The call failure raised by this attempt.
        attempt: Which attempt this is.
    """
    global _rate_limited_attempts
    if is_rate_limited(error):
        _rate_limited_attempts += 1
        reason = "Rate limited"
        delay = _rate_limit_backoff_seconds(attempt.number)
    elif is_transient_provider_error(error):
        reason = "Transient provider failure"
        delay = provider_outage_backoff_seconds(attempt.number)
    else:
        return
    logger.warning(
        "%s on attempt %s; waiting %.1fs before retrying",
        reason,
        attempt.number,
        delay,
    )
    await asyncio.sleep(delay)


async def _answer_call_failure(error: Exception, attempt: Attempt) -> None:
    """Decides whether a failed call is retried, and spaces the retry out.

    Returns only when another attempt follows; raises ``error`` (or the
    park error that replaces it) otherwise.

    Args:
        error: The call failure raised by this attempt.
        attempt: Which attempt this is.
    """
    _raise_if_unretryable(error, attempt)
    _log_failure(error, attempt)
    if attempt.is_final:
        raise error
    await _wait_before_retry(error, attempt)


def _next_rung(
    error: Exception, current: BudgetEscalation, model_name: str
) -> BudgetEscalation | None:
    """The rung that answers this failure, logged, or None when none does.

    An answerless attempt escalates, and so does a provider's flat refusal
    to honour disabled reasoning (see ``escalation_for_error``). A schema
    failure, a parse failure or an ordinary provider error all say nothing
    about thinking, and changing the request would spend more tokens on a
    problem tokens do not solve.

    Args:
        error: Why the attempt failed or was rejected.
        current: The rung that attempt was made at.
        model_name: Model name in litellm format, needed to log what a
            ``NO_THINKING`` rung actually sends this model.

    Returns:
        The rung for the next attempt, or None.
    """
    escalated = escalation_for_error(error, current)
    if escalated is not None:
        log_escalation(error, escalated, model_name)
    return escalated


def _numbers(plan: AttemptPlan) -> Iterable[int]:
    """The attempt numbers a plan allows; unbounded for escalation-only."""
    if plan.max_attempts is None:
        return itertools.count(1)
    return range(1, plan.max_attempts + 1)


class _AttemptRun(Generic[R, T]):
    """The state of one ``run_attempts`` call, which no caller sees.

    Holds what carries from one attempt to the next: the current rung, the
    latest feedback, and the last response and rejection, for a judge
    whose attempts all fail.
    """

    def __init__(
        self,
        make_attempt: Callable[[Attempt], Awaitable[R]],
        plan: AttemptPlan,
        judge: Judge[R, T] | None,
    ) -> None:
        self._make_attempt = make_attempt
        self._plan = plan
        self._judge = judge
        self._rung = BudgetEscalation.NONE
        self._feedback: str | None = None
        self._response_text: str | None = None
        self._last: Rejected | None = None

    async def run(self) -> T:
        """Makes attempts until one is accepted or none is left."""
        for number in _numbers(self._plan):
            self._announce(number)
            attempt = Attempt(
                number,
                number == self._plan.max_attempts,
                self._rung,
                self._feedback,
            )
            verdict = await self._attempt_once(attempt)
            if isinstance(verdict, Accepted):
                return verdict.value
            self._absorb(verdict)
        return self._exhausted()

    def _announce(self, number: int) -> None:
        """Counts a retry; an escalation-only plan records none."""
        if number == 1 or self._plan.is_escalation_only:
            return
        logger.debug(
            "retrying llm call (attempt %s/%s)",
            number,
            self._plan.max_attempts,
        )
        record_retry(self._plan.model_name)

    async def _attempt_once(self, attempt: Attempt) -> Accepted[T] | Rejected:
        """Makes and judges one attempt, answering a call failure.

        A failure while making or judging the response is classified here;
        one that no further attempt can answer is raised.
        """
        try:
            response = await self._make_attempt(attempt)
            return self._judge_response(response, attempt)
        except Exception as error:
            if not self._plan.is_escalation_only:
                await _answer_call_failure(error, attempt)
            return Rejected(error)

    def _judge_response(
        self, response: R, attempt: Attempt
    ) -> Accepted[T] | Rejected:
        """Judges a response; with no judge, any response is the answer."""
        if self._judge is None:
            return Accepted(cast(T, response))
        return self._judge.verdict(response, attempt)

    def _absorb(self, rejected: Rejected) -> None:
        """Carries a rejected attempt's lessons into the next one."""
        self._climb(rejected.error)
        if rejected.response_text is not None:
            self._response_text = rejected.response_text
        if rejected.feedback is not None:
            self._feedback = rejected.feedback
            logger.debug("added validation feedback to retry prompt")
        self._last = rejected

    def _climb(self, error: Exception) -> None:
        """Moves to the rung that answers ``error``, if there is one.

        An escalation-only plan has nothing else to do with a failure no
        rung answers, so it raises it.
        """
        rung = _next_rung(error, self._rung, self._plan.model_name)
        if rung is not None:
            self._rung = rung
        elif self._plan.is_escalation_only:
            raise error

    def _exhausted(self) -> T:
        """Hands a judge the last rejection once every attempt is spent."""
        if self._judge is None:
            raise AssertionError(
                "unreachable: a final attempt's failure always re-raises"
            )
        # ``max_attempts < 1`` makes no attempt and so rejects nothing.
        last = self._last or Rejected(ValueError("no attempt was made"))
        return self._judge.exhausted(Rejected(last.error, self._response_text))


@overload
async def run_attempts(
    make_attempt: Callable[[Attempt], Awaitable[R]], plan: AttemptPlan
) -> R: ...


@overload
async def run_attempts(
    make_attempt: Callable[[Attempt], Awaitable[R]],
    plan: AttemptPlan,
    judge: Judge[R, T],
) -> T: ...


async def run_attempts(
    make_attempt: Callable[[Attempt], Awaitable[Any]],
    plan: AttemptPlan,
    judge: Judge[Any, Any] | None = None,
) -> Any:
    """Runs attempts at escalating rungs until one is accepted.

    Args:
        make_attempt: Makes one attempt for the ``Attempt`` it is given and
            returns its response. It must not retry or log a failure: a
            failure is raised, and this loop decides what follows.
        plan: How many attempts, and how a failure is answered.
        judge: How to judge a response, or None to accept the first one
            that arrives.

    Returns:
        The response of the first attempt that is accepted, or whatever
        ``judge.exhausted`` returns once every attempt was rejected.

    Raises:
        Exception: The failure of the final attempt, or at once the failure
            of an attempt that cannot be retried (see ``_NEVER_RETRIED``,
            ``LLMRateLimitParkError`` and ``FreeModelEligibilityError``).
    """
    return await _AttemptRun(make_attempt, plan, judge).run()

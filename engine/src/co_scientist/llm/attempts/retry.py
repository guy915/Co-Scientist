"""Bounded LLM attempts, accepted responses, retries and provider-cap parking.

One attempt loop serves text, JSON and tool requests. Budget escalation remains
a separate policy so retrying a parse error cannot change the token budget.
"""

import asyncio
import itertools
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Generic, TypeVar, cast, overload

from litellm.exceptions import ContextWindowExceededError

from co_scientist.backoff import jittered_backoff_seconds
from co_scientist.exceptions import (
    FreeModelEligibilityError,
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
    LLMTimeoutError,
    short_error_text,
)
from co_scientist.llm.attempts.escalation import (
    BudgetEscalation,
    escalation_for_error,
    is_transient_provider_error,
    log_escalation,
)
from co_scientist.llm.request.thinking import failure_context_text
from co_scientist.llm.telemetry import record_retry

logger = logging.getLogger(__name__)


# What one attempt returns, and what the loop returns once it is judged.
R = TypeVar("R")
T = TypeVar("T")


@dataclass(frozen=True)
class Attempt:
    """What a caller needs to know to make one attempt.

    Attributes:
        number: The 1-indexed attempt number.
        is_final: Whether this is the last attempt the plan allows. Always
            False for an escalation-only plan, which has no attempt budget.
        rung: The budget escalation this attempt is made at.
        feedback: The latest feedback a judge rejected a response with, or
            None. It outlives an attempt that failed before reaching the
            judge, so the next attempt still carries it.
    """

    number: int
    is_final: bool
    rung: BudgetEscalation = BudgetEscalation.NONE
    feedback: str | None = None


@dataclass(frozen=True)
class Accepted(Generic[T]):
    """A judge's verdict that a response is the answer.

    Attributes:
        value: What the loop returns.
    """

    value: T


@dataclass(frozen=True)
class Rejected:
    """A judge's verdict that a response must be asked for again.

    Attributes:
        error: Why it was rejected. It also decides the next rung, like any
            other failure.
        response_text: The raw response, kept so a loop that runs out of
            attempts can report the last one it saw.
        feedback: What to tell the next attempt about this one, or None to
            ask again unchanged.
    """

    error: Exception
    response_text: str | None = None
    feedback: str | None = None


@dataclass(frozen=True)
class Judge(Generic[R, T]):
    """How a caller judges a response, and what it does when nothing passes.

    Attributes:
        verdict: Accepts a response, or rejects it with feedback.
        exhausted: Called with the last rejection (and the last response
            text any attempt produced) when every attempt was rejected.
            Returns the result, or raises. Never reached when an attempt
            *failed* on its final try: that failure is raised as it is.
    """

    verdict: Callable[[R, Attempt], Accepted[T] | Rejected]
    exhausted: Callable[[Rejected], T]


@dataclass(frozen=True)
class AttemptPlan:
    """How many attempts a call gets, and what it does with a failure.

    Attributes:
        model_name: The model the call is made against, for retry
            telemetry and the escalation log.
        max_attempts: How many attempts before giving up. A failure no rung
            of the ladder answers is retried in place, a throttle or an
            outage is waited out first, and a platform cap parks the task.
            ``None`` is the *escalation-only* policy, below.
    """

    model_name: str
    max_attempts: int | None

    @classmethod
    def escalation_only(cls, model_name: str) -> "AttemptPlan":
        """Retry only failures the budget-escalation ladder answers.

        There is no numeric attempt budget, but each rung can be entered
        at most once per call, including the initial rung. This permits at
        most four physical attempts and raises the current failure before
        revisiting a rung, even when reasoning failures alternate.
        Failures no rung answers propagate without backoff, quota parking
        or retry telemetry. Production entry points, including tool turns,
        use bounded plans instead; tool turns have three attempts and share
        standard backoff, quota parking and retry telemetry.

        Args:
            model_name: The model the attempts are made against.

        Returns:
            A plan limited by distinct escalation rungs.

        """
        return cls(model_name, None)

    @property
    def is_escalation_only(self) -> bool:
        """Whether this plan retries only where a rung of the ladder answers."""
        return self.max_attempts is None


def is_rate_limited(error: Exception) -> bool:
    """Return whether a provider error is a throttling response.

    Matched structurally (litellm raises ``RateLimitError`` for every
    provider) with a message fallback, so a provider whose SDK surfaces the
    condition as a generic error still backs off rather than hammering.
    """
    if type(error).__name__ == "RateLimitError":
        return True
    text = str(error).lower()
    return "rate limit" in text or "ratelimit" in text


# How long a wait must be before it is worth parking the whole task rather
# than absorbing it inside this call with the ordinary backoff. A
# per-minute platform cap (60s) and a short Retry-After both stay under
# this and get an ordinary throttled retry, since the five-attempt budget
# already covers waits that size; a per-day cap (hours) does not.
_PLATFORM_PARK_THRESHOLD_SECONDS = 90.0

# Conservative default for a per-minute cap (or an unqualified mention of
# the free-model pool) named only in the message, with no header to size
# the wait from -- long enough to clear a burst, and deliberately kept
# under the park threshold above so it is absorbed by the ordinary backoff
# rather than parking a task for a wait this short.
_PER_MINUTE_DEFAULT_SECONDS = 60.0


def _next_utc_midnight_epoch(now: float) -> float:
    """Return the epoch-seconds instant of the next UTC midnight after now."""
    current = datetime.fromtimestamp(now, tz=timezone.utc)
    tomorrow = (current + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return tomorrow.timestamp()


def _parse_float(value: str | None) -> float | None:
    """Parse a header value as a float, or None if it is missing/unusable."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _platform_reset_from_headers(
    error: Exception, now: float
) -> tuple[float, str] | None:
    """Read a platform rate-limit reset instant off the error's response.

    litellm's ``RateLimitError`` carries the original httpx response (when
    the upstream call had one) as ``.response``, so headers are read from
    there -- litellm surfaces no ``.headers`` shortcut of its own.
    ``Retry-After`` is checked first (it names a wait relative to now),
    then OpenRouter's ``X-RateLimit-Reset`` (an absolute epoch-millisecond
    instant).
    """
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    retry_after = _parse_float(headers.get("retry-after"))
    if retry_after is not None:
        return now + retry_after, "retry_after_header"
    reset_ms = _parse_float(headers.get("x-ratelimit-reset"))
    if reset_ms is not None:
        return reset_ms / 1000.0, "x_ratelimit_reset_header"
    return None


def _platform_reset_from_message(
    error: Exception, now: float
) -> tuple[float, str] | None:
    """Fall back to matching OpenRouter's free-model cap wording.

    Reached only when the response carried no usable header, so the wait
    is a conservative default rather than an exact instant: a "per day"
    mention parks until the next UTC reset, and a "per minute" mention (or
    a bare mention of the free-models pool) waits long enough to clear a
    burst without exceeding the park threshold above -- so it is absorbed
    by the ordinary jittered backoff instead of parking the task. A
    message naming neither a provider-cap nor a free-models phrase (e.g.
    "rate-limited upstream") matches nothing here and keeps its ordinary
    backoff.
    """
    # OpenRouter's own free-model cap message hyphenates ("free-models-
    # per-day"); match both that and a plain-English "per day" so either
    # phrasing is caught.
    text = str(error).lower()
    if "per day" in text or "per-day" in text:
        return _next_utc_midnight_epoch(now), "message_per_day"
    if "per minute" in text or "per-minute" in text or "free-models" in text:
        return now + _PER_MINUTE_DEFAULT_SECONDS, "message_per_minute"
    return None


def platform_rate_limit_park(
    error: Exception,
) -> LLMRateLimitParkError | None:
    """Return a park error when this 429 is a platform cap worth parking for.

    Only meaningful for an error ``is_rate_limited`` already matched.
    Headers are trusted before the message, since they name an exact
    instant rather than a guess; whichever source resolves, a wait short
    enough for the ordinary backoff to absorb returns ``None`` so the
    caller retries as usual instead of parking a task over a few seconds.

    Args:
        error: The provider failure to classify.

    Returns:
        An ``LLMRateLimitParkError`` carrying the resume instant and why it
        was classified as a platform cap, or ``None`` when this is an
        ordinary throttle the in-call backoff should absorb.
    """
    now = time.time()
    resolved = _platform_reset_from_headers(
        error, now
    ) or _platform_reset_from_message(error, now)
    if resolved is None:
        return None
    resume_at, reason = resolved
    if resume_at - now <= _PLATFORM_PARK_THRESHOLD_SECONDS:
        return None
    return LLMRateLimitParkError(resume_at=resume_at, reason=reason)


# Base seconds for the throttled-retry wait; attempt N waits roughly
# BASE * 2^(N-1), jittered.
_RATE_LIMIT_BACKOFF_BASE_SECONDS: Final[float] = 2.0

# Base and ceiling for the outage wait. Sized against run 49a509b0 below,
# and against the two clocks a long wait has to stay clear of: the wait is
# an awaited sleep, so the durable task's lease heartbeat (a coroutine on
# the same loop, waking each second) keeps renewing through it, and
# COSCIENTIST_LLM_TIMEOUT_SECONDS bounds each litellm call rather than the
# gaps between them. The ceiling exists so that a caller with a larger
# attempt budget cannot double its way into an open-ended stall.
_PROVIDER_OUTAGE_BACKOFF_BASE_SECONDS: Final[float] = 30.0
_PROVIDER_OUTAGE_BACKOFF_MAX_SECONDS: Final[float] = 240.0


def _rate_limit_backoff_seconds(attempt: int) -> float:
    """Return the jittered wait before retrying a throttled attempt.

    Uncapped, unlike the search-tool retry: a provider still throttling on
    the last of a handful of attempts is asking for a longer pause, and the
    attempt budget already bounds the total. See
    ``backoff.jittered_backoff_seconds`` for why the wait is jittered.
    """
    return jittered_backoff_seconds(
        attempt, base_seconds=_RATE_LIMIT_BACKOFF_BASE_SECONDS
    )


def provider_outage_backoff_seconds(attempt: int) -> float:
    """Return the jittered wait before retrying an outage-failed attempt.

    Longer than the throttled schedule because it answers a different
    condition. A throttle clears as soon as the caller's own burst does; an
    upstream that is down stays down on its own timetable, so a schedule
    sized for a burst spends the whole attempt budget inside the outage.
    Standard run 49a509b0 (2026-09-08) is the measurement: its terminal
    ``research_overview`` call logged waits of 1.6s, 3.6s, 6.3s and 11.6s
    -- the four the 2.0s base allows -- so all five attempts were gone in
    roughly 25 seconds against an outage lasting minutes, and the task
    failed, discarding a run with 146 completed tasks.

    At the base and ceiling above, the four waits a five-attempt call takes
    are drawn from [15, 30], [30, 60], [60, 120] and [120, 240] seconds:
    between 3.75 and 7.5 minutes in total, rather than half a minute.

    Args:
        attempt: The 1-indexed attempt that just failed.

    Returns:
        Seconds to wait, jittered, never above
        ``_PROVIDER_OUTAGE_BACKOFF_MAX_SECONDS``.
    """
    return jittered_backoff_seconds(
        attempt,
        base_seconds=_PROVIDER_OUTAGE_BACKOFF_BASE_SECONDS,
        max_seconds=_PROVIDER_OUTAGE_BACKOFF_MAX_SECONDS,
    )


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

    The two waits are sized separately (``llm.attempts.retry``), because a
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
        self._visited_rungs = {self._rung}
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

        An escalation-only plan raises the current failure when no rung
        answers it or the target was already entered during this call.
        """
        rung = _next_rung(error, self._rung, self._plan.model_name)
        if rung is not None:
            if self._plan.is_escalation_only and rung in self._visited_rungs:
                raise error
            self._rung = rung
            self._visited_rungs.add(rung)
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

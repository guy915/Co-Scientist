"""What a caller supplies to the attempt loop, and what it gets back.

The vocabulary of ``llm.attempts.retry.run_attempts``, kept apart from the
loop so the judge (``llm.attempts.json_attempt``) and the attempt-makers
(``llm.call``, ``llm.tools.iteration``) depend on the contract and not on
how failures are answered:

* ``Attempt``: what one attempt is told -- its number, its rung of
  ``BudgetEscalation`` and the feedback of the last rejected response.
* ``AttemptPlan``: how many attempts, and how a failure is answered.
* ``Judge`` with ``Accepted`` and ``Rejected``: how a response is judged,
  and what happens when every attempt was rejected.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from co_scientist.llm.attempts.escalation import BudgetEscalation

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

        This policy has no physical-attempt budget. Failures no rung answers
        propagate without backoff or quota parking. Production entry points,
        including tool turns, use bounded plans instead.
        """
        return cls(model_name, None)

    @property
    def is_escalation_only(self) -> bool:
        """Whether this plan retries only where a rung of the ladder answers."""
        return self.max_attempts is None

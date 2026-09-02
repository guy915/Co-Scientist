"""Budget escalation for the ``call_llm_json`` retry loop.

What a retry *changes about the request* after an attempt came back with
no answer: the ladder of rungs, and the call spec each rung sends. Which
failures escalate, and how far, is the retry loop's own decision and stays
in ``llm_json_retry`` -- which re-exports every name here, so
``co_scientist.llm_json_retry`` remains one import path for the whole
retry surface.
"""

import dataclasses
import enum
import logging
from dataclasses import dataclass
from typing import Any

from co_scientist.constants import (
    BUDGET_ESCALATION_MAX_INCREMENT,
    BUDGET_ESCALATION_MAX_TOKENS,
)
from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMThinkingOnlyError,
)

logger = logging.getLogger(__name__)


class BudgetEscalation(enum.Enum):
    """How far a retry has escalated after a budget-exhausted attempt.

    A call that came back with no answer -- because it reasoned until it
    hit its ceiling, or because it stopped after reasoning and wrote
    nothing -- does the same thing again if the request does not change.
    Production saw both shapes burn every attempt they were given, each
    one paid for in full, so an answerless attempt moves up this ladder
    instead of being re-sent:

    * ``NONE``: the call as its node sized it.
    * ``RAISED_BUDGET``: resent at half again the call's own budget
      (floored at ``BUDGET_ESCALATION_MAX_TOKENS``, see
      ``escalated_max_tokens``), in case the chain of thought was close
      to finishing.
    * ``NO_THINKING``: resent with thinking off, which removes the
      unbounded side of the budget altogether.

    The last rung is what makes the ladder terminate: reasoning ends at
    the ceiling, so its natural length is unknown and no finite budget is
    provably enough. Escalation is one-way within a call and never leaves
    the retry loop -- the node's own budget is unchanged for the next
    call.
    """

    NONE = "none"
    RAISED_BUDGET = "raised_budget"
    NO_THINKING = "no_thinking"


_ESCALATION_LADDER: dict[BudgetEscalation, BudgetEscalation] = {
    BudgetEscalation.NONE: BudgetEscalation.RAISED_BUDGET,
    BudgetEscalation.RAISED_BUDGET: BudgetEscalation.NO_THINKING,
    BudgetEscalation.NO_THINKING: BudgetEscalation.NO_THINKING,
}


def escalation_for_error(
    error: BaseException | None, current: BudgetEscalation
) -> BudgetEscalation | None:
    """The rung answering this error, or None when no rung answers it.

    The two answerless shapes enter the ladder at different points.
    Budget exhaustion climbs one rung, because a chain of thought cut off
    at the ceiling may genuinely have been close to finishing. A
    thinking-only response skips to the top: the model *chose* to stop, so
    it did not want for room, and the intermediate rung would spend a
    whole attempt proving that.

    Everything else -- a schema failure, a parse failure, an ordinary
    provider error -- returns None. They say nothing about thinking, and
    changing the request would spend more tokens on a problem tokens do
    not solve. None also ends the ladder at its top rung, which is what
    stops a caller escalating forever.

    Args:
        error: The failure the attempt raised, if any.
        current: The rung that attempt was made at.

    Returns:
        The rung to send next, or None to stop escalating.
    """
    if isinstance(error, LLMThinkingOnlyError):
        if current is BudgetEscalation.NO_THINKING:
            return None
        return BudgetEscalation.NO_THINKING
    if not isinstance(error, LLMBudgetExhaustedError):
        return None
    escalated = _ESCALATION_LADDER[current]
    return None if escalated is current else escalated


def escalated_max_tokens(max_tokens: int, escalation: BudgetEscalation) -> int:
    """The budget to send at a rung.

    Scaled off the caller's own budget rather than replaced by a flat
    constant, so this rung actually changes the request for every caller
    -- including one already sized at or above
    ``BUDGET_ESCALATION_MAX_TOKENS``, for whom a flat floor would return
    the identical budget and silently resend the identical request. See
    ``BUDGET_ESCALATION_MAX_INCREMENT`` for why the extra room is bounded
    by an increment rather than by a cap on the result: that is what lets
    this always raise (never cut down a caller sized above the floor) and
    always bound (never let a caller sized far below it escalate
    unboundedly) at once.

    Args:
        max_tokens: The budget as its caller sized it.
        escalation: The rung this attempt is being made at.

    Returns:
        The unchanged budget at ``NONE``, otherwise ``max_tokens`` plus up
        to ``BUDGET_ESCALATION_MAX_INCREMENT`` more, floored at
        ``BUDGET_ESCALATION_MAX_TOKENS``.
    """
    if escalation is BudgetEscalation.NONE:
        return max_tokens
    increment = min(max_tokens // 2, BUDGET_ESCALATION_MAX_INCREMENT)
    return max(max_tokens + increment, BUDGET_ESCALATION_MAX_TOKENS)


def log_escalation(
    error: BaseException | None, escalated: BudgetEscalation
) -> None:
    """Says what the next attempt will do differently, and why.

    One sentence per escalating failure, written where the decision is
    made rather than where the call failed: the layer that knows a retry
    follows is the only one that can say so, and the error text itself is
    already printed by whoever ends up raising it.

    Args:
        error: The failure that triggered the escalation.
        escalated: The rung the next attempt will be made at.
    """
    if isinstance(error, LLMThinkingOnlyError):
        logger.warning(
            "LLM finished thinking without answering; retrying with "
            "thinking disabled"
        )
        return
    logger.warning(
        "LLM spent its whole token budget reasoning; retrying with %s",
        "thinking disabled"
        if escalated is BudgetEscalation.NO_THINKING
        else "a raised token budget",
    )


@dataclass(frozen=True)
class _JsonCallSpec:
    """Bundles the model/token/schema fields shared by json-attempt helpers.

    Deliberately credential-free: the effective bring-your-own-key is
    scoped into the task context by ``call_llm_json`` before the retry
    loop starts, so attempts resolve it without carrying it here.
    """

    model_name: str
    max_tokens: int
    temperature: float
    json_schema: dict[str, Any] | None


def escalated_spec(
    spec: _JsonCallSpec, escalation: BudgetEscalation
) -> _JsonCallSpec:
    """The call spec to send at a given escalation rung.

    Raises the budget off the node's own size (see
    ``escalated_max_tokens``) rather than replacing it with a flat
    constant, so a node that already sized itself at or above
    ``BUDGET_ESCALATION_MAX_TOKENS`` is not cut down by the very step
    meant to give it room -- and still gets more room, rather than the
    identical budget sent again.

    Args:
        spec: The call spec as the node sized it.
        escalation: The rung this attempt is being made at.

    Returns:
        ``spec`` unchanged at ``NONE``, otherwise a copy with the raised
        budget. Whether thinking is also disabled is the caller's to apply
        -- it is a completion option, not part of the spec.
    """
    if escalation is BudgetEscalation.NONE:
        return spec
    return dataclasses.replace(
        spec, max_tokens=escalated_max_tokens(spec.max_tokens, escalation)
    )

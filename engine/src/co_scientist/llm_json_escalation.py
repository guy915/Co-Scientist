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
    * ``MINIMAL_REASONING_REQUIRED``: the provider rejected the disabled-
      reasoning request outright ("reasoning is mandatory... cannot be
      disabled") rather than answering with an empty completion. Resent
      with reasoning enabled at the smallest tier the gateway exposes,
      not the rejected request repeated and not the full reasoning spend
      ``NO_THINKING`` was trying to avoid in the first place.

    The last rung is what makes the ladder terminate: reasoning ends at
    the ceiling, so its natural length is unknown and no finite budget is
    provably enough. Escalation is one-way within a call and never leaves
    the retry loop -- the node's own budget is unchanged for the next
    call.
    """

    NONE = "none"
    RAISED_BUDGET = "raised_budget"
    NO_THINKING = "no_thinking"
    MINIMAL_REASONING_REQUIRED = "minimal_reasoning_required"


_ESCALATION_LADDER: dict[BudgetEscalation, BudgetEscalation] = {
    BudgetEscalation.NONE: BudgetEscalation.RAISED_BUDGET,
    BudgetEscalation.RAISED_BUDGET: BudgetEscalation.NO_THINKING,
    BudgetEscalation.NO_THINKING: BudgetEscalation.NO_THINKING,
}


def _is_reasoning_mandatory_error(error: BaseException | None) -> bool:
    """Whether this failure is a provider's flat refusal to disable reasoning.

    Matched by substring, the same way ``llm_json_retry._is_rate_limited``
    matches a 429 -- litellm raises a generic ``BadRequestError`` for
    every provider's 400, so the message is the only structured signal
    this failure carries. Observed verbatim from OpenRouter for
    ``minimax/minimax-m3:free`` (production run b82f9162's recovered
    finalize, 2026-09-06 04:39:30 UTC): "Reasoning is mandatory for this
    endpoint and cannot be disabled." Every entailment call failed this
    way on both of its attempts, because the identical rejected request
    was simply resent -- exactly what escalating past it now prevents.

    Args:
        error: The failure to classify, if any.

    Returns:
        True if the message names both a mandatory reasoning requirement
        and a refusal to disable it.
    """
    if error is None:
        return False
    text = str(error).lower()
    return "reasoning is mandatory" in text and "cannot be disabled" in text


def _escalate_once(
    current: BudgetEscalation, target: BudgetEscalation
) -> BudgetEscalation | None:
    """Move to ``target`` once; stay terminal on a repeat from ``target``.

    Shared by both single-attempt escalations below (a thinking-only
    response, a mandatory-reasoning refusal): each answers with one fixed
    rung regardless of where the failure came from, and neither should
    ask again once already there.
    """
    return None if current is target else target


def escalation_for_error(
    error: BaseException | None, current: BudgetEscalation
) -> BudgetEscalation | None:
    """The rung answering this error, or None when no rung answers it.

    A provider's flat refusal to honour disabled reasoning is checked
    first and independently of the ladder above: it can be raised from
    any rung that sends ``enabled: False`` (the call's own first attempt,
    or the ladder's own ``NO_THINKING`` rung), and the answer is always
    the same escalation regardless of where it came from. Terminal after
    one attempt -- a provider that rejects minimal reasoning too is not
    answered by asking again.

    The two answerless shapes enter the ladder at different points.
    Budget exhaustion climbs one rung, because a chain of thought cut off
    at the ceiling may genuinely have been close to finishing. A
    thinking-only response skips to the top: the model *chose* to stop, so
    it did not want for room, and the intermediate rung would spend a
    whole attempt proving that. That premise holds only because
    ``LLMThinkingOnlyError`` is never raised for a completion the provider
    itself aborted (``finish_reason="error"``) -- see
    ``llm_response._empty_content_error`` -- so by the time an error
    reaches this function as ``LLMThinkingOnlyError``, the model did
    genuinely choose to stop rather than being cut off mid-stream.

    Everything else -- a schema failure, a parse failure, an ordinary
    provider error (including a mid-stream provider failure, which is
    exactly a plain retryable error rather than a thinking-only response)
    -- returns None. They say nothing about thinking, and changing the
    request would spend more tokens on a problem tokens do not solve.
    None also ends the ladder at its top rung, which is what stops a
    caller escalating forever.

    Args:
        error: The failure the attempt raised, if any.
        current: The rung that attempt was made at.

    Returns:
        The rung to send next, or None to stop escalating.
    """
    if _is_reasoning_mandatory_error(error):
        return _escalate_once(
            current, BudgetEscalation.MINIMAL_REASONING_REQUIRED
        )
    if isinstance(error, LLMThinkingOnlyError):
        return _escalate_once(current, BudgetEscalation.NO_THINKING)
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
    if escalated is BudgetEscalation.MINIMAL_REASONING_REQUIRED:
        logger.warning(
            "Provider rejected disabled reasoning as mandatory; retrying "
            "with reasoning enabled at minimal effort and a raised budget"
        )
        return
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

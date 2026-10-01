"""Budget escalation for the one LLM attempt loop.

What a retry *changes about the request* after an attempt came back with
no answer: the ladder of rungs, which failure enters it where
(``escalation_for_error``), and the call spec each rung sends. Climbing it
-- keeping the rung across a failure it does not answer, ending an
escalation-only plan when no rung does -- is the attempt loop's own and
lives in ``llm.attempts.retry``.
"""

import dataclasses
import enum
import logging
from dataclasses import dataclass
from typing import Any

from co_scientist.constants import (
    BUDGET_ESCALATION_MAX_INCREMENT,
    BUDGET_ESCALATION_MAX_TOKENS,
    MINIMAL_REASONING_MAX_TOKENS,
)
from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMThinkingOnlyError,
)
from co_scientist.llm.request.gateway_body import effective_thinking_enabled

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
    * ``MINIMAL_REASONING_REQUIRED``: the provider rejected the request's
      reasoning instruction outright -- a disable it mandates against
      ("reasoning is mandatory... cannot be disabled"), or the explicit
      bound sent in its place (``llm.request.gateway_body
      ._minimal_reasoning_knob``) -- rather than answering with an empty
      completion. Resent with reasoning enabled at the smallest tier the
      gateway exposes: not the rejected request repeated, and not the
      full reasoning spend ``NO_THINKING`` was trying to avoid in the
      first place.

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


# litellm exception classes that mean the provider hiccuped rather than
# refused. Matched by exact class name, never by ``isinstance``: openai's
# ``APIError`` is the base of ``APIStatusError`` and so of
# ``BadRequestError``, so an isinstance check would sweep the
# reasoning-mandatory 400 in here and hand it a wait instead of the
# escalation rung that actually answers it.
_TRANSIENT_ERROR_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "APIError",
        "APIConnectionError",
        "InternalServerError",
        "ServiceUnavailableError",
    }
)

# Classes that are a problem with the *request*, whatever their text
# says. OpenRouter wraps an upstream 4xx with that provider's own raw
# words, so a 400 can quote an overload verbatim; the class settles it,
# and the reasoning-mandatory 400 keeps the escalation rung that answers
# it instead of being slowed down by a wait that fixes nothing.
_NON_TRANSIENT_ERROR_TYPE_NAMES: frozenset[str] = frozenset({"BadRequestError"})

# Wording for a provider that surfaces an overload as some other class.
# ``mid-stream`` is the one that carries no type at all: an OpenRouter
# ``finish_reason="error"`` completion is raised as a plain ``ValueError``
# by ``llm.request.response._empty_content_error``, whose text this matches.
_TRANSIENT_MESSAGE_CUES: tuple[str, ...] = (
    "temporarily overloaded",
    "upstream error",
    "reported an error mid-stream",
)


def _is_transient_not_found(error: BaseException) -> bool:
    """Whether a 404 is OpenRouter's routes-exhausted shape, not a bad model.

    OpenRouter answers "every route I could try has failed" with a 404
    whose body carries a ``previous_errors`` list naming what each
    upstream did. A 404 without that list is a genuine model-not-found,
    which no amount of waiting fixes, so the list is the whole test.

    Args:
        error: The ``NotFoundError`` to classify.

    Returns:
        True when the error body names the routes that were already tried.
    """
    return "previous_errors" in str(error)


def is_transient_provider_error(error: BaseException | None) -> bool:
    """Whether waiting -- rather than re-asking at once -- answers this failure.

    Recorded because the difference is not obvious from the exception
    type alone. Production extended run bc77950f (2026-09-08
    02:27:12-02:27:16 UTC) failed a ``research_overview`` call with
    ``litellm.APIError: OpenrouterException - Upstream error from Nvidia:
    Service temporarily overloaded`` on attempts 2, 3, 4 and 5 at
    one-second intervals -- the whole five-attempt budget spent in four
    seconds against an overload that needs seconds to minutes to clear --
    and ``knowledge_base_synthesis`` then did the same. Earlier in that
    run the provider returned ``litellm.NotFoundError`` carrying
    ``previous_errors``, OpenRouter's way of saying every route it could
    reach had already failed, and many calls came back as the mid-stream
    ``finish_reason="error"`` shape. All three are the remote side asking
    for time.

    The failures deliberately excluded are the ones a *different request*
    answers, where a wait only delays the fix: a 400 (the
    reasoning-mandatory refusal has its own rung in
    ``escalation_for_error``), a schema or
    parse failure (the next attempt carries corrective feedback and
    should go out at once), and this engine's own answerless-completion
    errors, which are ``ValueError`` subclasses from the same factory as
    the mid-stream one and would otherwise match its text.

    A rate-limited failure is not classified here at all -- it is claimed
    by ``llm.attempts.park.is_rate_limited`` first, which already backs off
    (and may park the task). That also covers a routes-exhausted body
    whose ``previous_errors`` name a 429.

    Args:
        error: The failure to classify, if any.

    Returns:
        True when the next attempt should be spaced out from this one.
    """
    if error is None or isinstance(
        error, LLMBudgetExhaustedError | LLMThinkingOnlyError
    ):
        return False
    name = type(error).__name__
    if name == "NotFoundError":
        return _is_transient_not_found(error)
    if name in _TRANSIENT_ERROR_TYPE_NAMES:
        return True
    return _has_transient_message(error)


def _has_transient_message(error: BaseException) -> bool:
    """Whether the failure's own text names a transient provider condition.

    The fallback for a provider whose SDK surfaces an overload as some
    other class, and the only signal the mid-stream shape carries. A
    class that is definitionally a request problem is excluded first,
    since its text is free to quote the upstream it wrapped.
    """
    if type(error).__name__ in _NON_TRANSIENT_ERROR_TYPE_NAMES:
        return False
    text = str(error).lower()
    return any(cue in text for cue in _TRANSIENT_MESSAGE_CUES)


def _is_reasoning_mandatory_error(error: BaseException | None) -> bool:
    """Whether this failure is a provider's flat refusal to disable reasoning.

    Matched by substring, the same way ``llm.attempts.park.is_rate_limited``
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


# What a provider says when it will not take an instruction about
# reasoning it does understand. Both lists must hit, alongside the word
# "reasoning" itself, before a failure counts: an unbounded-chain-of-
# thought budget failure names ``reasoning_tokens`` and ``max_tokens`` in
# its own message, and reading that as a rejected instruction would
# divert every budget failure to the terminal recovery rung and retire
# the escalation ladder above.
_REASONING_FIELD_CUES: tuple[str, ...] = ("max_tokens", "max tokens")
_REJECTION_CUES: tuple[str, ...] = (
    "not supported",
    "unsupported",
    "invalid",
    "not allowed",
)


def _is_reasoning_cap_rejected(error: BaseException | None) -> bool:
    """Whether a provider refused the explicit bound on its reasoning.

    The bound (``MINIMAL_REASONING_MAX_TOKENS``, sent as the gateway's
    ``reasoning.max_tokens``) is what stops a classification call funding
    an unbounded chain of thought, but it is unprobed against every host
    the free chain's ``models`` array can reach. A host that rejects it
    must therefore degrade to the tier name -- the request shape
    production has actually been served -- not fail the call, which is
    the same requirement ``_is_reasoning_mandatory_error`` established
    for the disable it replaced.

    Args:
        error: The failure to classify, if any.

    Returns:
        True for a provider error naming reasoning, a token-bound field
        and a refusal. Never for this engine's own budget failures,
        whose messages name the first two.
    """
    if error is None or isinstance(
        error, LLMBudgetExhaustedError | LLMThinkingOnlyError
    ):
        return False
    text = str(error).lower()
    return (
        "reasoning" in text
        and any(cue in text for cue in _REASONING_FIELD_CUES)
        and any(cue in text for cue in _REJECTION_CUES)
    )


def _is_reasoning_instruction_refused(error: BaseException | None) -> bool:
    """Whether the provider refused what the request said about reasoning.

    One question with two observed shapes -- a mandated reasoning mode
    and a rejected bound on it -- because one answer serves both: resend
    at the gateway's smallest tier, once.

    Args:
        error: The failure to classify, if any.

    Returns:
        True if either shape matches.
    """
    return _is_reasoning_mandatory_error(error) or _is_reasoning_cap_rejected(
        error
    )


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

    A provider's refusal of the request's reasoning instruction -- the
    disable it mandates against, or the bound sent in its place -- is
    checked first and independently of the ladder above: it can be raised
    from any rung that asks a model not to reason (the call's own first
    attempt, or the ladder's own ``NO_THINKING`` rung), and the answer is
    always the same escalation regardless of where it came from. Terminal
    after one attempt -- a provider that rejects minimal reasoning too is
    not answered by asking again.

    The two answerless shapes enter the ladder at different points.
    Budget exhaustion climbs one rung, because a chain of thought cut off
    at the ceiling may genuinely have been close to finishing. A
    thinking-only response skips to the top: the model *chose* to stop, so
    it did not want for room, and the intermediate rung would spend a
    whole attempt proving that. That premise holds only because
    ``LLMThinkingOnlyError`` is never raised for a completion the provider
    itself aborted (``finish_reason="error"``) -- see
    ``llm.request.response._empty_content_error`` -- so by the time an error
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
    if _is_reasoning_instruction_refused(error):
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


def _no_thinking_detail_text(model_name: str) -> str:
    """What the ``NO_THINKING`` rung actually sends this model.

    The rung always requests ``enable_thinking=False``, but a model that
    cannot honour a disable (``GatewayModel.reasoning_can_disable`` is
    False) is redirected to reasoning bounded at
    ``MINIMAL_REASONING_MAX_TOKENS`` instead -- never the literal disable
    already known to 400 -- see
    ``llm.request.gateway_body._declared_gateway_body``. That redirect happens
    on every model in the deployed free chain, so the log has to name what
    reaches the wire, not what the rung is named for.

    Args:
        model_name: Model name in litellm format.

    Returns:
        A phrase describing the actual request: capped reasoning for a
        model that redirects, a plain disable otherwise.
    """
    return (
        f"reasoning capped at {MINIMAL_REASONING_MAX_TOKENS} tokens"
        if effective_thinking_enabled(model_name, False)
        else "thinking disabled"
    )


def log_escalation(
    error: BaseException | None,
    escalated: BudgetEscalation,
    model_name: str,
) -> None:
    """Says what the next attempt will do differently, and why.

    One sentence per escalating failure, written where the decision is
    made rather than where the call failed: the layer that knows a retry
    follows is the only one that can say so, and the error text itself is
    already printed by whoever ends up raising it.

    Args:
        error: The failure that triggered the escalation.
        escalated: The rung the next attempt will be made at.
        model_name: Model name in litellm format, needed to say what a
            ``NO_THINKING`` rung actually sends this model (see
            ``_no_thinking_detail_text``).
    """
    if escalated is BudgetEscalation.MINIMAL_REASONING_REQUIRED:
        logger.warning(
            "Provider rejected disabled reasoning as mandatory; retrying "
            "with reasoning enabled at minimal effort and a raised budget"
        )
        return
    detail = (
        _no_thinking_detail_text(model_name)
        if escalated is BudgetEscalation.NO_THINKING
        else "a raised token budget"
    )
    if isinstance(error, LLMThinkingOnlyError):
        logger.warning(
            "LLM finished thinking without answering; retrying with %s",
            detail,
        )
        return
    logger.warning(
        "LLM spent its whole token budget reasoning; retrying with %s",
        detail,
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

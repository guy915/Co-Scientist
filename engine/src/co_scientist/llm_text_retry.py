"""Budget-escalation retry loop for plain-text ``call_llm``.

The JSON retry loop (``llm_json_retry``/``llm_json_attempt``) answers an
answerless completion by escalating a budget rung instead of re-sending the
identical request; a plain-text caller such as the literature-review
synthesis step used ``call_llm`` directly and got none of that -- one
answerless attempt and the whole call failed. This module is the plain-text
counterpart: same rungs, same failure classification, same rate-limit
backoff, with no JSON parsing, schema validation, or retry-prompt-feedback
step, since a plain-text call either returns content or the attempt failed
outright.

Built on top of the JSON loop's own pieces (``_handle_json_call_failure``,
``_JsonAttempt``, and the escalation primitives in ``llm_json_escalation``)
rather than a second implementation, so the two ladders cannot drift apart.
``co_scientist.llm.call_llm`` injects the raw per-attempt call as
``call_for_attempt``, exactly like ``call_llm_json``'s own ``call_for_json``
seam.
"""

import logging
from collections.abc import Awaitable, Callable

from litellm.exceptions import ContextWindowExceededError

from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMTimeoutError,
)
from co_scientist.llm_json_attempt import _JsonAttempt
from co_scientist.llm_json_escalation import (
    BudgetEscalation,
    escalation_for_error,
    log_escalation,
)
from co_scientist.llm_json_retry import _handle_json_call_failure
from co_scientist.llm_telemetry import record_retry as _record_retry

logger = logging.getLogger(__name__)


async def _run_text_attempt(
    call_for_attempt: Callable[[BudgetEscalation], Awaitable[str]],
    attempt: _JsonAttempt,
) -> tuple[str | None, Exception | None]:
    """Runs one plain-text attempt, converting a call failure to an outcome.

    Mirrors ``llm_json_retry._run_json_attempt`` with no parse/validate step:
    a plain-text call either returns its content (the success case) or the
    raw call raised, and there is nothing further to check. The same three
    failures stay unretried for the same reason they do under the JSON
    loop -- see ``_run_json_attempt`` for why a timeout, an exceeded
    LLM-call ceiling, or an oversized prompt cannot be answered by trying
    again.

    Args:
        call_for_attempt: Makes one attempt's raw call at a given escalation
            rung; raises on failure.
        attempt: Which attempt of the retry loop this is.

    Returns:
        ``(text, None)`` on success, or ``(None, error)`` when this attempt
        failed and another may follow (the final attempt's failure instead
        propagates, via ``_handle_json_call_failure``'s bare ``raise``).
    """
    try:
        return await call_for_attempt(attempt.escalation), None
    except LLMCallBudgetExceededError:
        logger.error(
            "LLM-call ceiling exceeded on attempt %s; not retrying",
            attempt.number,
        )
        raise
    except LLMTimeoutError:
        logger.error(
            "LLM call timed out on attempt %s; not retrying", attempt.number
        )
        raise
    except ContextWindowExceededError:
        logger.error(
            "Prompt exceeded the model's context window on attempt %s;"
            " not retrying, since the same prompt cannot fit on a retry",
            attempt.number,
        )
        raise
    except Exception as e:
        outcome = await _handle_json_call_failure(e, attempt)
        return None, outcome.error


def _escalation_after_text_failure(
    error: Exception | None, current: BudgetEscalation
) -> BudgetEscalation:
    """The escalation rung for the next plain-text attempt.

    The same classification ``call_llm_json`` uses
    (``llm_json_escalation.escalation_for_error``), called directly rather
    than through ``llm_json_retry.escalation_after``: that wrapper reads its
    error off a ``_JsonAttemptOutcome``, and a plain-text attempt has
    nothing else to build one from.

    Args:
        error: The failure the attempt just raised, if any.
        current: The rung that attempt was made at.

    Returns:
        The rung for the next attempt, or ``current`` unchanged.
    """
    escalated = escalation_for_error(error, current)
    if escalated is None:
        return current
    log_escalation(error, escalated)
    return escalated


async def run_with_budget_escalation(
    call_for_attempt: Callable[[BudgetEscalation], Awaitable[str]],
    max_attempts: int,
    model_name: str,
) -> str:
    """Runs ``call_for_attempt`` through the budget-escalation retry ladder.

    The plain-text counterpart of ``llm._run_call_llm_json_loop``: same
    rungs, same failure handling, minus the JSON-specific parse/validate
    step and the retry-prompt-feedback it can produce.

    Args:
        call_for_attempt: Makes one attempt's raw call at a given escalation
            rung; raises on failure.
        max_attempts: How many attempts to make before giving up.
        model_name: The model this call is made against, for retry
            telemetry (see ``llm_telemetry.record_retry``).

    Returns:
        The first attempt's content that returns successfully.

    Raises:
        Exception: Whatever the final attempt's call failure was.
    """
    escalation = BudgetEscalation.NONE
    for number in range(1, max_attempts + 1):
        if number > 1:
            logger.debug(
                "retrying llm call (attempt %s/%s)", number, max_attempts
            )
            _record_retry(model_name)
        attempt = _JsonAttempt(number, number == max_attempts, escalation)
        text, error = await _run_text_attempt(call_for_attempt, attempt)
        if error is None:
            assert text is not None  # success carries no error
            return text
        escalation = _escalation_after_text_failure(error, escalation)
    raise AssertionError(
        "unreachable: the final attempt's failure always re-raises"
    )

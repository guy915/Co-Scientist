"""Content extraction from LiteLLM completion responses.

Split from ``co_scientist.llm.request.completion``: pulls the text content out
of a completion response and, when there is none, summarizes why in one short
line.
"""

import contextlib
import logging
from dataclasses import dataclass
from typing import Any, cast

from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMThinkingOnlyError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenUsage:
    """Token counts read off one completion response's ``usage`` field.

    Every field defaults to zero, which is also what a response carrying
    no ``usage`` at all naturally produces (the offline backend never
    populates one -- see ``offline_llm``) -- there is no separate
    "unknown" state a caller needs to check for.

    Attributes:
        prompt_tokens: Prompt (input) tokens the provider billed.
        completion_tokens: Completion (output) tokens the provider billed.
        reasoning_tokens: Reasoning tokens billed separately from
            ``completion_tokens``, when the provider reports them.
        cached_prompt_tokens: The share of ``prompt_tokens`` the provider
            served from a prompt cache and bills at its cache-read rate --
            roughly a fifth of the input rate across DeepSeek's hosts. Not
            a separate charge on top of ``prompt_tokens``: it is a cheaper
            slice of the same number, so a cost estimate must subtract it
            before applying the full input rate. Zero from any provider
            that does not report the field, which prices the call exactly
            as it did before this existed.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_prompt_tokens: int = 0


def extract_token_usage(response: Any) -> TokenUsage:
    """Reads prompt/completion/reasoning token counts off a response.

    Every field is read defensively, the same way
    ``_empty_content_diagnosis`` reads them: this runs on both a healthy
    and an already-failing response, and a reader that raises would turn
    a telemetry gap into a request failure.

    Args:
        response: The raw response returned by ``litellm.acompletion``.

    Returns:
        The token counts reported, defaulting to zero for anything absent.
    """
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None) or 0
    completion_tokens = getattr(usage, "completion_tokens", None) or 0
    details = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = getattr(details, "reasoning_tokens", None) or 0
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(prompt_details, "cached_tokens", None) or 0
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_prompt_tokens=min(cached, prompt_tokens),
    )


def _empty_content_diagnosis(response: Any) -> str:
    """Summarizes, in one short line, why a completion carried no content.

    The response object itself is deliberately never logged. On a reasoning
    model it embeds the entire chain of thought twice -- once as
    ``message.reasoning_content`` and again under
    ``provider_specific_fields`` -- so a single record runs to tens of
    kilobytes, floods the persisted log, and pushes the run's own narrative
    out of the fixed newest-N window the Logs panel shows. None of that text
    diagnoses anything the fields below do not: ``finish_reason="length"``
    with ``reasoning_tokens`` sitting at the call's ``max_tokens`` says the
    chain of thought spent the whole budget and left nothing for the answer.

    Every field is read defensively -- this runs on an already-failing
    response, and a diagnostic that raises would replace a useful error with
    an ``AttributeError`` from the logging path.

    Args:
        response: The raw response returned by ``litellm.acompletion``.

    Returns:
        A compact ``key=value`` summary of the finish reason and token spend.
    """
    parts: list[str] = []

    with contextlib.suppress(Exception):
        parts.append(f"finish_reason={response.choices[0].finish_reason}")

    usage = getattr(response, "usage", None)
    for field in ("prompt_tokens", "completion_tokens"):
        value = getattr(usage, field, None)
        if value is not None:
            parts.append(f"{field}={value}")

    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None)
    if reasoning is not None:
        parts.append(f"reasoning_tokens={reasoning}")

    return ", ".join(parts) if parts else "no usage reported"


def _finish_reason(response: Any) -> str | None:
    """The provider's finish reason for a response, or None if unreadable.

    Read defensively for the same reason ``_empty_content_diagnosis`` is:
    this runs on an already-failing response, and a reader that raises
    would replace a diagnosable failure with an ``AttributeError``.

    Args:
        response: The raw response returned by ``litellm.acompletion``.

    Returns:
        The first choice's ``finish_reason``, or None when absent.
    """
    with contextlib.suppress(Exception):
        return cast("str | None", response.choices[0].finish_reason)
    return None


def _extract_completion_content(response: Any, model_name: str) -> str:
    """Extracts and validates the text content of a completion response.

    Args:
        response: The raw response returned by ``litellm.acompletion``.
        model_name: Model name in litellm format, included in the error
            message when the response has no content.

    Returns:
        The non-empty response content.

    Raises:
        LLMBudgetExhaustedError: If the response is empty because the whole
            token budget went on the chain of thought
            (``finish_reason="length"``). A subclass of ``ValueError``, so
            callers written against the general case still catch it.
        LLMThinkingOnlyError: If the response ended normally having spent
            reasoning tokens and written no answer. Also a ``ValueError``.
        ValueError: If the response has no non-whitespace content for any
            other reason.
    """
    content = response.choices[0].message.content

    if content is None or not content.strip():
        # Deliberately silent: the exception raised here carries the model
        # and the same diagnosis, and every layer above prints that text.
        # Logging it as well made one answerless completion write three
        # records saying the same sentence -- an export of a run that
        # recovered fine read as 27 errors and 29 warnings. The layer that
        # knows whether a retry follows does the logging: llm.attempts.retry's
        # retry loop, shared by call_llm_json and call_llm's own escalation
        # loop alike (see llm.attempts.text_retry).
        raise _empty_content_error(
            response, model_name, _empty_content_diagnosis(response)
        )

    return cast(str, content)


def _empty_content_error(
    response: Any, model_name: str, diagnosis: str
) -> ValueError:
    """Classify an empty completion by what would answer it.

    Four outcomes, and the split is by remedy rather than by severity:

    * ``finish_reason="length"`` -- the provider stopped at the ceiling, so
      the request needs a different budget.
    * ``finish_reason="error"`` -- OpenRouter's way of reporting an upstream
      provider failure mid-stream, not a completion that ran to term. The
      model did not choose to stop here, so neither of the thinking-related
      remedies below applies; it is an ordinary provider hiccup like any
      other, answered by a plain retry. Checked before the reasoning-spent
      case so a mid-stream failure that happened to spend reasoning tokens
      first is never mistaken for one.
    * Reasoning spent, no answer, stopped normally -- the model finished
      thinking and wrote nothing, so the request needs thinking off. More
      budget is beside the point (production spent 1149 of 18000), and so
      is a plain retry (attempts 2 and 3 did exactly the same). This
      premise -- the model chose to stop -- only holds because the
      provider-error case above is filtered out first: a completion that
      stopped for a reason other than its own choice is never charged to
      "the model didn't want more room".
    * Anything else, including an empty response with no reasoning at all --
      an ordinary provider hiccup, which a plain retry does recover.

    Args:
        response: The raw response returned by ``litellm.acompletion``.
        model_name: Model name in litellm format, named in the message.
        diagnosis: The already-computed ``key=value`` usage summary.

    Returns:
        The error to raise; every kind is a ``ValueError`` subclass.
    """
    finish_reason = _finish_reason(response)
    if finish_reason == "length":
        return LLMBudgetExhaustedError(
            "LLM spent its entire token budget without answering. "
            f"Model: {model_name} ({diagnosis})"
        )
    if finish_reason == "error":
        return ValueError(
            "LLM provider reported an error mid-stream and wrote no "
            f"answer. Model: {model_name} ({diagnosis})"
        )
    if extract_token_usage(response).reasoning_tokens > 0:
        return LLMThinkingOnlyError(
            "LLM finished its chain of thought and wrote no answer. "
            f"Model: {model_name} ({diagnosis})"
        )
    return ValueError(
        f"LLM returned None or empty content. Model: {model_name}"
    )

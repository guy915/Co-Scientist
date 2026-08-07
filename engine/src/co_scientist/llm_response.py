"""Content extraction from LiteLLM completion responses.

Split from ``co_scientist.llm_request``: pulls the text content out of a
completion response and, when there is none, summarizes why in one short
line. Every name here is re-exported from ``co_scientist.llm_request`` so
that module's namespace is unchanged.
"""

import contextlib
import logging
from dataclasses import dataclass
from typing import Any, cast

from co_scientist.exceptions import LLMBudgetExhaustedError

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
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0


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
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
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
        ValueError: If the response has no non-whitespace content for any
            other reason.
    """
    content = response.choices[0].message.content

    if content is None or not content.strip():
        diagnosis = _empty_content_diagnosis(response)
        logger.error(
            "LLM returned None or empty content. Model: %s (%s)",
            model_name,
            diagnosis,
        )
        # Split by finish reason, not by token counts: "length" is the
        # provider stating it stopped at the ceiling, which is the one
        # empty response a different budget can fix. Everything else --
        # a filtered response, a provider hiccup, an empty answer the
        # model chose -- is answered by a plain retry.
        if _finish_reason(response) == "length":
            raise LLMBudgetExhaustedError(
                "LLM spent its entire token budget without answering. "
                f"Model: {model_name} ({diagnosis})"
            )
        raise ValueError(
            f"LLM returned None or empty content. Model: {model_name}"
        )

    return cast(str, content)

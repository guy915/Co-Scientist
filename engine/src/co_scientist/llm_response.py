"""Content extraction from LiteLLM completion responses.

Split from ``co_scientist.llm_request``: pulls the text content out of a
completion response and, when there is none, summarizes why in one short
line. Every name here is re-exported from ``co_scientist.llm_request`` so
that module's namespace is unchanged.
"""

import contextlib
import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


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


def _extract_completion_content(response: Any, model_name: str) -> str:
    """Extracts and validates the text content of a completion response.

    Args:
        response: The raw response returned by ``litellm.acompletion``.
        model_name: Model name in litellm format, included in the error
            message when the response has no content.

    Returns:
        The non-empty response content.

    Raises:
        ValueError: If the response has no non-whitespace content.
    """
    content = response.choices[0].message.content

    if content is None or not content.strip():
        logger.error(
            "LLM returned None or empty content. Model: %s (%s)",
            model_name,
            _empty_content_diagnosis(response),
        )
        raise ValueError(
            f"LLM returned None or empty content. Model: {model_name}"
        )

    return cast(str, content)

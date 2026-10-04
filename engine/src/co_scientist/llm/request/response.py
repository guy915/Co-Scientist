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
    """Cache reads are a discounted slice of prompt tokens, not an additional
    charge.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_prompt_tokens: int = 0


def extract_token_usage(response: Any) -> TokenUsage:
    """Missing telemetry must not turn a healthy response into a request
    failure.
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
    """Raw responses duplicate reasoning and flood the bounded Logs feed.
    Diagnostics must not mask the original failure.
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
    """Unreadable diagnostic fields must not replace the original response
    failure.
    """
    with contextlib.suppress(Exception):
        return cast("str | None", response.choices[0].finish_reason)
    return None


def _extract_completion_content(response: Any, model_name: str) -> str:
    content = response.choices[0].message.content

    if content is None or not content.strip():
        # The attempt boundary logs once with retry context; logging extraction
        # failures here duplicates it.
        raise _empty_content_error(
            response, model_name, _empty_content_diagnosis(response)
        )

    return cast(str, content)


def _empty_content_error(
    response: Any, model_name: str, diagnosis: str
) -> ValueError:
    """
    Provider aborts precede reasoning spend: the model did not choose to stop.
    Only normal thinking-only stops skip the larger-budget rung.
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

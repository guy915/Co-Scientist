"""Tests for ``co_scientist.llm.request.response``."""

from types import SimpleNamespace

import pytest

from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMThinkingOnlyError,
)
from co_scientist.llm.request.response import (
    TokenUsage,
    _extract_completion_content,
    extract_token_usage,
)


def test_extract_token_usage_reads_all_fields() -> None:
    """Reads prompt, completion, and reasoning tokens off a full response."""
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=45,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=30),
        )
    )
    assert extract_token_usage(response) == TokenUsage(120, 45, 30)


def test_extract_token_usage_defaults_missing_usage_to_zero() -> None:
    """A response with no ``usage`` attribute at all reads as all-zero.

    This is exactly the offline backend's response shape (see
    ``offline_llm._build_response``), so telemetry never raises on it.
    """
    response = SimpleNamespace(choices=[])
    assert extract_token_usage(response) == TokenUsage(0, 0, 0)


def test_extract_token_usage_defaults_missing_reasoning_to_zero() -> None:
    """A provider that omits reasoning tokens reads as zero, not None."""
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    )
    assert extract_token_usage(response) == TokenUsage(10, 5, 0)


# --- classifying an empty completion (_extract_completion_content) ---------


def _empty_response(
    finish_reason: str | None, reasoning_tokens: int
) -> SimpleNamespace:
    """A response with no content, at a given finish reason/reasoning spend."""
    message = SimpleNamespace(content=None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=reasoning_tokens,
        completion_tokens_details=SimpleNamespace(
            reasoning_tokens=reasoning_tokens
        ),
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def test_finish_reason_error_is_a_plain_retryable_failure() -> None:
    """A mid-stream provider error is not a thinking-only response.

    OpenRouter reports an upstream failure mid-stream as
    ``finish_reason="error"``, which production hit repeatedly (reasoning
    tokens spent, no answer). The model did not choose to stop -- the
    provider errored -- so this must not disable thinking for every later
    attempt; it is answered by a plain retry instead.
    """
    response = _empty_response("error", reasoning_tokens=519)

    with pytest.raises(ValueError) as caught:
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")

    assert type(caught.value) is ValueError
    assert "error" in str(caught.value).lower()


def test_finish_reason_stop_with_reasoning_still_classifies_thinking_only() -> (
    None
):
    """The genuine case is untouched: a normal stop with no answer.

    Pins that narrowing the classification to exclude provider errors did
    not also narrow out the case it exists for.
    """
    response = _empty_response("stop", reasoning_tokens=1149)

    with pytest.raises(LLMThinkingOnlyError):
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")


def test_finish_reason_length_still_classifies_budget_exhausted() -> None:
    """``finish_reason="length"`` is checked, and wins, before "error" is."""
    response = _empty_response("length", reasoning_tokens=18000)

    with pytest.raises(LLMBudgetExhaustedError):
        _extract_completion_content(response, "openrouter/z-ai/glm-5.3-flash")

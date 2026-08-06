"""Tests for ``co_scientist.llm_response.extract_token_usage``."""

from types import SimpleNamespace

from co_scientist.llm_response import TokenUsage, extract_token_usage


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

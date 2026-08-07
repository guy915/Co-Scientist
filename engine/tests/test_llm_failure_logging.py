"""What the LLM wrappers log when a call fails, and at what level.

Two properties, both learned from a production diagnostics export where ten
of forty records were errors and eight of them were a condition the retry
ladder had already recovered from.

1. Severity tracks the remedy, not the event. A failure another attempt will
   answer is a warning; ERROR is for the attempt that gives up. Otherwise a
   healthy run reads as broken and a real failure is impossible to spot.
2. A provider error is logged at a bounded length. DeepSeek reports a
   truncated json-mode response by embedding the whole completion in the
   error text, and that landed twice per occurrence in a store whose single
   writer this codebase has already had starved by log volume.
"""

import logging
from typing import Any

import pytest

from co_scientist.llm import CompletionSpec, call_llm_json
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_wrapper_fakes import (
    make_completion as _completion,
)
from tests._llm_wrapper_fakes import (
    make_message as _message,
)
from tests._llm_wrapper_fakes import (
    make_usage as _usage,
)

_MODEL = "deepseek/deepseek-v4-flash"

_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}

# The shape of the real offender: litellm's DeepSeek json-mode parse failure
# appends "Original Response: {...}" carrying the entire completion.
_HUGE_PROVIDER_ERROR = (
    "litellm.APIError: APIError: DeepseekException - Unable to get json "
    "response - Unterminated string starting at: line 1 column 184 "
    "(char 183), Original Response: " + ("{payload}" * 900)
)


def _answerless() -> Any:
    """A completion that reasoned, stopped normally, and wrote no answer."""
    return _completion(
        _message(None),
        usage=_usage(3938, 523, reasoning_tokens=523),
        finish_reason="stop",
    )


def _serve(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> None:
    """Patch the completion seam to return ``responses`` in order.

    An entry that is an exception is raised instead of returned; the last
    entry repeats once the list is spent.
    """
    remaining = list(responses)

    async def fake(**_kwargs: Any) -> Any:
        item = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", fake)


async def test_a_recovered_call_logs_no_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An answerless completion the ladder recovers from is not an error."""
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless(), _completion(_message('{"a":1}'))])

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        result = await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=5,
        )

    assert result == {"a": 1}
    assert [
        r.message for r in caplog.records if r.levelno >= logging.ERROR
    ] == []
    # The retry is still reported -- demoting it must not make it silent.
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_the_attempt_that_gives_up_still_logs_an_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Severity is about the remedy, so exhausting the ladder is an error."""
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless()])

    with (
        caplog.at_level(logging.DEBUG, logger="co_scientist"),
        pytest.raises(ValueError),
    ):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=2,
        )

    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_a_provider_error_is_logged_at_a_bounded_length(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No log record carries the whole completion the provider echoed back."""
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [RuntimeError(_HUGE_PROVIDER_ERROR)])

    with (
        caplog.at_level(logging.DEBUG, logger="co_scientist"),
        pytest.raises(RuntimeError),
    ):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=1,
        )

    assert caplog.records
    for record in caplog.records:
        assert len(record.getMessage()) < 1000
    # The head identifies the failure, so truncation must keep it.
    assert any("Unterminated string" in r.getMessage() for r in caplog.records)

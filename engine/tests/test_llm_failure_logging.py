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


def _llm_layer_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    """Failure records from below the retry loop, which must stay silent.

    Scoped to WARNING and above: those layers still trace at debug, and
    the point is that a reader's diagnostics panel sees one record, not
    that the modules never speak.
    """
    return [
        r
        for r in caplog.records
        if r.name
        in (
            "co_scientist.llm",
            "co_scientist.llm.call",
            "co_scientist.llm.request.response",
        )
        and r.levelno >= logging.WARNING
    ]


async def test_one_failed_attempt_logs_one_failure_record(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Three layers saw the same failure and all three wrote it down.

    ``llm.request.response`` logged the empty completion, ``call_llm`` logged
    the call, and the retry loop logged the attempt -- one answerless
    completion, three records saying the same sentence. A production export of a
    run that recovered fine read as 27 errors and 29 warnings, which is what a
    reader has to page through to find a real fault.
    """
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless(), _completion(_message('{"a":1}'))])

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=5,
        )

    failures = [r for r in caplog.records if "LLM call failed" in r.message]
    assert len(failures) == 1
    assert failures[0].name == "co_scientist.llm.attempts.retry"
    assert _llm_layer_records(caplog) == []


async def test_the_failure_record_carries_the_budget_actually_sent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The surviving record reports the floored budget, not the asked one.

    The thinking floor raises the budget before the request goes out, so a
    record printing the call site's own number sat beside a reasoning-token
    count larger than it and read as a provider fault. Folding three
    records into one must not drop the number that settles that.
    """
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless(), _completion(_message('{"a":1}'))])

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL, max_tokens=8000, json_schema=_INT_SCHEMA
            ),
            max_attempts=5,
        )

    failure = next(r for r in caplog.records if "LLM call failed" in r.message)
    assert "max_tokens 18000" in failure.getMessage()
    assert "asked for 8000" in failure.getMessage()


async def test_the_failure_record_names_the_call_that_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One shared loop logs every node's failures, so it must say which.

    A production export of fifteen answerless completions could be
    narrowed no further than the budget constant the request carried, and
    ten call sites ask for the commonest one. The schema name is the
    fallback label because every structured call has one.
    """
    _disable_cache(monkeypatch)
    _serve(monkeypatch, [_answerless(), _completion(_message('{"a":1}'))])

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL,
                json_schema={"name": "ranking_judgment", **_INT_SCHEMA},
            ),
            max_attempts=5,
        )

    failure = next(r for r in caplog.records if "LLM call failed" in r.message)
    assert "ranking_judgment" in failure.getMessage()


async def test_a_direct_call_llm_failure_logs_once_per_attempt(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Silencing the raw call layer under the retry loop must not silence it.

    ``debate`` and the literature-review synthesis call ``call_llm``
    directly, and ``call_llm`` runs on the same attempt loop
    (``llm.attempts.retry``) as ``call_llm_json`` -- so a repeated failure
    logs once per attempt, not once per underlying raw call PLUS once per
    attempt, and the raw call layer itself
    (``co_scientist.llm``/``co_scientist.llm.attempts.single``) stays silent
    under it exactly as it does under ``call_llm_json``.
    """
    from co_scientist.llm import call_llm

    _disable_cache(monkeypatch)
    _serve(monkeypatch, [RuntimeError("provider exploded")])

    with (
        caplog.at_level(logging.DEBUG, logger="co_scientist"),
        pytest.raises(RuntimeError),
    ):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_MODEL), max_attempts=3
        )

    failures = [r for r in caplog.records if "LLM call failed" in r.message]
    assert len(failures) == 3
    assert {r.name for r in failures} == {"co_scientist.llm.attempts.retry"}
    assert [r.levelno for r in failures] == [
        logging.WARNING,
        logging.WARNING,
        logging.ERROR,
    ]
    assert _llm_layer_records(caplog) == []


def test_a_repaired_truncation_reports_the_phase_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two layers wrote down one truncated response; only one should.

    The repair helper named the strategy index and its caller named the
    phase, both at warning, so every truncated completion cost a reader
    two records to learn one fact. The phase is the fact; the strategy
    index is for someone debugging the repair strategies.
    """
    from co_scientist.llm import parse_tool_loop_json

    truncated = '{"items": [{"a": 1}, {"a": 2'

    with caplog.at_level(logging.DEBUG, logger="co_scientist"):
        parsed = parse_tool_loop_json(truncated, "items", "Draft phase")

    assert parsed
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Draft phase" in warnings[0].getMessage()
    # The strategy index survives, at a level a reader is not paging past.
    assert any(
        "major repair strategy" in r.getMessage() and r.levelno == logging.DEBUG
        for r in caplog.records
    )

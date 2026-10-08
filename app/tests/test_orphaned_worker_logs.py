from __future__ import annotations

import io
import json
import logging

import pytest
from co_scientist.platform.db.log_capture import _drop_orphaned_logging_worker_noise
from co_scientist.platform.telemetry.logging_setup import configure_logging

_DESTROYED = (
    "Task was destroyed but it is pending!\n"
    "task: <Task pending name='Task-7' coro=<LoggingWorker._worker_loop() running at "
    "/site-packages/litellm/litellm_core_utils/logging_worker.py:121>>"
)
_NEVER_RETRIEVED = (
    "Task exception was never retrieved\n"
    "future: <Task finished name='Task-9' coro=<LoggingWorker._process_log_task() done, "
    "defined at /site-packages/litellm/litellm_core_utils/logging_worker.py:92> "
    "exception=ValueError('task_done() called too many times')>"
)


def _asyncio_record(message: str) -> logging.LogRecord:
    return logging.LogRecord("asyncio", logging.ERROR, __file__, 1, message, (), None)


def _stdout_payloads(*records: logging.LogRecord) -> list[dict[str, object]]:
    handler = configure_logging()
    stream = io.StringIO()
    handler.stream = stream  # type: ignore[attr-defined]
    try:
        for record in records:
            handler.handle(record)
    finally:
        configure_logging()
    return [json.loads(line) for line in stream.getvalue().splitlines()]


@pytest.mark.parametrize("message", [_DESTROYED, _NEVER_RETRIEVED])
def test_orphaned_litellm_worker_prints_as_a_warning_with_a_note(message: str) -> None:
    [payload] = _stdout_payloads(_asyncio_record(message))

    assert payload["level"] == "WARNING"
    assert payload["message"] == message
    assert "LiteLLM logging worker" in str(payload["note"])


@pytest.mark.parametrize("message", [_DESTROYED, _NEVER_RETRIEVED])
def test_orphaned_litellm_worker_is_not_captured_against_a_run(message: str) -> None:
    assert _drop_orphaned_logging_worker_noise(_asyncio_record(message)) is False


def test_an_application_task_leak_stays_an_error_and_is_captured() -> None:
    leak = _asyncio_record(
        "Task was destroyed but it is pending!\ntask: <Task pending coro=<drain_queue()>>"
    )

    [payload] = _stdout_payloads(leak)

    assert payload["level"] == "ERROR"
    assert "note" not in payload
    assert _drop_orphaned_logging_worker_noise(leak) is True

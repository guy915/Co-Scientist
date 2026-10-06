from __future__ import annotations

import logging
import logging.handlers

import pytest

from app.logging_setup import (
    configure_log_capture,
    run_log_context,
    shutdown_log_capture,
)
from app.store import logs
from app.store.logs import NewLogRecord


@pytest.fixture(autouse=True)
def _teardown_capture() -> object:
    yield
    shutdown_log_capture()


def _flush() -> None:
    shutdown_log_capture()


def _test_logger() -> logging.Logger:
    # Set logger levels explicitly because the root logger may remain at
    # WARNING.
    test_logger = logging.getLogger("app.capture_test")
    test_logger.setLevel(logging.INFO)
    return test_logger


def test_capture_persists_records_with_run_id_and_exception_text(
    isolated_db: str,
) -> None:
    configure_log_capture(level=logging.INFO)
    configure_log_capture(level=logging.INFO)
    test_logger = _test_logger()
    test_logger.info("plain record %d", 7)
    with run_log_context("run-42"):
        test_logger.warning("scoped record")
    try:
        raise ValueError("kaboom")
    except ValueError:
        test_logger.exception("operation failed")
    _flush()
    rows = logs.list_logs(db_path=isolated_db)
    assert len(rows) == 3
    by_message = {row["message"]: row for row in rows}
    assert "ValueError: kaboom" in by_message["operation failed"]["exc_text"]
    assert by_message["plain record 7"]["run_id"] is None
    assert by_message["plain record 7"]["level"] == "INFO"
    assert by_message["plain record 7"]["logger"] == "app.capture_test"
    assert by_message["scoped record"]["run_id"] == "run-42"


def test_configure_prunes_existing_backlog(isolated_db: str) -> None:
    for i in range(10):
        logs.append_log(
            NewLogRecord(
                level="INFO",
                levelno=logging.INFO,
                logger_name="app.capture_test",
                message=f"old {i}",
            ),
            db_path=isolated_db,
        )
    configure_log_capture(max_rows=4)
    _flush()
    assert len(logs.list_logs(db_path=isolated_db)) == 4


def test_store_failure_does_not_break_logging(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(**kwargs: object) -> int:
        raise RuntimeError("db exploded")

    monkeypatch.setattr("app.logging_setup.store.append_log", boom)
    configure_log_capture()
    test_logger = _test_logger()
    test_logger.info("first")
    test_logger.info("second")
    _flush()
    err = capsys.readouterr().err
    assert err.count("log capture") == 1


def test_capture_drops_chatter_and_keeps_real_messages(
    isolated_db: str,
) -> None:
    # Dependency chatter, repeated records and an orphaned LiteLLM worker's
    # destroyed-task error must not crowd out or fail an unrelated run.
    configure_log_capture()
    for name in ("LiteLLM", "httpx", "mcp.client.streamable_http"):
        chatty = logging.getLogger(name)
        chatty.setLevel(logging.INFO)
        chatty.info("routine %s chatter", name)
        chatty.warning("%s is in trouble", name)
    probe = logging.getLogger("co_scientist.mcp_client")
    probe.setLevel(logging.INFO)
    for _ in range(20):
        probe.warning("MCP server unavailable at %s", "http://127.0.0.1:9/mcp")
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.setLevel(logging.INFO)
    with run_log_context("run-orphan"):
        asyncio_logger.error(
            "Task was destroyed but it is pending!\ntask: <Task pending "
            "name='Task-1676' coro=<LoggingWorker._worker_loop() running "
            "at /x/litellm/litellm_core_utils/logging_worker.py:121>>"
        )
        asyncio_logger.error(
            "Task was destroyed but it is pending!\ntask: <Task pending "
            "name='Task-9' coro=<run_run_worker_pool() running at x.py:1>>"
        )
    _flush()

    messages = [row["message"] for row in logs.list_logs(db_path=isolated_db)]
    assert not [m for m in messages if m.startswith("routine ")]
    assert len([m for m in messages if "is in trouble" in m]) == 3
    assert (
        messages.count("MCP server unavailable at http://127.0.0.1:9/mcp") == 1
    )
    assert not [m for m in messages if "LoggingWorker._worker_loop" in m]
    assert len([m for m in messages if "run_run_worker_pool" in m]) == 1

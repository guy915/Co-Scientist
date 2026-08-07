"""Tests for persistent log capture (root logger -> app_logs table)."""

from __future__ import annotations

import logging
import logging.handlers

import pytest

from app import store
from app.logging_setup import (
    configure_log_capture,
    run_log_context,
    shutdown_log_capture,
)


@pytest.fixture(autouse=True)
def _teardown_capture() -> object:
    """Always stop capture after a test so later tests start clean."""
    yield
    shutdown_log_capture()


def _flush() -> None:
    """Stop the capture pipeline, draining queued records to the store."""
    shutdown_log_capture()


def _test_logger() -> logging.Logger:
    """Return the test logger with an explicit level.

    The test process never calls ``configure_logging``, so the root
    logger sits at its WARNING default; an explicit level makes INFO
    records propagate so the capture handler's own threshold is what is
    under test.
    """
    test_logger = logging.getLogger("app.capture_test")
    test_logger.setLevel(logging.INFO)
    return test_logger


def test_capture_persists_records_with_run_id(isolated_db: str) -> None:
    configure_log_capture()
    test_logger = _test_logger()
    test_logger.info("plain record %d", 7)
    with run_log_context("run-42"):
        test_logger.warning("scoped record")
    _flush()
    rows = store.list_logs(db_path=isolated_db)
    by_message = {row["message"]: row for row in rows}
    assert by_message["plain record 7"]["run_id"] is None
    assert by_message["plain record 7"]["level"] == "INFO"
    assert by_message["plain record 7"]["logger"] == "app.capture_test"
    assert by_message["scoped record"]["run_id"] == "run-42"


def test_capture_formats_exception_text(isolated_db: str) -> None:
    configure_log_capture()
    test_logger = _test_logger()
    try:
        raise ValueError("kaboom")
    except ValueError:
        test_logger.exception("operation failed")
    _flush()
    rows = store.list_logs(db_path=isolated_db)
    assert len(rows) == 1
    assert rows[0]["message"] == "operation failed"
    assert "ValueError: kaboom" in rows[0]["exc_text"]


def test_capture_respects_level_threshold(isolated_db: str) -> None:
    configure_log_capture(level=logging.WARNING)
    test_logger = _test_logger()
    test_logger.info("too quiet")
    test_logger.error("loud enough")
    _flush()
    rows = store.list_logs(db_path=isolated_db)
    assert [row["message"] for row in rows] == ["loud enough"]


def test_configure_prunes_existing_backlog(isolated_db: str) -> None:
    for i in range(10):
        store.append_log(
            store.NewLogRecord(
                level="INFO",
                levelno=logging.INFO,
                logger_name="app.capture_test",
                message=f"old {i}",
            ),
            db_path=isolated_db,
        )
    configure_log_capture(max_rows=4)
    _flush()
    assert len(store.list_logs(db_path=isolated_db)) == 4


def test_reconfigure_does_not_duplicate_records(isolated_db: str) -> None:
    configure_log_capture()
    configure_log_capture()
    _test_logger().info("once only")
    _flush()
    rows = store.list_logs(db_path=isolated_db)
    assert [row["message"] for row in rows] == ["once only"]


def test_capture_includes_non_propagating_uvicorn_loggers(
    isolated_db: str,
) -> None:
    """Persist HTTP access records from uvicorn's own loggers.

    Uvicorn configures those loggers with propagate=False in production,
    so the capture handler must be attached to them directly.
    """
    access = logging.getLogger("uvicorn.access")
    prior_propagate = access.propagate
    prior_level = access.level
    access.propagate = False  # mirror uvicorn's production config
    access.setLevel(logging.INFO)
    try:
        configure_log_capture()
        access.info('127.0.0.1:1 - "GET /status HTTP/1.1" 200')
        _flush()
    finally:
        access.propagate = prior_propagate
        access.setLevel(prior_level)
    rows = store.list_logs(db_path=isolated_db)
    assert ['"GET /status HTTP/1.1"' in row["message"] for row in rows] == [
        True
    ]


def test_capture_skips_own_polling_endpoint_access_logs(
    isolated_db: str,
) -> None:
    """Drop access records for the log endpoint itself.

    Otherwise polling the log view would append to the log being viewed.
    """
    access = logging.getLogger("uvicorn.access")
    prior_propagate = access.propagate
    prior_level = access.level
    access.propagate = False
    access.setLevel(logging.INFO)
    try:
        configure_log_capture()
        access.info('127.0.0.1:1 - "GET /api/logs?after_id=0 HTTP/1.1" 200')
        access.info('127.0.0.1:1 - "GET /api/runs HTTP/1.1" 200')
        _flush()
    finally:
        access.propagate = prior_propagate
        access.setLevel(prior_level)
    messages = [row["message"] for row in store.list_logs(db_path=isolated_db)]
    assert any("/api/runs" in message for message in messages)
    assert not any("/api/logs" in message for message in messages)


def test_propagating_uvicorn_record_is_captured_once(
    isolated_db: str,
) -> None:
    """Capture a propagating record exactly once.

    Without uvicorn's production config the access logger propagates to
    root, so the handler is reachable at several attachment points.
    """
    access = logging.getLogger("uvicorn.access")
    prior_level = access.level
    access.setLevel(logging.INFO)
    assert access.propagate  # in-process default
    try:
        configure_log_capture()
        access.info('127.0.0.1:1 - "GET /api/runs HTTP/1.1" 200')
        _flush()
    finally:
        access.setLevel(prior_level)
    rows = store.list_logs(db_path=isolated_db)
    assert len(rows) == 1


def test_capture_stop_detaches_uvicorn_loggers(isolated_db: str) -> None:
    capture = configure_log_capture()
    access = logging.getLogger("uvicorn.access")
    attached = [
        handler
        for handler in access.handlers
        if isinstance(handler, logging.handlers.QueueHandler)
    ]
    assert attached
    capture.stop()
    assert not [handler for handler in access.handlers if handler in attached]


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
    # Neither call may raise, even though every write fails.
    test_logger.info("first")
    test_logger.info("second")
    _flush()
    err = capsys.readouterr().err
    # One warning latch, not one line per failed record.
    assert err.count("log capture") == 1


def test_high_volume_dependency_loggers_are_not_persisted(
    isolated_db: str,
) -> None:
    """Chatty dependency records must not reach the database at all.

    The read path already hides these below WARNING, so persisting them
    only buys rows nobody reads -- and it is not free. In production they
    were 84% of the table (LiteLLM alone 9,928 of 20,021 rows), each an
    open-write-close against a database with a single writer and no fair
    queuing. That stream starved ordinary API writes until creating a run
    failed with "database is locked". Filtering at capture keeps the
    default view identical while removing most of the write load.

    Anything at WARNING or above still persists: those are the records
    that say a dependency is in trouble.
    """
    configure_log_capture()
    for name in ("LiteLLM", "httpx", "mcp.client.streamable_http"):
        chatty = logging.getLogger(name)
        chatty.setLevel(logging.INFO)
        chatty.info("routine %s chatter", name)
        chatty.warning("%s is in trouble", name)
    _flush()

    rows = store.list_logs(db_path=isolated_db)
    messages = {row["message"] for row in rows}
    assert not [m for m in messages if m.startswith("routine ")]
    assert len([m for m in messages if "is in trouble" in m]) == 3


def test_repeated_identical_records_are_persisted_once(
    isolated_db: str,
) -> None:
    """A steady-state condition must not refill the log on every probe.

    The MCP availability probe warns once per /status refresh, and both
    noise filters exempt WARNING and above, so an unconfigured or
    unreachable server wrote two rows every 30-60 seconds forever. On an
    idle app that was the only thing growing: the Logs panel shows a
    fixed newest-100 window, so after about half an hour the whole window
    was one message repeated and the log read as though nothing was being
    collected.

    The first occurrence still persists in full -- a real problem must
    stay visible -- and only verbatim repeats inside the window are
    dropped.
    """
    configure_log_capture()
    probe = logging.getLogger("co_scientist.mcp_client_availability")
    probe.setLevel(logging.INFO)
    for _ in range(20):
        probe.warning("MCP server unavailable at %s", "http://127.0.0.1:9/mcp")
    probe.warning("MCP server responded but provided no tools")
    _flush()

    rows = store.list_logs(db_path=isolated_db)
    messages = [row["message"] for row in rows]
    assert (
        messages.count("MCP server unavailable at http://127.0.0.1:9/mcp") == 1
    )
    # A different message from the same logger is its own condition.
    assert "MCP server responded but provided no tools" in messages


def test_orphaned_litellm_worker_tasks_are_not_persisted(
    isolated_db: str,
) -> None:
    """A destroyed litellm logging-worker task stays out of the database.

    The message is an ERROR emitted by asyncio's garbage collector, from
    a task litellm orphaned on an event-loop rebind (see
    ``app.litellm_shutdown``). Nothing is wrong when it fires and nothing
    in this app can prevent it, but it lands against whatever run is
    executing at collection time and reads as that run failing.
    """
    configure_log_capture()
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

    messages = {row["message"] for row in store.list_logs(db_path=isolated_db)}
    assert not [m for m in messages if "LoggingWorker._worker_loop" in m]
    # A destroyed task of ours is a real leak and must still surface.
    assert len([m for m in messages if "run_run_worker_pool" in m]) == 1

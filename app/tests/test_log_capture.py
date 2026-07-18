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
            level="INFO",
            levelno=logging.INFO,
            logger_name="app.capture_test",
            message=f"old {i}",
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

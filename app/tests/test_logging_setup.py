"""Tests for the app logging module: formats, run-id tagging, idempotency."""

from __future__ import annotations

import io
import json
import logging

from app.logging_setup import (
    TEXT_FORMAT,
    JsonFormatter,
    RunIdFilter,
    TextRunIdFormatter,
    configure_logging,
    current_run_id,
    run_log_context,
)
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status


def _record(message: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def _restore_default_logging() -> None:
    """Reinstall the app's default handler so later tests see normal logs."""
    from app.config import settings

    configure_logging(settings.log_format)


# --- run-id context ----------------------------------------------------------


def test_run_log_context_binds_and_restores_run_id() -> None:
    assert current_run_id() is None
    with run_log_context("run-123"):
        assert current_run_id() == "run-123"
    assert current_run_id() is None


def test_run_id_filter_stamps_context_run_id_onto_records() -> None:
    record = _record()
    with run_log_context("run-abc"):
        RunIdFilter().filter(record)
    assert record.run_id == "run-abc"  # type: ignore[attr-defined]

    unscoped = _record()
    RunIdFilter().filter(unscoped)
    assert unscoped.run_id is None  # type: ignore[attr-defined]


# --- formatters --------------------------------------------------------------


def test_text_formatter_appends_run_id_suffix_only_when_bound() -> None:
    formatter = TextRunIdFormatter(TEXT_FORMAT)

    tagged = _record()
    tagged.run_id = "run-xyz"
    assert formatter.format(tagged).endswith(" [run_id=run-xyz]")

    plain = _record()
    plain.run_id = None
    assert "run_id" not in formatter.format(plain)


def test_json_formatter_emits_structured_fields() -> None:
    record = _record("structured message")
    record.run_id = "run-json"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "structured message"
    assert payload["run_id"] == "run-json"
    assert "time" in payload


def test_json_formatter_includes_exception_detail() -> None:
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        import sys

        record = _record("failed")
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(record))

    assert "kaboom" in payload["exc_info"]


# --- configure_logging -------------------------------------------------------


def _cosci_handlers() -> list[logging.Handler]:
    return [
        h
        for h in logging.getLogger().handlers
        if getattr(h, "_cosci_handler", False)
    ]


def test_configure_logging_is_idempotent_and_selects_format() -> None:
    try:
        configure_logging("json")
        configure_logging("json")
        handlers = _cosci_handlers()
        assert len(handlers) == 1
        assert isinstance(handlers[0].formatter, JsonFormatter)

        configure_logging("text")
        handlers = _cosci_handlers()
        assert len(handlers) == 1
        assert isinstance(handlers[0].formatter, TextRunIdFormatter)
    finally:
        _restore_default_logging()


def test_configured_handler_emits_run_tagged_json_lines() -> None:
    try:
        handler = configure_logging("json")
        stream = io.StringIO()
        handler.stream = stream  # type: ignore[attr-defined]

        with run_log_context("run-e2e"):
            logging.getLogger("app.sample").info("inside run scope")

        lines = [
            json.loads(line)
            for line in stream.getvalue().splitlines()
            if line.strip()
        ]
        tagged = [ln for ln in lines if ln.get("run_id") == "run-e2e"]
        assert tagged and tagged[0]["message"] == "inside run scope"
    finally:
        _restore_default_logging()


# --- workflow correlation ----------------------------------------------------


def test_workflow_records_carry_the_run_id(isolated_db: str) -> None:
    """Records logged inside a run's workflow task carry that run's id.

    Uses a list-capturing handler with the RunIdFilter attached (mirroring
    the configured stdout handler) so the assertion sees exactly what the
    formatter would.
    """

    class _Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    capture = _Capture()
    capture.addFilter(RunIdFilter())
    logging.getLogger().addHandler(capture)
    try:
        client = _client()
        created = client.post(
            "/api/runs",
            json={
                "research_goal": "Correlate logs with events",
                "tier": "express",
            },
        )
        run_id = created.json()["id"]
        started = client.post(f"/api/runs/{run_id}/start", json={})
        assert started.status_code == 200
        assert _wait_status(client, run_id, "completed", timeout=30.0)
    finally:
        logging.getLogger().removeHandler(capture)

    tagged = {getattr(r, "run_id", None) for r in capture.records}
    assert run_id in tagged

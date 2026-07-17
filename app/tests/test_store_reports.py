"""Tests for report persistence edge cases in ``app.store.reports``.

``save_report``'s happy path and ``read_report_markdown``'s DB-text-preferred
path are already covered by ``test_store.py``; this file covers the
disk-write failure branch and the on-disk fallback used for report rows that
predate the ``markdown_text`` column.
"""

from __future__ import annotations

import logging
import pathlib
from pathlib import Path

import pytest

from app import store


def _insert_legacy_report_row(
    db_path: str, run_id: str, report_id: str, markdown_path: str | None
) -> None:
    """Insert a report row with no ``markdown_text`` (pre-column schema)."""
    with store.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO reports (id, run_id, payload_json, markdown_path, "
            "markdown_text, created_at) VALUES (?,?,?,?,?,?)",
            (report_id, run_id, "{}", markdown_path, None, 0.0),
        )


def test_save_report_logs_warning_on_disk_write_failure(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A disk write failure is logged, but the DB row is still persisted."""
    run = store.create_run(
        "disk failure goal", "default", "mock", {}, db_path=isolated_db
    )

    def _boom(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _boom)

    with caplog.at_level(logging.WARNING, logger="app.store.reports"):
        saved = store.save_report(
            run.id, {"k": "v"}, "# md body", db_path=isolated_db
        )

    assert "Could not write report markdown to disk" in caplog.text
    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["id"] == saved["id"]
    assert report["markdown_text"] == "# md body"


def test_read_report_markdown_falls_back_to_disk_when_db_text_missing(
    isolated_db: str, tmp_path: pathlib.Path
) -> None:
    """Rows written before markdown_text existed fall back to the disk file."""
    run = store.create_run(
        "disk fallback goal", "default", "mock", {}, db_path=isolated_db
    )
    md_file = tmp_path / "on_disk.md"
    md_file.write_text("# From disk", encoding="utf-8")

    _insert_legacy_report_row(
        isolated_db, run.id, "report-disk-1", str(md_file)
    )

    text = store.read_report_markdown(run.id, db_path=isolated_db)
    assert text == "# From disk"


def test_read_report_markdown_none_without_db_text_or_path(
    isolated_db: str,
) -> None:
    """No markdown_text and no markdown_path yields None, not a crash."""
    run = store.create_run(
        "no source goal", "default", "mock", {}, db_path=isolated_db
    )
    _insert_legacy_report_row(isolated_db, run.id, "report-disk-2", None)

    assert store.read_report_markdown(run.id, db_path=isolated_db) is None


def test_get_latest_report_and_read_markdown_none_without_any_report(
    isolated_db: str,
) -> None:
    """A run with no report row at all yields None from both readers."""
    run = store.create_run(
        "no report goal", "default", "mock", {}, db_path=isolated_db
    )
    assert store.get_latest_report(run.id, db_path=isolated_db) is None
    assert store.read_report_markdown(run.id, db_path=isolated_db) is None


def test_read_report_markdown_none_when_disk_file_missing(
    isolated_db: str, tmp_path: pathlib.Path
) -> None:
    """A markdown_path pointing at a deleted file yields None, not a crash."""
    run = store.create_run(
        "missing file goal", "default", "mock", {}, db_path=isolated_db
    )
    missing_path = tmp_path / "does_not_exist.md"

    _insert_legacy_report_row(
        isolated_db, run.id, "report-disk-3", str(missing_path)
    )

    assert store.read_report_markdown(run.id, db_path=isolated_db) is None

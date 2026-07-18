"""Tests for the persisted application log store (app_logs table)."""

from __future__ import annotations

import logging

from app import store


def _append(
    isolated_db: str,
    message: str,
    *,
    level: str = "INFO",
    levelno: int = logging.INFO,
    logger_name: str = "app.test",
    run_id: str | None = None,
    exc_text: str | None = None,
) -> int:
    return store.append_log(
        level=level,
        levelno=levelno,
        logger_name=logger_name,
        message=message,
        run_id=run_id,
        exc_text=exc_text,
        db_path=isolated_db,
    )


def test_append_and_list_roundtrip(isolated_db: str) -> None:
    row_id = _append(
        isolated_db,
        "hello world",
        run_id="run-1",
        exc_text="Traceback: boom",
    )
    rows = store.list_logs(db_path=isolated_db)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == row_id
    assert row["level"] == "INFO"
    assert row["levelno"] == logging.INFO
    assert row["logger"] == "app.test"
    assert row["message"] == "hello world"
    assert row["run_id"] == "run-1"
    assert row["exc_text"] == "Traceback: boom"
    assert row["created_at"] > 0


def test_list_after_id_and_limit(isolated_db: str) -> None:
    ids = [_append(isolated_db, f"m{i}") for i in range(5)]
    rows = store.list_logs(after_id=ids[1], db_path=isolated_db)
    assert [row["message"] for row in rows] == ["m2", "m3", "m4"]
    rows = store.list_logs(limit=2, db_path=isolated_db)
    # A limit keeps the NEWEST rows, still returned in ascending order.
    assert [row["message"] for row in rows] == ["m3", "m4"]


def test_list_filters_by_min_level(isolated_db: str) -> None:
    _append(isolated_db, "debugging", level="DEBUG", levelno=logging.DEBUG)
    _append(isolated_db, "informational")
    _append(isolated_db, "bad", level="ERROR", levelno=logging.ERROR)
    rows = store.list_logs(min_levelno=logging.WARNING, db_path=isolated_db)
    assert [row["message"] for row in rows] == ["bad"]


def test_list_filters_by_run_and_substring(isolated_db: str) -> None:
    _append(isolated_db, "global line")
    _append(isolated_db, "run line one", run_id="run-1")
    _append(isolated_db, "run line two", run_id="run-1")
    _append(isolated_db, "other run", run_id="run-2")
    rows = store.list_logs(run_id="run-1", db_path=isolated_db)
    assert [row["message"] for row in rows] == ["run line one", "run line two"]
    rows = store.list_logs(contains="line one", db_path=isolated_db)
    assert [row["message"] for row in rows] == ["run line one"]


def test_count_logs_ignores_limit_and_respects_filters(
    isolated_db: str,
) -> None:
    for i in range(5):
        _append(isolated_db, f"info {i}")
    _append(isolated_db, "bad", level="ERROR", levelno=logging.ERROR)
    _append(isolated_db, "scoped", run_id="run-1")
    assert store.count_logs(db_path=isolated_db) == 7
    assert (
        store.count_logs(min_levelno=logging.WARNING, db_path=isolated_db) == 1
    )
    assert store.count_logs(run_id="run-1", db_path=isolated_db) == 1
    assert store.count_logs(contains="info", db_path=isolated_db) == 5


def test_prune_logs_keeps_newest(isolated_db: str) -> None:
    for i in range(10):
        _append(isolated_db, f"m{i}")
    deleted = store.prune_logs(max_rows=4, db_path=isolated_db)
    assert deleted == 6
    rows = store.list_logs(db_path=isolated_db)
    assert [row["message"] for row in rows] == ["m6", "m7", "m8", "m9"]
    # Under the cap: nothing to delete.
    assert store.prune_logs(max_rows=4, db_path=isolated_db) == 0


def test_clear_logs_empties_and_restarts_ids(isolated_db: str) -> None:
    for i in range(3):
        _append(isolated_db, f"m{i}")
    assert store.clear_logs(db_path=isolated_db) == 3
    assert store.list_logs(db_path=isolated_db) == []
    # A clear is a fresh start: ids restart at 1 so the id-numbered UI
    # badge reads as a count again. Followers detect the reset via
    # last_id dropping below their cursor.
    assert _append(isolated_db, "after clear") == 1


def test_clear_logs_on_empty_table_returns_zero(isolated_db: str) -> None:
    assert store.clear_logs(db_path=isolated_db) == 0


def test_latest_log_id(isolated_db: str) -> None:
    assert store.latest_log_id(db_path=isolated_db) == 0
    last = 0
    for i in range(3):
        last = _append(isolated_db, f"m{i}")
    assert store.latest_log_id(db_path=isolated_db) == last

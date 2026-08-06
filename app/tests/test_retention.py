"""Tests for the time-based retention sweep (N4): app.retention."""

from __future__ import annotations

import io
import sqlite3
import time

import pytest

from app import retention, store
from tests._client import make_client


def _backdate_completion(db_path: str, run_id: str, seconds_ago: float) -> None:
    """Force a run's completed_at/updated_at into the past for a test.

    ``store`` has no setter for this (a real run's timestamps are always
    "now" when it settles), so the sweep's age judgment is exercised here
    by writing the column directly rather than by waiting out real time.
    """
    backdated = time.time() - seconds_ago
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET completed_at=?, updated_at=? WHERE id=?",
            (backdated, backdated, run_id),
        )


def test_run_retention_days_defaults_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_RUN_RETENTION_DAYS", raising=False)
    assert retention.run_retention_days() == 90


def test_run_retention_days_reads_the_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSCIENTIST_RUN_RETENTION_DAYS", "5")
    assert retention.run_retention_days() == 5


def test_zero_disables_the_run_sweep(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COSCIENTIST_RUN_RETENTION_DAYS", "0")
    client = make_client()
    created = client.post(
        "/api/runs",
        headers={"X-Client-ID": "retention-tester"},
        json={"research_goal": "Old completed goal"},
    )
    run_id = created.json()["id"]
    store.update_run_status(run_id, store.RunStatus.COMPLETED)

    deleted = retention.sweep_expired_runs(now=time.time() + 10_000 * 86_400)

    assert deleted == []
    assert store.run_exists(run_id)


def test_sweep_deletes_only_terminal_runs_past_the_window(
    isolated_db: str,
) -> None:
    client = make_client()
    old_completed = client.post(
        "/api/runs",
        headers={"X-Client-ID": "retention-tester"},
        json={"research_goal": "Old completed goal"},
    ).json()["id"]
    store.update_run_status(old_completed, store.RunStatus.COMPLETED)
    _backdate_completion(isolated_db, old_completed, 120 * 86_400)

    old_running = client.post(
        "/api/runs",
        headers={"X-Client-ID": "retention-tester"},
        json={"research_goal": "Old but still running"},
    ).json()["id"]
    store.update_run_status(old_running, store.RunStatus.RUNNING)
    _backdate_completion(isolated_db, old_running, 120 * 86_400)

    recent_completed = client.post(
        "/api/runs",
        headers={"X-Client-ID": "retention-tester"},
        json={"research_goal": "Just completed"},
    ).json()["id"]
    store.update_run_status(recent_completed, store.RunStatus.COMPLETED)

    # Only the completed row backdated past the default 90-day window
    # should be swept.
    deleted = retention.sweep_expired_runs()

    assert deleted == [old_completed]
    assert not store.run_exists(old_completed)
    assert store.run_exists(old_running)  # never terminal -> never swept
    assert store.run_exists(recent_completed)  # not yet expired


def test_sweep_expired_documents_deletes_only_past_the_window(
    isolated_db: str,
) -> None:
    client = make_client()
    staged = client.post(
        "/api/documents",
        headers={"X-Client-ID": "retention-tester"},
        files={"file": ("notes.txt", io.BytesIO(b"old notes"), "text/plain")},
        data={"consent": "true"},
    )
    document_id = staged.json()["id"]

    far_future = time.time() + 200 * 86_400
    deleted = retention.sweep_expired_documents(now=far_future)

    assert deleted == 1
    assert store.get_staged_documents([document_id], "retention-tester") == []


def test_sweep_expired_feedback_deletes_only_past_the_window(
    isolated_db: str,
) -> None:
    client = make_client()
    client.post(
        "/api/feedback",
        json={"message": "Old note", "category": "bug"},
    )

    far_future = time.time() + 400 * 86_400
    deleted = retention.sweep_expired_feedback(now=far_future)

    assert deleted == 1
    assert store.list_feedback() == []

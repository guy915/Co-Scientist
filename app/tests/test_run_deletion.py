"""Tests for permanent run deletion (N3/N4): DELETE /api/runs/{run_id}."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from app import store
from app.store.db import _reports_dir
from tests._client import append_log_row, make_client, wait_for

_OWNER = {"X-Client-ID": "delete-owner"}
_OTHER = {"X-Client-ID": "someone-else"}


def _wait_owned_status(
    client: TestClient, run_id: str, status: str, *, timeout: float = 30.0
) -> bool:
    """Poll ``GET /api/runs/{id}`` as ``_OWNER`` until it reaches ``status``.

    ``tests._client.wait_for_status`` only polls under the client's own
    default identity, so it cannot see a run created under a different,
    explicit ``X-Client-ID`` like the one this suite uses throughout.
    """

    def _reached() -> bool:
        response = client.get(f"/api/runs/{run_id}", headers=_OWNER)
        return response.status_code == 200 and bool(
            response.json().get("status") == status
        )

    return wait_for(_reached, timeout=timeout)


def _run_to_completion(client: TestClient, goal: str) -> str:
    """Create, start, and wait one express-tier offline run to completion."""
    created = client.post(
        "/api/runs",
        headers=_OWNER,
        json={"research_goal": goal, "tier": "express"},
    )
    assert created.status_code == 200, created.text
    run_id: str = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", headers=_OWNER, json={})
    assert started.status_code == 200, started.text
    assert _wait_owned_status(client, run_id, "completed")
    return run_id


def test_delete_requires_a_terminal_run() -> None:
    """An active run cannot be deleted out from under its workers.

    Forces the row to RUNNING directly rather than actually starting the
    engine, so the assertion does not race a fast offline run to
    completion before the delete call fires.
    """
    client = make_client()
    created = client.post(
        "/api/runs", headers=_OWNER, json={"research_goal": "Active run goal"}
    )
    run_id = created.json()["id"]
    store.update_run_status(run_id, store.RunStatus.RUNNING)

    response = client.delete(f"/api/runs/{run_id}", headers=_OWNER)

    assert response.status_code == 409
    assert store.run_exists(run_id)


def test_delete_unknown_run_404s() -> None:
    client = make_client()
    response = client.delete("/api/runs/does-not-exist", headers=_OWNER)
    assert response.status_code == 404


def test_another_client_cannot_delete_the_run() -> None:
    """Ownership: a non-owner gets 404, not a delete, matching AGENTS.md."""
    client = make_client()
    created = client.post(
        "/api/runs", headers=_OWNER, json={"research_goal": "Owned goal"}
    )
    run_id = created.json()["id"]

    response = client.delete(f"/api/runs/{run_id}", headers=_OTHER)

    assert response.status_code == 404
    assert store.run_exists(run_id)


def test_demo_run_cannot_be_deleted() -> None:
    """The shared demo fixture is not any one caller's data to remove."""
    client = make_client()
    demo = store.create_run(
        "Demo goal",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(client_id=store.DEMO_CLIENT_ID),
    )
    store.update_run_status(demo.id, store.RunStatus.COMPLETED)

    response = client.delete(f"/api/runs/{demo.id}", headers=_OWNER)

    assert response.status_code == 403
    assert store.run_exists(demo.id)


def test_delete_cascades_across_every_run_scoped_table(
    isolated_db: str,
) -> None:
    """The whole point of N3/N4: deleting a run empties every table it touched.

    Drives one real offline engine run to completion (real hypotheses,
    evidence, reviews, matches, citations, a report, ...), records nonzero
    row counts across the affected tables, deletes the run, and asserts
    every one of those counts is back to zero.
    """
    client = make_client()
    run_id = _run_to_completion(client, "Cascade delete goal")

    before = store.count_run_rows(run_id, db_path=isolated_db)
    # A completed run must have left real rows behind in at least the core
    # pipeline tables, or this test would trivially pass without exercising
    # the cascade at all.
    assert before["runs"] == 1
    assert before["hypotheses"] > 0
    assert before["reports"] > 0
    nonzero_tables = [t for t, n in before.items() if n > 0]
    assert len(nonzero_tables) >= 4

    response = client.delete(f"/api/runs/{run_id}", headers=_OWNER)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["counts"] == before

    after = store.count_run_rows(run_id, db_path=isolated_db)
    assert all(count == 0 for count in after.values()), after
    assert not store.run_exists(run_id)
    assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_delete_removes_the_runs_persisted_log_rows(
    isolated_db: str,
) -> None:
    """Deletion must also clear ``app_logs``, goal text included (N4).

    ``app_logs`` carries a ``run_id`` column but no foreign key to
    ``runs`` (see ``app.store.logs``), so it does not cascade away with
    the rest of the run's tables and has to be cleared explicitly. Left
    behind, a deleted run's stage narrative -- its research goal
    verbatim, mirrored from ``run_events`` by ``app.store.events`` --
    would survive a deletion whose whole purpose is to remove it.
    """
    client = make_client()
    created = client.post(
        "/api/runs",
        headers=_OWNER,
        json={"research_goal": "deletion cascade probe"},
    )
    run_id = created.json()["id"]

    append_log_row(
        isolated_db,
        "Supervisor analyzing research goal: deletion cascade probe",
        run_id=run_id,
    )
    append_log_row(
        isolated_db,
        "report research_goal=deletion cascade probe run_mode=standard",
        run_id=run_id,
    )
    # A different tenant's run-scoped row, and an app-wide row with no run
    # at all, must both survive this run's deletion untouched.
    other_run = client.post(
        "/api/runs",
        headers=_OTHER,
        json={"research_goal": "a different tenant's goal"},
    ).json()["id"]
    other_row_id = append_log_row(
        isolated_db, "other tenant's line", run_id=other_run
    )
    app_wide_row_id = append_log_row(isolated_db, "app-wide line")

    assert store.count_logs_for_run(run_id, db_path=isolated_db) == 2

    response = client.delete(f"/api/runs/{run_id}", headers=_OWNER)
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["app_logs"] == 2

    assert store.count_logs_for_run(run_id, db_path=isolated_db) == 0
    remaining = store.list_logs(db_path=isolated_db)
    assert "deletion cascade probe" not in " ".join(
        row["message"] for row in remaining
    )
    remaining_ids = {row["id"] for row in remaining}
    assert other_row_id in remaining_ids
    assert app_wide_row_id in remaining_ids


def test_delete_clears_but_does_not_remove_a_carried_document(
    isolated_db: str,
) -> None:
    """A carried document survives deletion; only its run link is cleared.

    ``staged_documents`` has no FK to ``runs`` (a document exists before
    any run does), so deleting the run must not destroy the caller's only
    copy of their own upload.
    """
    client = make_client()
    staged = client.post(
        "/api/documents",
        headers=_OWNER,
        files={
            "file": ("notes.txt", io.BytesIO(b"private notes"), "text/plain")
        },
        data={"consent": "true"},
    )
    document_id = staged.json()["id"]
    created = client.post(
        "/api/runs",
        headers=_OWNER,
        json={
            "research_goal": "Carries a document",
            "document_ids": [document_id],
        },
    )
    run_id = created.json()["id"]
    client.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)

    response = client.delete(f"/api/runs/{run_id}", headers=_OWNER)
    assert response.status_code == 200, response.text

    remaining = store.get_staged_documents([document_id], "delete-owner")
    assert len(remaining) == 1
    assert remaining[0]["run_id"] is None


def test_deleted_run_report_markdown_file_is_removed(isolated_db: str) -> None:
    client = make_client()
    run_id = _run_to_completion(client, "Report file cleanup goal")
    md_path = _reports_dir() / f"{run_id}.md"
    assert md_path.exists()

    client.delete(f"/api/runs/{run_id}", headers=_OWNER)

    assert not Path(md_path).exists()

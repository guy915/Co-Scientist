"""Tests for the account-level data export (N11): GET /api/account/export."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from tests._client import make_client, wait_for

_OWNER = {"X-Client-ID": "export-owner"}
_OTHER = {"X-Client-ID": "someone-else"}


def _wait_owned_status(
    client: TestClient, run_id: str, status: str, *, timeout: float = 30.0
) -> bool:
    """Poll ``GET /api/runs/{id}`` as ``_OWNER`` until it reaches ``status``.

    ``tests._client.wait_for_status`` only polls under the client's own
    default identity, so it cannot see a run created under a different,
    explicit ``X-Client-ID`` like this suite's.
    """

    def _reached() -> bool:
        response = client.get(f"/api/runs/{run_id}", headers=_OWNER)
        return response.status_code == 200 and bool(
            response.json().get("status") == status
        )

    return wait_for(_reached, timeout=timeout)


def test_export_includes_a_run_its_report_and_a_document(
    isolated_db: str,
) -> None:
    client = make_client()
    client.post(
        "/api/documents",
        headers=_OWNER,
        files={
            "file": ("mine.txt", io.BytesIO(b"my private notes"), "text/plain")
        },
        data={"consent": "true"},
    )
    created = client.post(
        "/api/runs",
        headers=_OWNER,
        json={"research_goal": "Export goal", "tier": "express"},
    )
    run_id = created.json()["id"]
    client.post(f"/api/runs/{run_id}/start", headers=_OWNER, json={})
    assert _wait_owned_status(client, run_id, "completed")

    response = client.get("/api/account/export", headers=_OWNER)

    assert response.status_code == 200
    payload = response.json()
    assert payload["client_id"] == "export-owner"
    run_ids = [row["id"] for row in payload["runs"]]
    assert run_id in run_ids
    exported_run = next(r for r in payload["runs"] if r["id"] == run_id)
    assert exported_run["status"] == "completed"
    assert exported_run["report_markdown"]  # a genuine finalized report
    titles = [doc["title"] for doc in payload["documents"]]
    assert "mine.txt" in titles
    document = next(d for d in payload["documents"] if d["title"] == "mine.txt")
    assert document["text"] == "my private notes"


def test_export_is_scoped_to_the_caller() -> None:
    client = make_client()
    client.post(
        "/api/runs", headers=_OWNER, json={"research_goal": "Private goal"}
    )

    other_export = client.get("/api/account/export", headers=_OTHER)

    assert other_export.status_code == 200
    assert other_export.json()["runs"] == []


def test_export_includes_feedback() -> None:
    client = make_client()
    client.post(
        "/api/feedback",
        headers=_OWNER,
        json={"message": "Own note", "category": "bug"},
    )
    client.post(
        "/api/feedback",
        headers=_OTHER,
        json={"message": "Not mine", "category": "bug"},
    )

    payload = client.get("/api/account/export", headers=_OWNER).json()

    messages = [note["message"] for note in payload["feedback"]]
    assert messages == ["Own note"]

"""Tests for permanent staged-document deletion (N3).

Covers ``DELETE /api/documents/{id}``.
"""

from __future__ import annotations

import io
from typing import Any

from fastapi.testclient import TestClient

from tests._client import make_client

_OWNER = {"X-Client-ID": "doc-delete-owner"}
_OTHER = {"X-Client-ID": "someone-else"}


def _stage(client: TestClient, headers: dict[str, str]) -> Any:
    return client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                "notes.txt",
                io.BytesIO(b"private research notes"),
                "text/plain",
            )
        },
        data={"consent": "true"},
    )


def test_owner_can_delete_their_document() -> None:
    client = make_client()
    document_id = _stage(client, _OWNER).json()["id"]

    response = client.delete(f"/api/documents/{document_id}", headers=_OWNER)

    assert response.status_code == 204
    # A deleted document can no longer be resolved for the owner.
    interview = client.post(
        "/api/interviews",
        headers=_OWNER,
        json={"research_challenge": "x", "document_ids": [document_id]},
    )
    assert interview.status_code == 404


def test_another_client_cannot_delete_the_document() -> None:
    client = make_client()
    document_id = _stage(client, _OWNER).json()["id"]

    response = client.delete(f"/api/documents/{document_id}", headers=_OTHER)

    assert response.status_code == 404
    # Still resolvable by its real owner -- nothing was deleted.
    interview = client.post(
        "/api/interviews",
        headers=_OWNER,
        json={"research_challenge": "x", "document_ids": [document_id]},
    )
    assert interview.status_code == 200


def test_delete_unknown_document_404s() -> None:
    client = make_client()
    response = client.delete(
        "/api/documents/not-a-real-document", headers=_OWNER
    )
    assert response.status_code == 404

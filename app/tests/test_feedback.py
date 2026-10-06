from __future__ import annotations

import pytest

from app.config import settings
from app.store import feedback
from tests._client import make_client, make_operator_client

PAYLOAD = {
    "category": "Bug",
    "message": "The plan did not load.",
    "diagnostics": ("=== SESSION DETAILS ===\n=== STATS ===\n=== LOGS (JSON) ===\n[]"),
    "url": "https://ai-co-scientist.com/chats/private-chat",
    "run_id": "reported-context",
}


def _submission(message: str = "A bug") -> feedback.Submission:
    return feedback.Submission("Bug", message, "diagnostic snapshot", "https://example.test/")


def test_submit_persists_context_and_account_export_is_owner_scoped(
    isolated_db: str,
) -> None:
    client = make_client()
    first = client.post("/api/feedback", json=PAYLOAD, headers={"X-Client-ID": "alice"})
    assert first.status_code == 201, first.text
    client.post(
        "/api/feedback",
        json={**PAYLOAD, "message": "Different owner"},
        headers={"X-Client-ID": "bob"},
    )
    exported = client.get("/api/account/export", headers={"X-Client-ID": "alice"}).json()[
        "feedback"
    ]
    assert len(exported) == 1
    row = exported[0]
    assert row["id"] == first.json()["id"]
    assert row["client_id"] == "alice"
    for key, value in PAYLOAD.items():
        assert row[key] == value
    assert "host_key" not in row
    assert client.get("/api/feedback/admin", headers={"X-Client-ID": "alice"}).status_code == 403


def test_admin_requires_token_independently_of_researcher_session(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    feedback.submit("alice", "host", _submission())
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "logs_admin_token", "maintainer-token")
    client = make_client()
    assert client.post("/api/feedback", json=PAYLOAD).status_code == 401
    assert make_operator_client().get("/api/feedback/admin").status_code == 403
    assert (
        client.get(
            "/api/feedback/admin",
            headers={"X-Logs-Token": "wrong", "X-Forwarded-For": "127.0.0.1"},
        ).status_code
        == 403
    )
    response = client.get("/api/feedback/admin", headers={"X-Logs-Token": "maintainer-token"})
    assert response.status_code == 200
    assert response.json()["feedback"][0]["client_id"] == "alice"
    monkeypatch.setattr(settings, "logs_admin_token", "")
    assert (
        client.get("/api/feedback/admin", headers={"X-Logs-Token": "maintainer-token"}).status_code
        == 403
    )

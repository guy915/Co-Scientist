from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import settings
from app.store import db, feedback
from tests._client import make_client, make_operator_client

PAYLOAD = {
    "category": "Bug",
    "message": "The plan did not load.",
    "diagnostics": (
        "=== SESSION DETAILS ===\n=== STATS ===\n=== LOGS (JSON) ===\n[]"
    ),
    "url": "https://ai-co-scientist.com/chats/private-chat",
    "run_id": "reported-context",
}


def _submission(message: str = "A bug") -> feedback.Submission:
    return feedback.Submission(
        "Bug", message, "diagnostic snapshot", "https://example.test/"
    )


def test_submit_persists_context_and_account_export_is_owner_scoped(
    isolated_db: str,
) -> None:
    client = make_client()
    first = client.post(
        "/api/feedback", json=PAYLOAD, headers={"X-Client-ID": "alice"}
    )
    assert first.status_code == 201, first.text
    client.post(
        "/api/feedback",
        json={**PAYLOAD, "message": "Different owner"},
        headers={"X-Client-ID": "bob"},
    )
    exported = client.get(
        "/api/account/export", headers={"X-Client-ID": "alice"}
    ).json()["feedback"]
    assert len(exported) == 1
    row = exported[0]
    assert row["id"] == first.json()["id"]
    assert row["client_id"] == "alice"
    for key, value in PAYLOAD.items():
        assert row[key] == value
    assert "host_key" not in row
    assert (
        client.get(
            "/api/feedback/admin", headers={"X-Client-ID": "alice"}
        ).status_code
        == 403
    )


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
    response = client.get(
        "/api/feedback/admin", headers={"X-Logs-Token": "maintainer-token"}
    )
    assert response.status_code == 200
    assert response.json()["feedback"][0]["client_id"] == "alice"
    monkeypatch.setattr(settings, "logs_admin_token", "")
    assert (
        client.get(
            "/api/feedback/admin", headers={"X-Logs-Token": "maintainer-token"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"message": "  "},
        {"category": "Audience"},
        {"message": "x" * 8001},
        {"diagnostics": "x" * 100001},
        {"url": "x" * 2049},
        {"run_id": "x" * 129},
    ],
)
def test_invalid_or_oversized_submission_does_not_write(
    isolated_db: str, changes: dict[str, str]
) -> None:
    response = make_client().post("/api/feedback", json={**PAYLOAD, **changes})
    assert response.status_code == 422
    assert feedback.list_feedback() == []


def test_concurrent_owner_budget_is_atomic_and_survives_retention_and_restart(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(feedback, "MAX_ROWS", 2)

    def send(_: int) -> bool:
        try:
            feedback.submit("owner", "host", _submission())
            return True
        except feedback.RateExceededError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(send, range(12)))
    assert sum(accepted) == 5
    assert len(feedback.list_feedback()) == 2
    db._initialized.discard(isolated_db)
    with pytest.raises(feedback.RateExceededError):
        feedback.submit("owner", "host", _submission())
    with db.connect() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM feedback_admissions").fetchone()[
                0
            ]
            == 5
        )


def test_host_and_global_budgets_cannot_be_rotated_with_compatibility_ids(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(feedback, "HOST_PER_MINUTE", 3)
    for n in range(3):
        feedback.submit(f"owner-{n}", "same-host", _submission())
    with pytest.raises(feedback.RateExceededError):
        feedback.submit("another-owner", "same-host", _submission())
    monkeypatch.setattr(feedback, "GLOBAL_PER_MINUTE", 3)
    with pytest.raises(feedback.RateExceededError):
        feedback.submit("fresh-owner", "fresh-host", _submission())


def test_api_rate_limit_returns_retry_after(isolated_db: str) -> None:
    client = make_client()
    for _ in range(5):
        assert client.post("/api/feedback", json=PAYLOAD).status_code == 201
    response = client.post("/api/feedback", json=PAYLOAD)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_byte_row_and_age_bounds_keep_newest_and_expire_admission_history(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [10000000.0]
    monkeypatch.setattr(db, "_now", lambda: now[0])
    monkeypatch.setattr(feedback, "MAX_BYTES", 3000)
    monkeypatch.setattr(feedback, "MAX_ROWS", 3)
    for n in range(12):
        newest = feedback.submit(
            "owner", "host", _submission("🌱" * 100 + str(n))
        )
        now[0] += 61
    rows = feedback.list_feedback()
    assert rows[0]["id"] == newest
    assert len(rows) <= 3
    with db.connect() as conn:
        assert (
            conn.execute("SELECT SUM(byte_size) FROM feedback").fetchone()[0]
            <= 3000
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM feedback_admissions").fetchone()[
                0
            ]
            == 1
        )
    now[0] += feedback.RETENTION_SECONDS + 1
    assert feedback.list_feedback() == []
    feedback.submit("owner", "host", _submission("current"))
    assert [row["message"] for row in feedback.list_feedback()] == ["current"]

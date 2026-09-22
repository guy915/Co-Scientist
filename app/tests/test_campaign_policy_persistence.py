"""Server-derived campaign policy persistence for interviews and runs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import auth, credentials, store
from app.config import Settings, settings
from tests._client import make_client
from tests._interviews_helpers import (
    InterviewFields,
    _interview_payload,
    _patch_model_sequence,
    _response,
)


def _campaign_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(settings, "auth_secret", "campaign-test-secret")
    monkeypatch.setattr(settings, "campaign_researcher_ids", {"researcher-a"})
    token = auth.create_session_token("researcher-a")
    return {"Authorization": f"Bearer {token}"}


def test_campaign_researcher_setting_normalizes_and_rejects_empty_ids() -> None:
    configured = Settings(
        _env_file=None,
        campaign_researcher_ids={" researcher-a ", "researcher-b"},
    )
    assert configured.campaign_researcher_ids == {
        "researcher-a",
        "researcher-b",
    }

    with pytest.raises(ValidationError):
        Settings(_env_file=None, campaign_researcher_ids={"researcher-a", " "})


def test_legacy_rows_migrate_to_standard_policy(isolated_db: str) -> None:
    """Rows created before the policy columns retain ordinary behavior."""
    run = store.create_run(
        "Legacy run",
        "standard",
        "mock",
        {},
        store.RunCreateOptions(client_id="legacy", db_path=isolated_db),
    )
    interview = store.create_interview(
        "legacy", "Legacy interview", db_path=isolated_db
    )

    from app.store.db_migrations import _run_migrations

    with store.connect(isolated_db) as conn:
        conn.execute("ALTER TABLE runs DROP COLUMN execution_policy")
        conn.execute("ALTER TABLE interviews DROP COLUMN execution_policy")
        _run_migrations(conn)

    migrated_run = store.get_run(run.id, db_path=isolated_db)
    migrated_interview = store.get_interview(
        interview["id"], db_path=isolated_db
    )
    assert migrated_run is not None
    assert migrated_run.execution_policy == "standard"
    assert migrated_interview is not None
    assert migrated_interview["execution_policy"] == "standard"


def test_campaign_interview_survives_restart_and_cannot_downgrade_linked_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The campaign marker survives allowlist removal and a fresh connection."""
    headers = _campaign_headers(monkeypatch)
    _patch_model_sequence(
        monkeypatch,
        [_response("What should the study prioritize?")],
    )
    client = make_client()

    created = client.post(
        "/api/interviews",
        headers=headers,
        json={"research_challenge": "Map treatment resistance"},
    )
    interview = _interview_payload(created)
    assert interview["execution_policy"] == "campaign"

    store.update_interview(
        interview["id"],
        {
            **interview["fields"],
            "title": "Treatment resistance",
        },
        None,
        completed=True,
    )
    monkeypatch.setattr(settings, "campaign_researcher_ids", set())

    # A fresh connection/process initialization must read the durable marker,
    # not re-derive it from the now-changed deployment allowlist.
    from app.store import db as store_db

    store_db._initialized.discard(isolated_db)
    resumed = make_client().get(
        f"/api/interviews/{interview['id']}", headers=headers
    )
    assert resumed.json()["execution_policy"] == "campaign"

    run = make_client().post(
        "/api/runs",
        headers=headers,
        json={
            "research_goal": "client placeholder",
            "interview_id": interview["id"],
            "execution_policy": "standard",
        },
    )
    assert run.status_code == 200
    assert run.json()["execution_policy"] == "campaign"
    assert store.get_run(run.json()["id"]).execution_policy == "campaign"


def test_unsigned_identity_and_body_cannot_originate_campaign(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compatibility identity and body policy fields remain standard."""
    monkeypatch.setattr(settings, "campaign_researcher_ids", {"researcher-a"})
    _patch_model_sequence(
        monkeypatch,
        [_response("What should the study prioritize?", InterviewFields())],
    )
    headers = {"X-Client-ID": "researcher-a"}
    client = make_client()

    interview_response = client.post(
        "/api/interviews",
        headers=headers,
        json={
            "research_challenge": "Map treatment resistance",
            "execution_policy": "campaign",
        },
    )
    interview = _interview_payload(interview_response)
    assert interview["execution_policy"] == "standard"

    run = client.post(
        "/api/runs",
        headers=headers,
        json={
            "research_goal": "Map treatment resistance",
            "execution_policy": "campaign",
        },
    )
    assert run.status_code == 200
    assert run.json()["execution_policy"] == "standard"


async def test_campaign_run_rejects_byok_before_transport(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A campaign request never probes a caller-supplied paid credential."""
    headers = {
        **_campaign_headers(monkeypatch),
        "X-LLM-Provider": "openai",
        "X-LLM-API-Key": "paid-key",
    }
    monkeypatch.setattr(settings, "byok_encryption_key", "encrypt-test")
    called = False

    async def _unexpected_validation(
        _credential: credentials.ByokCredential,
    ) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        credentials, "validate_byok_credential", _unexpected_validation
    )

    interview_response = make_client().post(
        "/api/interviews",
        headers=headers,
        json={"research_challenge": "Map treatment resistance"},
    )
    assert interview_response.status_code == 400
    assert "campaign" in interview_response.json()["detail"].lower()
    assert store.list_interviews("researcher-a") == []

    response = make_client().post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Map treatment resistance"},
    )

    assert response.status_code == 400
    assert "campaign" in response.json()["detail"].lower()
    assert called is False
    assert store.list_runs(client_id="researcher-a") == []

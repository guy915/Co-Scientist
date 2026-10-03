from __future__ import annotations

from typing import Any

import pytest

from app import store
from app.config import settings
from app.store import RunStatus
from tests._client import make_client
from tests._outcome_refinement_api_support import (
    _add_hypothesis,
    _new_run,
    _outcome_body,
    _signed_headers,
)


@pytest.fixture(autouse=True)
def _configure_outcome_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-test-secret")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)


def test_researcher_records_outcome_and_reads_it_after_restart(
    isolated_db: str,
) -> None:
    owner = "outcome-researcher"
    headers = _signed_headers(owner)
    client = make_client()
    run_id = _new_run(client, owner)
    hypothesis_id = _add_hypothesis(
        run_id, isolated_db, "Treatment reduces growth"
    )
    evidence_id = store.add_evidence(
        store.NewEvidence(run_id=run_id, title="Assay protocol"),
        db_path=isolated_db,
    )
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=isolated_db)

    hypothesis_before = next(
        row
        for row in client.get(
            f"/api/runs/{run_id}/hypotheses", headers=headers
        ).json()["hypotheses"]
        if row["id"] == hypothesis_id
    )
    reviews_before = client.get(
        f"/api/runs/{run_id}/reviews", headers=headers
    ).json()["reviews"]
    messages_before = client.get(
        f"/api/runs/{run_id}/messages", headers=headers
    ).json()["messages"]
    claims_before = client.get(
        f"/api/runs/{run_id}/claim-evidence", headers=headers
    ).json()["claim_evidence"]
    request_body = _outcome_body(evidence_id)
    spoofed_body = {**request_body, "author": "another-researcher"}

    created = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=headers,
        json=spoofed_body,
    )
    assert created.status_code == 201
    outcome = created.json()
    hypothesis_snapshot = {
        "title": "Treatment reduces growth",
        "statement": "Treatment reduces growth by pathway Y.",
    }
    evidence_snapshot = [
        {
            "id": evidence_id,
            "title": "Assay protocol",
            "source": "mock",
            "url": "",
            "doi": None,
            "pmid": None,
            "sha256": None,
        }
    ]
    assert outcome == {
        "id": outcome["id"],
        "run_id": run_id,
        "hypothesis_id": hypothesis_id,
        **request_body,
        "hypothesis_snapshot": hypothesis_snapshot,
        "referenced_evidence": evidence_snapshot,
        "author": owner,
        "recorded_at": outcome["recorded_at"],
    }
    second_body = {
        **request_body,
        "measured_observation": "A repeat assay showed a 20% reduction.",
    }
    second = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=headers,
        json=second_body,
    )
    assert second.status_code == 201
    assert second.json()["id"] != outcome["id"]
    outcome_path = f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes"
    assert (
        client.put(outcome_path, headers=headers, json=request_body).status_code
        == 405
    )
    assert client.delete(outcome_path, headers=headers).status_code == 405

    replay = client.get(
        f"/api/runs/{run_id}/events?stream=false", headers=headers
    ).json()["events"]
    outcome_events = [
        event for event in replay if event["type"] == "scientist.outcome"
    ]
    assert len(outcome_events) == 2
    assert {event["payload"]["outcome_id"] for event in outcome_events} == {
        outcome["id"],
        second.json()["id"],
    }
    for event in outcome_events:
        payload = event["payload"]
        assert set(payload) <= {
            "outcome_id",
            "hypothesis_id",
            "author",
            "recorded_at",
            "activity",
        }
        assert payload["hypothesis_id"] == hypothesis_id
        assert payload["author"] == owner
        assert request_body["measured_observation"] not in str(payload)
        assert second_body["measured_observation"] not in str(payload)

    client.close()

    from app.store import db as store_db

    store_db._initialized.discard(isolated_db)
    reopened_client = make_client()
    listed = reopened_client.get(
        f"/api/runs/{run_id}/outcomes", headers=headers
    )
    assert listed.status_code == 200
    second_outcome = second.json()
    assert listed.json()["outcomes"] == [
        outcome,
        {
            "id": second_outcome["id"],
            "run_id": run_id,
            "hypothesis_id": hypothesis_id,
            **second_body,
            "hypothesis_snapshot": hypothesis_snapshot,
            "referenced_evidence": evidence_snapshot,
            "author": owner,
            "recorded_at": second_outcome["recorded_at"],
        },
    ]

    hypothesis_after = next(
        row
        for row in reopened_client.get(
            f"/api/runs/{run_id}/hypotheses", headers=headers
        ).json()["hypotheses"]
        if row["id"] == hypothesis_id
    )
    assert hypothesis_after["elo_rating"] == hypothesis_before["elo_rating"]
    assert (
        reopened_client.get(
            f"/api/runs/{run_id}/reviews", headers=headers
        ).json()["reviews"]
        == reviews_before
    )
    assert (
        reopened_client.get(
            f"/api/runs/{run_id}/messages", headers=headers
        ).json()["messages"]
        == messages_before
    )
    assert (
        reopened_client.get(
            f"/api/runs/{run_id}/claim-evidence", headers=headers
        ).json()["claim_evidence"]
        == claims_before
    )
    reopened_client.close()


def test_outcomes_hide_unowned_runs_and_hypotheses(isolated_db: str) -> None:
    owner = "outcome-owner"
    other_owner = "other-researcher"
    client = make_client()
    owned_run = _new_run(client, owner)
    other_run = _new_run(client, other_owner)
    owned_hypothesis = _add_hypothesis(
        owned_run, isolated_db, "Owned hypothesis"
    )
    foreign_hypothesis = _add_hypothesis(
        other_run, isolated_db, "Foreign hypothesis"
    )

    assert (
        client.get(
            f"/api/runs/{owned_run}/outcomes",
            headers=_signed_headers(other_owner),
        ).status_code
        == 404
    )
    denied_run_post = client.post(
        f"/api/runs/{owned_run}/hypotheses/{owned_hypothesis}/outcomes",
        headers=_signed_headers(other_owner),
        json=_outcome_body(),
    )
    assert denied_run_post.status_code == 404

    denied_hypothesis_post = client.post(
        f"/api/runs/{owned_run}/hypotheses/{foreign_hypothesis}/outcomes",
        headers=_signed_headers(owner),
        json=_outcome_body(),
    )
    assert denied_hypothesis_post.status_code == 404
    assert client.get(
        f"/api/runs/{owned_run}/outcomes", headers=_signed_headers(owner)
    ).json() == {"outcomes": []}
    client.close()


def test_compatibility_identity_cannot_read_or_write_private_outcomes(
    isolated_db: str,
) -> None:
    owner = "known-private-owner"
    client = make_client()
    run_id = _new_run(client, owner)
    hypothesis_id = _add_hypothesis(run_id, isolated_db, "Private hypothesis")
    signed = _signed_headers(owner)
    created = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=signed,
        json=_outcome_body(),
    )
    assert created.status_code == 201

    spoofed = {"X-Client-ID": owner}
    read = client.get(f"/api/runs/{run_id}/outcomes", headers=spoofed)
    write = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=spoofed,
        json=_outcome_body(),
    )
    invalid_bearer = client.get(
        f"/api/runs/{run_id}/outcomes",
        headers={**spoofed, "Authorization": "Bearer invalid"},
    )
    assert (
        read.status_code,
        write.status_code,
        invalid_bearer.status_code,
    ) == (401, 401, 401)
    client.close()


def test_demo_outcomes_are_publicly_readable_and_not_writable(
    isolated_db: str,
) -> None:
    demo = store.create_run(
        "Public demo outcome",
        "standard",
        "engine",
        {},
        options=store.RunCreateOptions(
            client_id=store.DEMO_CLIENT_ID, db_path=isolated_db
        ),
    )
    hypothesis_id = _add_hypothesis(demo.id, isolated_db, "Demo hypothesis")
    client = make_client()
    read = client.get(f"/api/runs/{demo.id}/outcomes")
    write = client.post(
        f"/api/runs/{demo.id}/hypotheses/{hypothesis_id}/outcomes",
        headers=_signed_headers("researcher"),
        json=_outcome_body(),
    )
    assert read.status_code == 200
    assert read.json() == {"outcomes": []}
    assert write.status_code == 404
    client.close()


def test_outcome_rejects_evidence_from_another_run(isolated_db: str) -> None:
    owner = "same-researcher"
    headers = _signed_headers(owner)
    client = make_client()
    run_id = _new_run(client, owner)
    other_run = _new_run(client, owner)
    hypothesis_id = _add_hypothesis(run_id, isolated_db, "Owned hypothesis")
    foreign_evidence_id = store.add_evidence(
        store.NewEvidence(run_id=other_run, title="Private other-run evidence"),
        db_path=isolated_db,
    )

    rejected = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=headers,
        json=_outcome_body(foreign_evidence_id),
    )
    assert rejected.status_code == 404
    assert foreign_evidence_id not in rejected.text
    assert client.get(
        f"/api/runs/{run_id}/outcomes", headers=headers
    ).json() == {"outcomes": []}
    client.close()


def test_outcome_text_is_bounded(isolated_db: str) -> None:
    owner = "bounded-researcher"
    headers = _signed_headers(owner)
    client = make_client()
    run_id = _new_run(client, owner)
    hypothesis_id = _add_hypothesis(run_id, isolated_db, "Bounded hypothesis")
    body = _outcome_body()
    body["measured_observation"] = "x" * 10_001

    rejected = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=headers,
        json=body,
    )
    assert rejected.status_code == 422
    assert client.get(
        f"/api/runs/{run_id}/outcomes", headers=headers
    ).json() == {"outcomes": []}
    client.close()


@pytest.mark.parametrize(
    ("clearer", "clears_events"),
    [
        (store.clear_publication_artifacts, False),
        (store.clear_run_derived_data, True),
    ],
    ids=["publication-replay", "legacy-resume"],
)
def test_outcomes_and_audit_events_survive_agent_cleanup(
    isolated_db: str,
    clearer: Any,
    clears_events: bool,
) -> None:
    owner = "durable-outcome-researcher"
    headers = _signed_headers(owner)
    client = make_client()
    run_id = _new_run(client, owner)
    hypothesis_id = _add_hypothesis(
        run_id, isolated_db, "Agent hypothesis to test"
    )
    evidence_id = store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title="Retrieved assay paper",
            source="pubmed",
            url="https://example.test/paper",
            doi="10.5555/outcome",
            pmid="12345",
            sha256="a" * 64,
            abstract="This private evidence text must not be snapshotted.",
        ),
        db_path=isolated_db,
    )
    body = _outcome_body(evidence_id)
    created = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=headers,
        json=body,
    )
    assert created.status_code == 201
    outcome = created.json()
    original_events = store.list_events(run_id, db_path=isolated_db)
    original_outcome_event = next(
        event
        for event in original_events
        if event["type"] == "scientist.outcome"
    )
    original_high_water = store.latest_event_seq(run_id, db_path=isolated_db)

    if clears_events:
        store.save_checkpoint(
            run_id,
            store.NewCheckpoint(
                stage="resume-test",
                schema_version=1,
                last_event_seq=original_high_water,
                state={},
            ),
            db_path=isolated_db,
        )
    clearer(run_id, db_path=isolated_db)

    outcomes = client.get(
        f"/api/runs/{run_id}/outcomes", headers=headers
    ).json()["outcomes"]
    assert outcomes == [outcome]
    assert outcome["hypothesis_snapshot"] == {
        "title": "Agent hypothesis to test",
        "statement": "Agent hypothesis to test by pathway Y.",
    }
    assert outcome["referenced_evidence"] == [
        {
            "id": evidence_id,
            "title": "Retrieved assay paper",
            "source": "pubmed",
            "url": "https://example.test/paper",
            "doi": "10.5555/outcome",
            "pmid": "12345",
            "sha256": "a" * 64,
        }
    ]
    assert evidence_id not in [row["id"] for row in store.list_evidence(run_id)]
    assert hypothesis_id not in [
        row["id"] for row in store.list_hypotheses(run_id)
    ]

    replayed = client.get(
        f"/api/runs/{run_id}/events?stream=false", headers=headers
    ).json()["events"]
    outcome_events = [
        event for event in replayed if event["type"] == "scientist.outcome"
    ]
    assert len(outcome_events) == 1
    outcome_event = outcome_events[0]
    assert outcome_event["payload"]["outcome_id"] == outcome["id"]
    assert outcome_event["payload"]["hypothesis_id"] == hypothesis_id
    assert "measured_observation" not in outcome_event["payload"]
    assert outcome_event == original_outcome_event

    next_seq = store.append_event(
        run_id, "status", {"status": "still-ordered"}, db_path=isolated_db
    )
    assert next_seq > outcome_event["seq"]
    client.close()

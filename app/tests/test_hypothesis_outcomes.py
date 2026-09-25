"""Public API tests for append-only researcher-measured outcomes."""

from __future__ import annotations

from typing import Any, cast

import pytest
from co_scientist.checkpoint import serialize_workflow_state
from co_scientist.models import Hypothesis

from app import auth, store
from app.config import settings
from app.store import RunStatus
from tests._client import make_client


@pytest.fixture(autouse=True)
def _configure_outcome_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-test-secret")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)


def _signed_headers(owner: str) -> dict[str, str]:
    token = auth.create_session_token(owner)
    return {"Authorization": f"Bearer {token}"}


def _outcome_body(evidence_id: str | None = None) -> dict[str, Any]:
    return {
        "method_protocol": "24-hour viability assay",
        "conditions": "10 micromolar treatment X, n=4",
        "measured_observation": "Mean growth was 18% lower than vehicle.",
        "units": "%",
        "controls": "Vehicle-treated cells",
        "interpretation": "The result is consistent with the proposed effect.",
        "referenced_evidence_ids": [evidence_id] if evidence_id else [],
    }


def _add_hypothesis(run_id: str, db_path: str, title: str) -> str:
    return store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title=title,
            statement=f"{title} by pathway Y.",
        ),
        db_path=db_path,
    )


def _new_run(client: Any, owner: str) -> str:
    response = client.post(
        "/api/runs",
        headers=_signed_headers(owner),
        json={"research_goal": "Measure the proposed effect"},
    )
    assert response.status_code == 200
    return str(response.json()["id"])


def _save_engine_checkpoint(
    run_id: str,
    hypothesis: Hypothesis,
    db_path: str,
) -> None:
    event_seq = store.latest_event_seq(run_id, db_path=db_path)
    envelope = serialize_workflow_state(
        {"hypotheses": [hypothesis]},
        last_event_seq=event_seq,
    )
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="completed",
            schema_version=1,
            last_event_seq=event_seq,
            state={"provider": "engine", **envelope},
        ),
        db_path=db_path,
    )


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


def test_owner_can_create_one_durable_targeted_outcome_intent(
    isolated_db: str,
) -> None:
    owner = "outcome-refinement-owner"
    headers = {
        **_signed_headers(owner),
        "Idempotency-Key": "refine-meselson-1",
    }
    client = make_client()
    run_id = _new_run(client, owner)
    statement = "Treatment X by pathway Y."
    hypothesis_id = _add_hypothesis(run_id, isolated_db, "Treatment X")
    evidence_id = store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title="Assay protocol",
            source="pubmed",
            url="https://example.test/protocol",
            doi="10.5555/protocol",
            abstract="This full text is not part of the refinement context.",
        ),
        db_path=isolated_db,
    )
    outcome_response = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=headers,
        json=_outcome_body(evidence_id),
    )
    assert outcome_response.status_code == 201
    outcome_id = outcome_response.json()["id"]
    assert (
        store.list_pending_outcome_refinement_actions(
            run_id, db_path=isolated_db
        )
        == []
    )
    assert store.list_tasks(run_id, db_path=isolated_db) == []
    _save_engine_checkpoint(
        run_id,
        Hypothesis(
            id=hypothesis_id,
            text=statement,
            title="Treatment reduces growth",
        ),
        isolated_db,
    )
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=isolated_db)

    action_path = (
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/"
        f"outcomes/{outcome_id}/refine"
    )
    created = client.post(action_path, headers=headers)
    assert created.status_code == 202
    action = created.json()
    assert action["status"] == "queued"
    assert action["outcome_id"] == outcome_id
    assert action["hypothesis_id"] == hypothesis_id
    assert action["action_id"]
    assert action["task_idempotency_key"] == (
        f"outcome-refinement:{action['action_id']}"
    )

    persisted = store.get_outcome_refinement_action(
        run_id, action["action_id"], db_path=isolated_db
    )
    assert persisted is not None
    context = persisted["context_snapshot"]
    assert len(context) <= 6_000
    assert statement in context
    assert _outcome_body(evidence_id)["measured_observation"] in context
    assert evidence_id in context
    assert "This full text is not part" not in context
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert len(tasks) == 1
    assert tasks[0].task_type == "engine.outcome.refinement"
    assert tasks[0].idempotency_key == action["task_idempotency_key"]
    assert tasks[0].provenance == {
        "action_id": action["action_id"],
        "outcome_id": outcome_id,
        "hypothesis_id": hypothesis_id,
    }

    replayed = client.post(action_path, headers=headers)
    assert replayed.status_code == 202
    assert replayed.json() == {**action, "replayed": True}
    assert (
        store.list_pending_outcome_refinement_actions(
            run_id, db_path=isolated_db
        )
        == []
    )
    events = store.list_events(run_id, db_path=isolated_db)
    action_events = [
        event
        for event in events
        if event["type"] == "scientist.outcome_refinement_requested"
    ]
    assert len(action_events) == 1
    assert action_events[0]["payload"]["action_id"] == action["action_id"]
    assert _outcome_body(evidence_id)["measured_observation"] not in str(
        action_events[0]["payload"]
    )
    client.close()
    from app.store import db as store_db

    store_db._initialized.discard(isolated_db)
    reopened_client = make_client()
    replay_after_restart = reopened_client.post(action_path, headers=headers)
    assert replay_after_restart.status_code == 202
    assert replay_after_restart.json() == {**action, "replayed": True}
    assert (
        store.list_pending_outcome_refinement_actions(
            run_id, db_path=isolated_db
        )
        == []
    )
    assert len(store.list_events(run_id, db_path=isolated_db)) == len(events)
    reopened_client.close()


def test_refinement_action_is_owner_scoped_and_exactly_one_per_outcome(
    isolated_db: str,
) -> None:
    owner = "outcome-refinement-owner"
    other_owner = "different-outcome-owner"
    client = make_client()
    run_id = _new_run(client, owner)
    parent_id = _add_hypothesis(run_id, isolated_db, "Target parent")
    sibling_id = _add_hypothesis(run_id, isolated_db, "Different sibling")
    body = _outcome_body()
    outcome = store.add_hypothesis_outcome(
        store.NewHypothesisOutcome(
            run_id=run_id,
            hypothesis_id=parent_id,
            method_protocol=body["method_protocol"],
            conditions=body["conditions"],
            measured_observation=body["measured_observation"],
            units=body["units"],
            controls=body["controls"],
            interpretation=body["interpretation"],
            referenced_evidence_ids=[],
            author=owner,
        ),
        db_path=isolated_db,
    )
    _save_engine_checkpoint(
        run_id,
        Hypothesis(
            id=parent_id,
            text="Target parent by pathway Y.",
            title="Target parent",
        ),
        isolated_db,
    )
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=isolated_db)
    action_path = (
        f"/api/runs/{run_id}/hypotheses/{parent_id}/"
        f"outcomes/{outcome['id']}/refine"
    )
    owner_headers = {
        **_signed_headers(owner),
        "Idempotency-Key": "outcome-parent-action",
    }

    assert (
        client.post(
            action_path,
            headers={
                "X-Client-ID": owner,
                "Idempotency-Key": "unauthenticated-action",
            },
        ).status_code
        == 401
    )
    assert (
        client.post(
            action_path,
            headers={
                **_signed_headers(other_owner),
                "Idempotency-Key": "foreign-owner-action",
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/runs/{run_id}/hypotheses/{sibling_id}/"
            f"outcomes/{outcome['id']}/refine",
            headers=owner_headers,
        ).status_code
        == 404
    )

    created = client.post(action_path, headers=owner_headers)
    assert created.status_code == 202
    second_outcome = client.post(
        f"/api/runs/{run_id}/hypotheses/{parent_id}/outcomes",
        headers=owner_headers,
        json=body,
    )
    assert second_outcome.status_code == 201
    assert (
        client.post(
            f"/api/runs/{run_id}/hypotheses/{parent_id}/"
            f"outcomes/{second_outcome.json()['id']}/refine",
            headers=owner_headers,
        ).status_code
        == 409
    )
    assert (
        client.post(
            action_path,
            headers={
                **_signed_headers(owner),
                "Idempotency-Key": "a-second-key-for-the-same-outcome",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/runs/{run_id}/hypotheses/{sibling_id}/"
            f"outcomes/{outcome['id']}/refine",
            headers=owner_headers,
        ).status_code
        == 404
    )
    action = store.get_outcome_refinement_action_for_outcome(
        run_id, outcome["id"], db_path=isolated_db
    )
    assert action is not None and action["status"] == "queued"
    client.close()


def test_refinement_requires_completed_engine_checkpoint_and_eligible_parent(
    isolated_db: str,
) -> None:
    owner = "outcome-refinement-eligibility"
    client = make_client()
    run_id = _new_run(client, owner)
    hypothesis_id = _add_hypothesis(run_id, isolated_db, "Ineligible parent")
    body = _outcome_body()
    outcome = store.add_hypothesis_outcome(
        store.NewHypothesisOutcome(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            method_protocol=body["method_protocol"],
            conditions=body["conditions"],
            measured_observation=body["measured_observation"],
            units=body["units"],
            controls=body["controls"],
            interpretation=body["interpretation"],
            referenced_evidence_ids=[],
            author=owner,
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=isolated_db)
    action_path = (
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/"
        f"outcomes/{outcome['id']}/refine"
    )
    headers = {
        **_signed_headers(owner),
        "Idempotency-Key": "missing-checkpoint-action",
    }
    assert client.post(action_path, headers=headers).status_code == 409

    _save_engine_checkpoint(
        run_id,
        Hypothesis(
            id=hypothesis_id,
            text="Ineligible parent by pathway Y.",
            title="Ineligible parent",
        ),
        isolated_db,
    )
    store.update_run_status(run_id, RunStatus.RUNNING, db_path=isolated_db)
    assert (
        client.post(
            action_path,
            headers={**headers, "Idempotency-Key": "running-run-action"},
        ).status_code
        == 409
    )
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=isolated_db)

    _save_engine_checkpoint(
        run_id,
        Hypothesis(
            id=hypothesis_id,
            text="Ineligible parent by pathway Y.",
            title="Ineligible parent",
            review_disposition="unsafe",
        ),
        isolated_db,
    )
    rejected_parent = client.post(
        action_path,
        headers={**headers, "Idempotency-Key": "blocked-parent-action"},
    )
    assert rejected_parent.status_code == 409
    assert (
        store.list_pending_outcome_refinement_actions(
            run_id, db_path=isolated_db
        )
        == []
    )
    client.close()


def test_refinement_rejects_demo_and_non_engine_runs(
    isolated_db: str,
) -> None:
    owner = "outcome-refinement-run-eligibility"
    demo = store.create_run(
        "Demo outcome refinement",
        "standard",
        "engine",
        {},
        options=store.RunCreateOptions(
            client_id=store.DEMO_CLIENT_ID,
            db_path=isolated_db,
        ),
    )
    demo_hypothesis = _add_hypothesis(demo.id, isolated_db, "Demo parent")
    demo_outcome = store.add_hypothesis_outcome(
        store.NewHypothesisOutcome(
            run_id=demo.id,
            hypothesis_id=demo_hypothesis,
            method_protocol="Protocol",
            conditions="Conditions",
            measured_observation="Observation",
            units=None,
            controls="Controls",
            interpretation="Interpretation",
            referenced_evidence_ids=[],
            author=owner,
        ),
        db_path=isolated_db,
    )
    _save_engine_checkpoint(
        demo.id,
        Hypothesis(
            id=demo_hypothesis,
            text="Demo parent by pathway Y.",
            title="Demo parent",
        ),
        isolated_db,
    )
    store.update_run_status(demo.id, RunStatus.COMPLETED, db_path=isolated_db)

    mock = store.create_run(
        "Mock outcome refinement",
        "standard",
        "mock",
        {},
        options=store.RunCreateOptions(client_id=owner, db_path=isolated_db),
    )
    mock_hypothesis = _add_hypothesis(mock.id, isolated_db, "Mock parent")
    mock_outcome = store.add_hypothesis_outcome(
        store.NewHypothesisOutcome(
            run_id=mock.id,
            hypothesis_id=mock_hypothesis,
            method_protocol="Protocol",
            conditions="Conditions",
            measured_observation="Observation",
            units=None,
            controls="Controls",
            interpretation="Interpretation",
            referenced_evidence_ids=[],
            author=owner,
        ),
        db_path=isolated_db,
    )
    store.update_run_status(mock.id, RunStatus.COMPLETED, db_path=isolated_db)

    client = make_client()
    demo_action = client.post(
        f"/api/runs/{demo.id}/hypotheses/{demo_hypothesis}/"
        f"outcomes/{demo_outcome['id']}/refine",
        headers={
            **_signed_headers(owner),
            "Idempotency-Key": "demo-action",
        },
    )
    mock_action = client.post(
        f"/api/runs/{mock.id}/hypotheses/{mock_hypothesis}/"
        f"outcomes/{mock_outcome['id']}/refine",
        headers={
            **_signed_headers(owner),
            "Idempotency-Key": "mock-action",
        },
    )
    assert demo_action.status_code == 404
    assert mock_action.status_code == 409
    assert (
        store.list_pending_outcome_refinement_actions(
            demo.id, db_path=isolated_db
        )
        == []
    )
    assert (
        store.list_pending_outcome_refinement_actions(
            mock.id, db_path=isolated_db
        )
        == []
    )
    client.close()


def test_refinement_rejects_more_than_three_source_metadata_links(
    isolated_db: str,
) -> None:
    owner = "outcome-refinement-sources"
    headers = _signed_headers(owner)
    client = make_client()
    run_id = _new_run(client, owner)
    hypothesis_id = _add_hypothesis(run_id, isolated_db, "Source-linked parent")
    evidence_ids = [
        store.add_evidence(
            store.NewEvidence(run_id=run_id, title=f"Source {index}"),
            db_path=isolated_db,
        )
        for index in range(4)
    ]
    outcome = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=headers,
        json={**_outcome_body(), "referenced_evidence_ids": evidence_ids},
    )
    assert outcome.status_code == 201
    _save_engine_checkpoint(
        run_id,
        Hypothesis(
            id=hypothesis_id,
            text="Source-linked parent by pathway Y.",
            title="Source-linked parent",
        ),
        isolated_db,
    )
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=isolated_db)
    action = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/"
        f"outcomes/{outcome.json()['id']}/refine",
        headers={**headers, "Idempotency-Key": "too-many-sources"},
    )
    assert action.status_code == 422
    assert (
        store.list_pending_outcome_refinement_actions(
            run_id, db_path=isolated_db
        )
        == []
    )
    client.close()


def test_refinement_context_uses_unicode_codepoints_and_rejects_6001(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.store import outcomes as outcomes_module

    monkeypatch.setattr(outcomes_module, "_now", lambda: 1_800_000_000.125)
    owner = "outcome-refinement-context"
    headers = _signed_headers(owner)
    statement = "Bounded parent by pathway Y."
    client = make_client()

    def refine(observation: str, key: str) -> tuple[int, int]:
        run_id = _new_run(client, owner)
        hypothesis_id = _add_hypothesis(run_id, isolated_db, "Bounded parent")
        _save_engine_checkpoint(
            run_id,
            Hypothesis(
                id=hypothesis_id,
                text=statement,
                title="Bounded parent",
            ),
            isolated_db,
        )
        store.update_run_status(
            run_id, RunStatus.COMPLETED, db_path=isolated_db
        )
        response = client.post(
            f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
            headers=headers,
            json={
                **_outcome_body(),
                "measured_observation": observation,
                "referenced_evidence_ids": [],
            },
        )
        assert response.status_code == 201
        outcome = cast(dict[str, Any], response.json())
        action_response = client.post(
            f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/"
            f"outcomes/{outcome['id']}/refine",
            headers={**headers, "Idempotency-Key": key},
        )
        return action_response.status_code, int(
            action_response.json().get("context_codepoints", 0)
        )

    calibration_status, baseline_length = refine("🧬", "unicode-calibration")
    assert calibration_status == 202
    exact_length_observation = "🧬" * (6_000 - baseline_length + 1)
    exact_status, exact_length = refine(
        exact_length_observation, "unicode-exact-boundary"
    )
    assert exact_status == 202
    assert exact_length == 6_000

    oversized_status, _ = refine(
        exact_length_observation + "🧬", "unicode-over-boundary"
    )
    assert oversized_status == 422
    client.close()


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

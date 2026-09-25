"""Owned, durable outcome-refinement API acceptance tests."""

from __future__ import annotations

import pytest
from co_scientist.models import Hypothesis

from app import store
from app.config import settings
from app.store import RunStatus
from tests._client import make_client
from tests._outcome_refinement_api_support import (
    MESELSON_STAHL_PARENT_TEXT,
    _add_hypothesis,
    _add_meselson_stahl_fixture,
    _new_run,
    _outcome_body,
    _save_engine_checkpoint,
    _signed_headers,
)


@pytest.fixture(autouse=True)
def _configure_outcome_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-test-secret")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)


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
    hypothesis_id, outcome_fields, source_ids = _add_meselson_stahl_fixture(
        run_id, isolated_db
    )
    outcome_response = client.post(
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes",
        headers=_signed_headers(owner),
        json=outcome_fields,
    )
    assert outcome_response.status_code == 201
    outcome = outcome_response.json()
    outcome_id = outcome["id"]
    assert outcome["author"] == owner
    assert outcome["referenced_evidence_ids"] == source_ids
    for field, value in outcome_fields.items():
        assert outcome[field] == value
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
            text=MESELSON_STAHL_PARENT_TEXT,
            title="Semiconservative DNA replication in E. coli",
        ),
        isolated_db,
    )
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=isolated_db)

    action_path = (
        f"/api/runs/{run_id}/hypotheses/{hypothesis_id}/"
        f"outcomes/{outcome_id}/refine"
    )
    assert client.get(action_path, headers=headers).status_code == 404
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
    assert client.get(action_path, headers=headers).json() == {
        **action,
        "replayed": True,
    }

    persisted = store.get_outcome_refinement_action(
        run_id, action["action_id"], db_path=isolated_db
    )
    assert persisted is not None
    context = persisted["context_snapshot"]
    assert len(context) <= 6_000
    assert MESELSON_STAHL_PARENT_TEXT in context
    assert outcome_fields["measured_observation"] in context
    assert outcome_fields["interpretation"] in context
    assert all(evidence_id in context for evidence_id in source_ids)
    assert "10.1073/pnas.44.7.671" in context
    assert "16590258" in context
    assert "PMC528642" in context
    assert "Hanawalt's historical account" in context
    assert "PMC539797" in context
    assert context.index(
        "The replication of DNA in Escherichia coli"
    ) < context.index("Hanawalt's historical account")
    assert "Full text and abstracts are outside" not in context
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
    assert outcome_fields["measured_observation"] not in str(
        action_events[0]["payload"]
    )
    client.close()
    from app.store import db as store_db

    store_db._initialized.discard(isolated_db)
    reopened_client = make_client()
    assert reopened_client.get(action_path, headers=headers).json() == {
        **action,
        "replayed": True,
    }
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
    parent_id, body, _ = _add_meselson_stahl_fixture(run_id, isolated_db)
    sibling_id = _add_hypothesis(run_id, isolated_db, "Different sibling")
    recorded = client.post(
        f"/api/runs/{run_id}/hypotheses/{parent_id}/outcomes",
        headers=_signed_headers(owner),
        json=body,
    )
    assert recorded.status_code == 201
    outcome = recorded.json()
    _save_engine_checkpoint(
        run_id,
        Hypothesis(
            id=parent_id,
            text=MESELSON_STAHL_PARENT_TEXT,
            title="Semiconservative DNA replication in E. coli",
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
    assert (
        client.get(
            action_path, headers=_signed_headers(other_owner)
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/runs/{run_id}/hypotheses/{sibling_id}/"
            f"outcomes/{outcome['id']}/refine",
            headers=owner_headers,
        ).status_code
        == 404
    )
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

"""Outcome-refinement eligibility and request-boundary acceptance tests."""

from __future__ import annotations

from typing import Any, cast

import pytest
from co_scientist.models import Hypothesis

from app import store
from app.config import settings
from app.store import RunStatus
from tests._client import make_client
from tests._outcome_refinement_api_support import (
    _add_hypothesis,
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

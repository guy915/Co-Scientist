"""Shared setup for outcome API and refinement contract tests."""

from __future__ import annotations

from typing import Any

from co_scientist.checkpoint import serialize_workflow_state
from co_scientist.models import Hypothesis

from app import auth, store


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

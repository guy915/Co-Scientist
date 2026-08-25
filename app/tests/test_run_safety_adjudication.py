"""Safety-decision adjudication and the resulting awaiting-decision status.

Split out of ``test_runs.py`` (which grew past the file-length ceiling once
these were added) to keep that file to run lifecycle: create, start,
persistence, reopen.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests._client import make_client as _client


def _run_with_held_decision(
    client: TestClient, headers: dict[str, str]
) -> tuple[str, str]:
    """Create a run carrying one held intake safety decision."""
    from app import store

    created = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Review a sensitive research protocol"},
    ).json()
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=created["id"],
            stage="intake",
            decision="hold",
            reason="Context requires review.",
            matches=[],
            category="uncertain",
            policy_version="coscientist-safety-v2",
            requires_review=True,
        )
    )
    decision_id = store.list_safety_decisions(created["id"])[0]["id"]
    return created["id"], decision_id


def test_safety_adjudication_is_identified_and_single_use(
    isolated_db: str,
) -> None:
    """A held decision requires an identified reviewer and resolves once."""
    from app import store

    client = _client()
    headers = {"X-Client-ID": "reviewer-1"}
    run_id, decision_id = _run_with_held_decision(client, headers)

    anonymous = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        json={"resolution": "approved"},
    )
    # Ownership middleware hides the existence of another client's run.
    assert anonymous.status_code == 404

    approved = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "approved"},
    )
    assert approved.status_code == 200
    assert store.safety_stage_is_approved(
        run_id, "intake", "coscientist-safety-v2"
    )

    repeated = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert repeated.status_code == 409


def test_held_hypothesis_adjudication_records_without_blocking(
    isolated_db: str,
) -> None:
    """A held-hypothesis hold resolves once and spares the run's lifecycle.

    Unlike intake/final holds, which gate the run's whole goal or report, a
    hypothesis-stage hold concerns one idea the engine already excluded from
    the pool and the report. Approving or rejecting it flips the recorded
    resolution exactly once, and the run itself is left alone.
    """
    from app import engine_adapter
    from tests._drain_helpers import _held_final_state

    client = _client()
    headers = {"X-Client-ID": "held-reviewer"}
    created = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Adjudicate hypotheses held for review"},
    ).json()
    run_id = created["id"]
    engine_adapter._persist_final_state(
        run_id=run_id, final_state=_held_final_state(), db_path=isolated_db
    )

    # The holds are retrievable through the safety endpoint the UI reads.
    listed = client.get(f"/api/runs/{run_id}/safety", headers=headers)
    assert listed.status_code == 200
    holds = [d for d in listed.json()["safety"] if d["decision"] == "hold"]
    assert len(holds) == 2

    approved = client.post(
        f"/api/runs/{run_id}/safety/{holds[0]['id']}/adjudicate",
        headers=headers,
        json={"resolution": "approved"},
    )
    assert approved.status_code == 200

    rejected = client.post(
        f"/api/runs/{run_id}/safety/{holds[1]['id']}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert rejected.status_code == 200

    by_id = {
        d["id"]: d
        for d in client.get(
            f"/api/runs/{run_id}/safety", headers=headers
        ).json()["safety"]
    }
    assert by_id[holds[0]["id"]]["resolution"] == "approved"
    assert by_id[holds[1]["id"]]["resolution"] == "rejected"
    # Single-use, like every other held decision.
    repeated = client.post(
        f"/api/runs/{run_id}/safety/{holds[0]['id']}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert repeated.status_code == 409
    # The held ideas were never part of the published output, so neither
    # resolution blocks the run (an intake/final rejection would).
    assert (
        client.get(f"/api/runs/{run_id}", headers=headers).json()["status"]
        == "draft"
    )


def test_paused_run_with_unresolved_review_awaits_decision(
    isolated_db: str,
) -> None:
    """A paused run with an unresolved review decision awaits a person."""
    from app import store
    from app.store import RunStatus

    client = _client()
    headers = {"X-Client-ID": "awaiting-1"}
    run_id, _ = _run_with_held_decision(client, headers)
    store.update_run_status(run_id, RunStatus.PAUSED)

    detail = client.get(f"/api/runs/{run_id}", headers=headers).json()

    assert detail["awaiting_decision_count"] == 1


def test_paused_run_without_unresolved_review_awaits_nothing(
    isolated_db: str,
) -> None:
    """A paused run with nothing left to review is not awaiting a person."""
    from app import store
    from app.store import RunStatus

    client = _client()
    headers = {"X-Client-ID": "awaiting-2"}
    run = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Explore a mundane pathway"},
    ).json()
    store.update_run_status(run["id"], RunStatus.PAUSED)

    detail = client.get(f"/api/runs/{run['id']}", headers=headers).json()

    assert detail["awaiting_decision_count"] == 0


def test_non_paused_run_with_unresolved_review_awaits_nothing(
    isolated_db: str,
) -> None:
    """A run merely holding a decision, not paused, is not "awaiting"."""
    client = _client()
    headers = {"X-Client-ID": "awaiting-3"}
    # _run_with_held_decision leaves the run in its created 'draft' status.
    run_id, _ = _run_with_held_decision(client, headers)

    detail = client.get(f"/api/runs/{run_id}", headers=headers).json()

    assert detail["awaiting_decision_count"] == 0


def test_paused_run_with_resolved_review_awaits_nothing(
    isolated_db: str,
) -> None:
    """A paused run whose only hold was already resolved awaits no one."""
    from app import store
    from app.store import RunStatus

    client = _client()
    headers = {"X-Client-ID": "awaiting-4"}
    run_id, decision_id = _run_with_held_decision(client, headers)
    client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "approved"},
    )
    store.update_run_status(run_id, RunStatus.PAUSED)

    detail = client.get(f"/api/runs/{run_id}", headers=headers).json()

    assert detail["awaiting_decision_count"] == 0

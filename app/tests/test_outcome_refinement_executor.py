"""Offline acceptance tests for targeted outcome-refinement execution."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from co_scientist.agents.evolution import evolve as evolution
from co_scientist.checkpoint import serialize_workflow_state
from co_scientist.models import (
    Hypothesis,
    HypothesisOrigin,
)

from app import auth, store, task_worker
from app.config import settings
from app.store import RunStatus
from tests._client import make_client


@pytest.fixture(autouse=True)
def _disable_embedded_provider_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-executor-test")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)


def _headers(owner: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth.create_session_token(owner)}",
        "Idempotency-Key": "refine-once",
    }


def _hypothesis(hypothesis_id: str, text: str) -> Hypothesis:
    return Hypothesis(
        id=hypothesis_id,
        text=text,
        title=hypothesis_id,
        origin=HypothesisOrigin.GENERATION,
    )


def _setup_action(client: Any, db_path: str) -> tuple[str, str, str, str]:
    owner = "refinement-owner"
    headers = _headers(owner)
    created = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Test a selected hypothesis"},
    )
    assert created.status_code == 200
    run_id = str(created.json()["id"])
    parent_id = "target-parent"
    sibling_id = "unrelated-sibling"
    parent = _hypothesis(parent_id, "Target hypothesis about pathway A.")
    sibling = _hypothesis(sibling_id, "Sibling hypothesis about pathway B.")
    for hypothesis in (parent, sibling):
        store.add_hypothesis(
            store.NewHypothesis(
                run_id=run_id,
                hypothesis_id=hypothesis.id,
                title=hypothesis.title or hypothesis.id,
                statement=hypothesis.text,
            ),
            db_path=db_path,
        )
    event_seq = store.latest_event_seq(run_id, db_path=db_path)
    envelope = serialize_workflow_state(
        {
            "hypotheses": [parent, sibling],
            "model_name": "offline/test-model",
            "run_id": run_id,
            "research_goal": "Test a selected hypothesis",
            "preferences": "Prefer falsifiable mechanisms",
            "lab_constraints": ["No animal studies"],
            "current_iteration": 0,
        },
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
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=db_path)
    recorded = client.post(
        f"/api/runs/{run_id}/hypotheses/{parent_id}/outcomes",
        headers=headers,
        json={
            "method_protocol": "Isotope shift",
            "conditions": "One generation cycle",
            "measured_observation": "Hybrid band only after one cycle.",
            "units": "density band",
            "controls": "Heavy and light references",
            "interpretation": "Consistent with the target mechanism.",
            "referenced_evidence_ids": [],
        },
    )
    assert recorded.status_code == 201
    response = client.post(
        f"/api/runs/{run_id}/hypotheses/{parent_id}/outcomes/"
        f"{recorded.json()['id']}/refine",
        headers=headers,
    )
    assert response.status_code == 202
    return run_id, parent_id, sibling_id, str(response.json()["action_id"])


def _claim_action(run_id: str, worker_id: str, db_path: str) -> Any:
    task = store.claim_task(worker_id, run_id=run_id, db_path=db_path)
    assert task is not None
    assert task.task_type == "engine.outcome.refinement"
    return task


def test_worker_refines_only_linked_parent_and_persists_at_most_one_child(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client()
    run_id, parent_id, sibling_id, action_id = _setup_action(
        client, isolated_db
    )
    task = _claim_action(run_id, "offline-worker", isolated_db)
    calls: list[dict[str, Any]] = []

    async def evolve_stub(
        parent: Hypothesis,
        context: Any,
        outcome_context: str,
        validation_hypotheses: list[Hypothesis],
    ) -> tuple[Hypothesis, dict[str, Any]]:
        calls.append(
            {
                "parent_id": parent.id,
                "peer_ids": [],
                "validation_ids": [
                    hypothesis.id for hypothesis in validation_hypotheses
                ],
                "outcome_context": outcome_context,
                "prompt_state": context.state,
            }
        )
        child = Hypothesis(
            id="one-child",
            text="A targeted child hypothesis about pathway A.",
            title="Targeted child",
            parent_id=parent.id,
            parent_ids=[parent.id],
            generation=parent.generation + 1,
            origin=HypothesisOrigin.EVOLUTION,
        )
        return child, {"parent_id": parent.id, "child_id": child.id}

    monkeypatch.setattr(
        evolution,
        "evolve_single_hypothesis_from_outcome",
        evolve_stub,
    )
    result = asyncio.run(
        task_worker._execute_task_payload(task, db_path=isolated_db)
    )
    task_worker._record_success(task, "offline-worker", result, isolated_db)

    assert result["action_id"] == action_id
    assert result["child_hypothesis_id"] == "one-child"
    assert len(calls) == 1
    assert calls[0]["parent_id"] == parent_id
    assert calls[0]["peer_ids"] == []
    assert calls[0]["validation_ids"] == [sibling_id]
    assert (
        calls[0]["prompt_state"]["research_goal"]
        == "Test a selected hypothesis"
    )
    assert (
        calls[0]["prompt_state"]["preferences"]
        == "Prefer falsifiable mechanisms"
    )
    assert calls[0]["prompt_state"]["lab_constraints"] == ["No animal studies"]
    assert [
        hypothesis.id for hypothesis in calls[0]["prompt_state"]["hypotheses"]
    ] == [parent_id]
    assert "Hybrid band only after one cycle." in calls[0]["outcome_context"]
    assert (
        "Sibling hypothesis about pathway B." not in calls[0]["outcome_context"]
    )

    action = store.get_outcome_refinement_action(
        run_id, action_id, db_path=isolated_db
    )
    assert action is not None
    assert action["status"] == "completed"
    assert action["child_hypothesis_id"] == "one-child"
    children = [
        hypothesis
        for hypothesis in store.list_hypotheses(run_id, db_path=isolated_db)
        if hypothesis["id"] == "one-child"
    ]
    assert len(children) == 1
    assert children[0]["parent_id"] == parent_id
    action_child = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert action_child is not None
    checkpoint_state = action_child["state"]["state"]
    child_state = next(
        hypothesis
        for hypothesis in checkpoint_state["hypotheses"]
        if hypothesis["id"] == "one-child"
    )
    assert child_state["enrichments"]["outcome_refinement"] == {
        "action_id": action_id,
        "outcome_id": action["outcome_id"],
        "parent_hypothesis_id": parent_id,
    }
    review_tasks = [
        row
        for row in store.list_tasks(run_id, db_path=isolated_db)
        if row.task_type == "engine.node.review"
    ]
    assert len(review_tasks) == 1
    stored_parent = store.get_hypothesis(parent_id, db_path=isolated_db)
    stored_sibling = store.get_hypothesis(sibling_id, db_path=isolated_db)
    assert stored_parent is not None
    assert stored_sibling is not None
    assert stored_parent["elo_rating"] == 1200
    assert stored_sibling["elo_rating"] == 1200
    events = store.list_events(run_id, db_path=isolated_db)
    assert "Hybrid band only after one cycle." not in str(events)
    assert not any(
        event["type"] in {"review", "claim_evidence", "safety", "match"}
        for event in events
    )

    replay_task = store.claim_task(
        "replay-worker", run_id=run_id, db_path=isolated_db
    )
    assert replay_task is not None
    assert replay_task.task_type == "engine.node.review"
    duplicate = asyncio.run(
        task_worker._execute_task_payload(task, db_path=isolated_db)
    )
    assert duplicate["replayed"] is True
    assert len(calls) == 1
    assert (
        len(
            [
                hypothesis
                for hypothesis in store.list_hypotheses(
                    run_id, db_path=isolated_db
                )
                if hypothesis["id"] == "one-child"
            ]
        )
        == 1
    )
    client.close()


def test_provider_failure_retries_same_action_after_restart(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client()
    run_id, parent_id, _, action_id = _setup_action(client, isolated_db)
    first = _claim_action(run_id, "first-worker", isolated_db)
    first_key = first.idempotency_key
    calls = 0

    async def flaky_evolve(*args: Any, **kwargs: Any) -> tuple[None, None]:
        nonlocal calls
        calls += 1
        raise RuntimeError("offline provider unavailable")

    monkeypatch.setattr(
        evolution,
        "evolve_single_hypothesis_from_outcome",
        flaky_evolve,
    )
    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(
            task_worker._execute_task_payload(first, db_path=isolated_db)
        )
    assert store.fail_task(
        first.id,
        "first-worker",
        "temporary",
        retryable=False,
        db_path=isolated_db,
    )
    from app.outcome_refinement_action import (
        materialize_pending_outcome_refinements,
    )

    assert materialize_pending_outcome_refinements(db_path=isolated_db) == 0
    failed = store.get_task(first.id, db_path=isolated_db)
    assert failed is not None and failed.status == "failed"
    action = store.get_outcome_refinement_action(
        run_id, action_id, db_path=isolated_db
    )
    assert action is not None
    replay_response = client.post(
        f"/api/runs/{run_id}/hypotheses/{parent_id}/outcomes/"
        f"{action['outcome_id']}/refine",
        headers=_headers("refinement-owner"),
    )
    assert replay_response.status_code == 202
    assert replay_response.json()["action_id"] == action_id
    assert replay_response.json()["replayed"] is True
    requeued = store.get_task(first.id, db_path=isolated_db)
    assert requeued is not None and requeued.status == "queued"

    from app.store import db as store_db

    store_db._initialized.discard(isolated_db)
    retried = store.claim_task(
        "restarted-worker", run_id=run_id, db_path=isolated_db
    )
    assert retried is not None
    assert retried.id == first.id
    assert retried.idempotency_key == first_key
    assert retried.inputs["action_id"] == action_id

    async def recovered_evolve(
        parent: Hypothesis,
        context: Any,
        outcome_context: str,
        validation_hypotheses: list[Hypothesis],
    ) -> tuple[Hypothesis, dict[str, Any]]:
        nonlocal calls
        calls += 1
        assert parent.id == parent_id
        assert "Hybrid band only after one cycle." in outcome_context
        return (
            Hypothesis(
                id="recovered-child",
                text="A hypothesis after the recovered outcome.",
                parent_id=parent.id,
                parent_ids=[parent.id],
                origin=HypothesisOrigin.EVOLUTION,
            ),
            {},
        )

    monkeypatch.setattr(
        evolution,
        "evolve_single_hypothesis_from_outcome",
        recovered_evolve,
    )
    result = asyncio.run(
        task_worker._execute_task_payload(retried, db_path=isolated_db)
    )
    assert result["child_hypothesis_id"] == "recovered-child"
    assert calls == 2
    client.close()


def test_checkpointed_child_is_committed_without_repeating_evolution(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client()
    run_id, _parent_id, _, action_id = _setup_action(client, isolated_db)
    task = _claim_action(run_id, "checkpoint-worker", isolated_db)
    calls = 0

    async def evolve_once(
        parent: Hypothesis,
        context: Any,
        outcome_context: str,
        validation_hypotheses: list[Hypothesis],
    ) -> tuple[Hypothesis, dict[str, Any]]:
        nonlocal calls
        calls += 1
        return (
            Hypothesis(
                id="checkpoint-child",
                text="A child checkpointed before its row is committed.",
                parent_id=parent.id,
                parent_ids=[parent.id],
                origin=HypothesisOrigin.EVOLUTION,
            ),
            {},
        )

    monkeypatch.setattr(
        evolution,
        "evolve_single_hypothesis_from_outcome",
        evolve_once,
    )
    original_add_hypothesis = store.add_hypothesis
    write_fails = True

    def fail_child_once(hypothesis: store.NewHypothesis, **kwargs: Any) -> Any:
        nonlocal write_fails
        if hypothesis.hypothesis_id == "checkpoint-child" and write_fails:
            write_fails = False
            raise RuntimeError("simulated crash before child row commit")
        return original_add_hypothesis(hypothesis, **kwargs)

    monkeypatch.setattr(store, "add_hypothesis", fail_child_once)
    with pytest.raises(RuntimeError, match="before child row commit"):
        asyncio.run(
            task_worker._execute_task_payload(task, db_path=isolated_db)
        )
    assert calls == 1
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task:{task.id}"
    marker = checkpoint["state"]["state"]["outcome_refinement_result"]
    assert marker["action_id"] == action_id
    assert marker["child_hypothesis_id"] == "checkpoint-child"
    assert store.fail_task(
        task.id,
        "checkpoint-worker",
        "simulated process restart",
        db_path=isolated_db,
    )

    from app.store import db as store_db

    store_db._initialized.discard(isolated_db)
    retried = store.claim_task(
        "after-restart-worker", run_id=run_id, db_path=isolated_db
    )
    assert retried is not None and retried.id == task.id
    monkeypatch.setattr(store, "add_hypothesis", original_add_hypothesis)

    async def should_not_evolve(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("checkpoint replay repeated provider work")

    monkeypatch.setattr(
        evolution,
        "evolve_single_hypothesis_from_outcome",
        should_not_evolve,
    )
    result = asyncio.run(
        task_worker._execute_task_payload(retried, db_path=isolated_db)
    )
    assert result["child_hypothesis_id"] == "checkpoint-child"
    assert calls == 1
    action = store.get_outcome_refinement_action(
        run_id, action_id, db_path=isolated_db
    )
    assert action is not None and action["status"] == "completed"
    assert (
        len(
            [
                hypothesis
                for hypothesis in store.list_hypotheses(
                    run_id, db_path=isolated_db
                )
                if hypothesis["id"] == "checkpoint-child"
            ]
        )
        == 1
    )
    client.close()

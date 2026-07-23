"""App-level checkpoint + resume: derived-data clearing and pause semantics.

Engine resume itself (restore a persisted ``WorkflowState`` and continue from
the last checkpoint without redoing completed work) is covered end-to-end in
``test_resume_engine.py``, including the durable pause/resume path in
``test_runs_edge.py`` (test
``test_engine_queue_can_pause_and_resume_without_process_handle``).
This file covers the surrounding store + endpoint seams that resume relies on:
``clear_run_derived_data`` preserving scientist contributions while dropping
agent artifacts, event-seq continuity across a resume boundary, and the
resume/pause endpoint guards.
"""

from __future__ import annotations

from app import store
from tests._client import make_client as _client


def _seed_agent_artifacts(run_id: str) -> str:
    """Persist agent-authored hypothesis + review + retrieved evidence."""
    agent_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Agent idea",
            statement="An agent-generated hypothesis.",
            created_by_agent="generation",
        )
    )
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=agent_id,
            reviewer_agent="reflection",
            summary="agent review",
            critique="agent critique",
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title="Retrieved paper",
            source="pubmed",
            abstract="x",
        )
    )
    return agent_id


def _seed_scientist_artifacts(run_id: str) -> str:
    """Persist scientist hypothesis + human review + an attachment."""
    manual_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Human idea",
            statement="A scientist-authored hypothesis.",
            created_by_agent="scientist_manual",
            author="dr-who",
        )
    )
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=manual_id,
            reviewer_agent="scientist",
            summary="human review",
            critique="looks promising",
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title="Attached doc",
            source="attachment",
            abstract="notes",
        )
    )
    return manual_id


def test_resume_preserves_scientist_contributions(isolated_db: str) -> None:
    """Clearing derived data keeps human hypotheses/reviews/attachments."""
    run = store.create_run(
        "Human input survives resume", "express", "engine", {}
    )
    _seed_agent_artifacts(run.id)
    manual_id = _seed_scientist_artifacts(run.id)

    store.clear_run_derived_data(run.id)

    # The human hypothesis, review, and attachment survive; agent artifacts go.
    hyps = store.list_hypotheses(run.id)
    assert [h["id"] for h in hyps] == [manual_id]
    reviews = store.list_reviews(run.id)
    assert len(reviews) == 1 and reviews[0]["reviewer_agent"] == "scientist"
    evidence = store.list_evidence(run.id)
    assert [e["source"] for e in evidence] == ["attachment"]


def test_publication_replay_preserves_task_history_and_scientist_input(
    isolated_db: str,
) -> None:
    """Finalizer cleanup removes drain rows without erasing durable history."""
    run = store.create_run("Publication replay", "express", "engine", {})
    manual_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Human idea",
            statement="Scientist idea",
            created_by_agent="scientist_manual",
        )
    )
    store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Agent idea",
            statement="Agent idea",
            created_by_agent="generation",
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run.id, title="Private", source="attachment", abstract="x"
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run.id, title="Paper", source="pubmed", abstract="y"
        )
    )
    store.append_event(run.id, "scientific_task", {"task": "ranking"})
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run.id,
            stage="intake",
            decision="allow",
            reason="",
            matches=[],
        )
    )
    store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.finalize",
            inputs={},
            idempotency_key="finalize-test",
        ),
        db_path=isolated_db,
    )

    store.clear_publication_artifacts(run.id, db_path=isolated_db)

    assert [item["id"] for item in store.list_hypotheses(run.id)] == [manual_id]
    assert [item["source"] for item in store.list_evidence(run.id)] == [
        "attachment"
    ]
    assert len(store.list_events(run.id)) == 1
    assert len(store.list_safety_decisions(run.id)) == 1
    assert len(store.list_tasks(run.id, db_path=isolated_db)) == 1


def test_resume_reassigns_event_seqs_above_last_checkpoint(
    isolated_db: str,
) -> None:
    """Event seqs after a resume continue above the checkpoint high-water mark.

    ``clear_run_derived_data`` empties ``run_events``, but a client holding
    ``?after=N`` from before the resume must not silently miss the resumed
    run's events. The checkpoint's ``last_event_seq`` floors the next seq.
    """
    run = store.create_run("Seq continuity", "express", "engine", {})
    for i in range(5):
        store.append_event(run.id, "log", {"i": i})
    high_water = store.latest_event_seq(run.id)
    assert high_water == 5

    # A checkpoint records the high-water mark, then a resume clears events.
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="pause", schema_version=1, last_event_seq=high_water, state={}
        ),
    )
    store.clear_run_derived_data(run.id)
    assert store.list_events(run.id) == []

    # The next event continues strictly above the pre-resume high-water mark,
    # so an ?after=5 reconnect still receives it.
    seq = store.append_event(run.id, "status", {"status": "resuming"})
    assert seq == high_water + 1
    assert store.list_events(run.id, after_seq=high_water)[0]["seq"] == seq


def test_resume_endpoint_requires_a_checkpoint(isolated_db: str) -> None:
    """Resuming a run with no checkpoint is a 409 (nothing to resume from)."""
    client = _client()
    run_id = client.post(
        "/api/runs", json={"research_goal": "No checkpoint yet"}
    ).json()["id"]
    res = client.post(f"/api/runs/{run_id}/resume")
    assert res.status_code == 409


def test_pause_endpoint_404_when_not_active(isolated_db: str) -> None:
    """Pausing a run that is not running in this process is a 404."""
    client = _client()
    run_id = client.post(
        "/api/runs", json={"research_goal": "Not active"}
    ).json()["id"]
    res = client.post(f"/api/runs/{run_id}/pause")
    assert res.status_code == 404

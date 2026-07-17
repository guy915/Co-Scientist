"""App-level checkpoint + resume: derived-data clearing and pause semantics.

Engine resume itself (restore a persisted ``WorkflowState`` and continue from
the last checkpoint without redoing completed work) is covered end-to-end in
``test_resume_engine.py``. This file covers the surrounding store + endpoint
seams that resume relies on: ``clear_run_derived_data`` preserving scientist
contributions while dropping agent artifacts, event-seq continuity across a
resume boundary, the pause override that keeps an engine run resumable, and the
resume/pause endpoint guards.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app import store
from tests._client import make_client as _client


def test_resume_preserves_scientist_contributions(isolated_db: str) -> None:
    """Clearing derived data keeps human hypotheses/reviews/attachments."""
    run = store.create_run(
        "Human input survives resume", "express", "engine", {}
    )

    # Agent-authored artifacts: a generated hypothesis, an agent review of it,
    # and retrieved (pubmed) evidence -- everything a resume rebuilds.
    agent_id = store.add_hypothesis(
        run.id,
        title="Agent idea",
        statement="An agent-generated hypothesis.",
        created_by_agent="generation",
    )
    store.add_review(
        run.id,
        hypothesis_id=agent_id,
        reviewer_agent="reflection",
        summary="agent review",
        critique="agent critique",
    )
    store.add_evidence(run.id, "Retrieved paper", source="pubmed", abstract="x")

    # Scientist contributions: a manual hypothesis, a human review of it, and
    # an attachment (run-scoped evidence with the attachment source).
    manual_id = store.add_hypothesis(
        run.id,
        title="Human idea",
        statement="A scientist-authored hypothesis.",
        created_by_agent="scientist_manual",
        author="dr-who",
    )
    store.add_review(
        run.id,
        hypothesis_id=manual_id,
        reviewer_agent="scientist",
        summary="human review",
        critique="looks promising",
    )
    store.add_evidence(
        run.id, "Attached doc", source="attachment", abstract="notes"
    )

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
        run.id,
        title="Human idea",
        statement="Scientist idea",
        created_by_agent="scientist_manual",
    )
    store.add_hypothesis(
        run.id,
        title="Agent idea",
        statement="Agent idea",
        created_by_agent="generation",
    )
    store.add_evidence(run.id, "Private", source="attachment", abstract="x")
    store.add_evidence(run.id, "Paper", source="pubmed", abstract="y")
    store.append_event(run.id, "scientific_task", {"task": "ranking"})
    store.add_safety_decision(run.id, "intake", "allow", "", [])
    store.enqueue_task(
        run.id,
        "engine.finalize",
        {},
        idempotency_key="finalize-test",
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
        stage="pause",
        schema_version=1,
        last_event_seq=high_water,
        state={},
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


async def test_paused_engine_run_lands_in_paused_not_cancelled(
    isolated_db: str,
) -> None:
    """The pause override fires end-to-end for a no-checkpoint engine run.

    Reproduces the exact broken sequence: an engine run with no per-iteration
    checkpoint, handle.paused set, and the workflow ending on the cancel
    signal (having set CANCELLED, as the engine adapter does). The task must
    override the terminal status to the resumable PAUSED, not leave it
    CANCELLED.
    """
    from app import engine_adapter
    from app.runs import _ensure_resumable_checkpoint, _run_workflow_task
    from app.runs_registry import _active, _RunHandle
    from app.store import RunStatus

    run = store.create_run("Engine pause e2e", "express", "engine", {})
    store.update_run_status(run.id, RunStatus.RUNNING)

    async def _fake_run_workflow(**_kwargs: object) -> AsyncIterator[Any]:
        # The engine adapter marks the run CANCELLED when it sees the cancel
        # signal, then the stream ends. Mirror that, yielding nothing further.
        store.update_run_status(run.id, RunStatus.CANCELLED)
        for _ in ():  # an async generator that yields nothing
            yield

    original = engine_adapter.run_workflow
    engine_adapter.run_workflow = _fake_run_workflow  # type: ignore[assignment]
    try:
        handle = _RunHandle()
        handle.paused = True
        _active[run.id] = handle
        # What the pause endpoint does before signalling:
        _ensure_resumable_checkpoint(run.id, "engine")

        await _run_workflow_task(
            run.id, run.research_goal, run.config, None, handle
        )
    finally:
        engine_adapter.run_workflow = original
        _active.pop(run.id, None)

    reopened = store.get_run(run.id)
    assert reopened is not None
    assert reopened.status == RunStatus.PAUSED.value
    assert store.has_checkpoint(run.id)


def test_ensure_resumable_checkpoint_makes_engine_run_resumable(
    isolated_db: str,
) -> None:
    """Pausing ensures a checkpoint so an engine run is resumable, not lost.

    The engine provider does not checkpoint per iteration, so without this the
    pause-override in _run_workflow_task could never fire for an engine run and
    /resume would 409 forever.
    """
    from app.runs import _ensure_resumable_checkpoint

    run = store.create_run("Engine pause", "express", "engine", {})
    assert not store.has_checkpoint(run.id)

    _ensure_resumable_checkpoint(run.id, "engine")
    assert store.has_checkpoint(run.id)

    # Idempotent: a second pause does not add a second checkpoint.
    _ensure_resumable_checkpoint(run.id, "engine")
    latest = store.get_latest_checkpoint(run.id)
    assert latest is not None and latest["seq"] == 1

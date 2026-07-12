"""App-level checkpoint + resume (Milestone 4): failure injection and recovery.

The mock writes an envelope checkpoint at each iteration boundary, so a run
interrupted after one is resumable. Resume clears the run's derived data and
re-runs deterministically from the same seed, reconstructing identical terminal
artifacts without duplicating rows, events, or the report. These tests exercise
that offline (the endpoints wrap the same store + workflow seam).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.run_modes import resolved_run_config
from tests._client import make_client as _client
from tests.test_mock_workflow import _drain_mock_workflow


def _terminal_fingerprint(run_id: str) -> dict[str, Any]:
    """A seed-deterministic summary of a run's terminal artifacts.

    Hypothesis ids are fresh uuids per run, so the fingerprint uses the
    deterministic content (titles/Elo/record) rather than ids.
    """
    hyps = store.list_hypotheses(run_id)
    report = store.get_latest_report(run_id)
    return {
        "hypotheses": sorted(
            (h["title"], h["elo_rating"], h["win_count"], h["loss_count"])
            for h in hyps
        ),
        "match_count": len(store.list_matches(run_id)),
        "report_hyp_count": (report or {})
        .get("payload", {})
        .get("hypothesis_count"),
    }


async def _drain_until_checkpoint(
    run_id: str, goal: str, cfg: dict[str, Any]
) -> None:
    """Drive the mock only until its first checkpoint, then stop (a crash).

    Leaves the run mid-flight: a checkpoint exists but no report, simulating an
    interruption after the first ranking iteration.
    """
    from app.mock_workflow import run_mock_workflow

    async for _ in run_mock_workflow(run_id, goal, cfg, sleep_seconds=0):
        if store.has_checkpoint(run_id):
            return  # stop consuming -> the workflow is interrupted


def test_resume_reconstructs_identical_terminal_artifacts(
    isolated_db: str,
) -> None:
    """Clearing + re-running from the seed rebuilds identical artifacts."""
    cfg = resolved_run_config({})
    run = store.create_run("Resume determinism", "standard", "mock", {})

    asyncio.run(_drain_mock_workflow(run.id, run.research_goal, cfg))
    before = _terminal_fingerprint(run.id)
    assert before["report_hyp_count"] is not None  # completed once

    # Resume = clear derived data + re-run deterministically (same run_id seed).
    store.clear_run_derived_data(run.id)
    # Every derived table must be empty -- not just hypotheses. The child
    # tables (reviews/citations/claim_evidence/hypothesis_state) are cleared
    # explicitly, since the FK cascade is not enforced on this connection.
    assert store.list_hypotheses(run.id) == []
    assert store.list_reviews(run.id) == []
    assert store.list_citations(run.id) == []
    assert store.list_claim_evidence(run.id) == []
    assert store.list_matches(run.id) == []
    asyncio.run(_drain_mock_workflow(run.id, run.research_goal, cfg))
    after = _terminal_fingerprint(run.id)

    assert after == before


def test_interrupted_run_is_resumable_and_completes_once(
    isolated_db: str,
) -> None:
    """A crash mid-run leaves a checkpoint; reconcile+resume finishes it."""
    cfg = resolved_run_config({})
    run = store.create_run("Resume recovery", "standard", "mock", {})

    # Interrupt after the first checkpoint; the run is left non-terminal.
    asyncio.run(_drain_until_checkpoint(run.id, run.research_goal, cfg))
    assert store.has_checkpoint(run.id)
    store.update_run_status(run.id, store.RunStatus.RUNNING)

    # Simulated restart: reconcile marks the checkpointed run resumable.
    reconciled = store.reconcile_interrupted_runs()
    assert run.id in reconciled["resumable"]

    # Resume: clear + re-run to completion.
    store.clear_run_derived_data(run.id)
    asyncio.run(_drain_mock_workflow(run.id, run.research_goal, cfg))

    # Exactly one report, and event seqs are unique (no duplicated events).
    report = store.get_latest_report(run.id)
    assert report is not None
    events = store.list_events(run.id)
    seqs = [e["seq"] for e in events]
    assert len(seqs) == len(set(seqs))
    assert seqs == sorted(seqs)


def test_resume_preserves_scientist_contributions(isolated_db: str) -> None:
    """Clearing derived data keeps human hypotheses/reviews/attachments."""
    cfg = resolved_run_config({})
    run = store.create_run(
        "Human input survives resume", "standard", "mock", {}
    )
    asyncio.run(_drain_mock_workflow(run.id, run.research_goal, cfg))

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
    run = store.create_run("Publication replay", "standard", "engine", {})
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
    run = store.create_run("Seq continuity", "standard", "mock", {})
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


async def test_mock_stop_emits_paused_when_pause_flagged(
    isolated_db: str,
) -> None:
    """The mock's stop path persists/emits `paused`, not a wrong `cancelled`.

    Reproduces finding #2: pause reuses the cancel signal, so the terminal
    emit must consult the registry pause flag and land the run PAUSED rather
    than writing a terminal `cancelled` status event that closes SSE streams.
    """
    from app.mock_workflow_stages import _emit_cancelled_if_set
    from app.report_events import make_emitter
    from app.runs_registry import _active, _RunHandle
    from app.store import RunStatus

    run = store.create_run("Mock pause emit", "standard", "mock", {})
    emit = make_emitter(run.id, db_path=isolated_db)
    cancelled = asyncio.Event()
    cancelled.set()

    handle = _RunHandle()
    handle.paused = True
    _active[run.id] = handle
    try:
        event = await _emit_cancelled_if_set(
            run.id, isolated_db, cancelled, emit
        )
    finally:
        _active.pop(run.id, None)

    assert event is not None and event["payload"]["status"] == "paused"
    reopened = store.get_run(run.id, db_path=isolated_db)
    assert reopened is not None
    assert reopened.status == RunStatus.PAUSED.value


async def test_mock_stop_emits_cancelled_without_pause_flag(
    isolated_db: str,
) -> None:
    """Without the pause flag, the stop path still lands the run cancelled."""
    from app.mock_workflow_stages import _emit_cancelled_if_set
    from app.report_events import make_emitter
    from app.store import RunStatus

    run = store.create_run("Mock cancel emit", "standard", "mock", {})
    emit = make_emitter(run.id, db_path=isolated_db)
    cancelled = asyncio.Event()
    cancelled.set()

    # No handle registered -> not a pause -> cancelled.
    event = await _emit_cancelled_if_set(run.id, isolated_db, cancelled, emit)

    assert event is not None and event["payload"]["status"] == "cancelled"
    reopened = store.get_run(run.id, db_path=isolated_db)
    assert reopened is not None
    assert reopened.status == RunStatus.CANCELLED.value


def test_double_resume_is_stable(isolated_db: str) -> None:
    """Two consecutive resume cycles produce identical terminal artifacts."""
    cfg = resolved_run_config({})
    run = store.create_run("Double resume", "standard", "mock", {})

    asyncio.run(_drain_mock_workflow(run.id, run.research_goal, cfg))
    first = _terminal_fingerprint(run.id)

    for _ in range(2):
        store.clear_run_derived_data(run.id)
        asyncio.run(_drain_mock_workflow(run.id, run.research_goal, cfg))

    assert _terminal_fingerprint(run.id) == first


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

    run = store.create_run("Engine pause e2e", "standard", "engine", {})
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

    The engine provider does not checkpoint per iteration (only the mock does),
    so without this the pause-override in _run_workflow_task could never fire
    for an engine run and /resume would 409 forever.
    """
    from app.runs import _ensure_resumable_checkpoint

    run = store.create_run("Engine pause", "standard", "engine", {})
    assert not store.has_checkpoint(run.id)

    _ensure_resumable_checkpoint(run.id, "engine")
    assert store.has_checkpoint(run.id)

    # Idempotent: a second pause does not add a second checkpoint.
    _ensure_resumable_checkpoint(run.id, "engine")
    latest = store.get_latest_checkpoint(run.id)
    assert latest is not None and latest["seq"] == 1

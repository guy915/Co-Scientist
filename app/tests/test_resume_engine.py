"""App-level REAL-engine checkpoint + resume (P0.7).

Unlike ``test_resume.py`` (mock provider, deterministic re-derive), these drive
the *real* ``HypothesisGenerator`` through the app engine adapter with only the
LLM boundary faked. They prove the engine provider truly resumes from a
persisted ``WorkflowState`` — completed nodes are not re-run — rather than the
old behavior of clearing derived data and re-running from the goal (a retry
from zero that discarded all completed LLM/tool work).

Acceptance (P0.7): kill the run after a node, resume, and (a) do not repeat
completed LLM/tool calls, (b) preserve the checkpointed hypotheses, (c) produce
exactly one report with unique, monotonic event seqs.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import engine_adapter, store
from tests._resume_engine_helpers import (
    _assert_events_unique_and_monotonic,
    _assert_published_report,
    _assert_unique_ids,
    _drain_all,
    _drain_until,
    _engine_cfg,
    _engine_stream,
    _install_fake_engine_llm,
    _latest_checkpoint,
    _post_generate_boundary,
    _reviewed_boundary,
)


def _count_llm_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Wrap ``litellm.acompletion`` with a call counter, return the counter."""
    import litellm

    calls = {"n": 0}
    original = litellm.acompletion

    async def _counting(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(litellm, "acompletion", _counting)
    return calls


def _seed_stale_mock_run(run_id: str) -> str:
    """Persist stale mock-era artifacts a re-bootstrap must clear.

    Returns the id of the stale agent-authored hypothesis.
    """
    stale_id = store.add_hypothesis(
        run_id,
        title="Stale agent idea",
        statement="A hypothesis from the retired mock run.",
        created_by_agent="generation",
    )
    store.add_evidence(run_id, "Old mock paper", source="pubmed", abstract="x")
    return stale_id


def _save_legacy_mock_checkpoint(run_id: str) -> None:
    """Save a pre-flip mock envelope checkpoint (not engine WorkflowState)."""
    store.save_checkpoint(
        run_id,
        stage="iteration_1",
        schema_version=1,
        last_event_seq=store.latest_event_seq(run_id),
        state={
            "provider": "mock",
            "run_mode": "express",
            "iteration": 1,
            "config": {"tier": "express"},
        },
    )


def _assert_rebootstrapped_completed(run_id: str, stale_id: str) -> None:
    """Assert a legacy resume cleared stale data and completed durably.

    (1) the stale mock-era hypothesis is gone, (2) durable engine tasks drove
    the run, (3) fresh hypotheses were generated, ranked, and published.
    """
    final_hyps = store.list_hypotheses(run_id)
    assert stale_id not in {h["id"] for h in final_hyps}
    assert any(
        task.task_type.startswith("engine.")
        for task in store.list_tasks(run_id)
    )
    assert final_hyps
    _assert_published_report(run_id)
    final = store.get_run(run_id)
    assert final is not None
    assert final.status == store.RunStatus.COMPLETED.value


def _enqueue_paused_blocking_task(run_id: str, db_path: str) -> None:
    """Enqueue one blocking engine task and leave the run paused."""
    store.enqueue_task(
        run_id,
        "engine.test.blocking",
        {},
        idempotency_key="blocking:0",
        db_path=db_path,
    )
    store.pause_run_tasks(run_id, db_path=db_path)
    store.update_run_status(run_id, store.RunStatus.PAUSED)


def _install_blocking_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the task executor with a synchronous ~1s blocking cost.

    Stands in for the worker's real synchronous cost: a large json.dumps plus
    a committed SQLite write, run directly on the caller's loop.
    """
    import time as _time

    from app import engine_tasks

    async def _execute(
        _task: Any, *, db_path: str | None = None
    ) -> dict[str, bool]:
        _time.sleep(1.0)
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)


async def _worst_loop_stall(stop: asyncio.Event) -> float:
    """Return the worst delay the loop imposed on a 10ms sleep until stopped."""
    import time as _time

    worst = 0.0
    while not stop.is_set():
        started = _time.monotonic()
        await asyncio.sleep(0.01)
        worst = max(worst, _time.monotonic() - started - 0.01)
    return worst


async def test_engine_run_persists_real_state_checkpoints(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real engine run checkpoints its full WorkflowState, not an envelope."""
    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()
    run = store.create_run("Engine checkpoint", "standard", "engine", {})

    await _drain_all(_engine_stream(run.id, run.research_goal, cfg))

    checkpoint = store.get_latest_checkpoint(run.id)
    assert checkpoint is not None
    envelope = checkpoint["state"]
    # An engine checkpoint carries a serialized WorkflowState, not the mock's
    # {provider, run_mode, iteration, config} envelope.
    assert envelope.get("provider") == "engine"
    assert "state" in envelope and "hypotheses" in envelope["state"]
    assert envelope["state"]["hypotheses"], "checkpoint has no hypotheses"
    # last_event_seq is a real high-water mark within the run's event log.
    assert 0 < checkpoint["last_event_seq"] <= store.latest_event_seq(run.id)


async def test_engine_resume_preserves_work_and_reports_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interrupt a real engine run, resume, and finish without redoing work."""
    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()
    run = store.create_run("Engine resume", "standard", "engine", {})

    # Interrupt at the pre-orchestrator boundary (all hypotheses reviewed).
    await _drain_until(
        _engine_stream(run.id, run.research_goal, cfg),
        _reviewed_boundary(run.id),
    )
    checkpoint = _latest_checkpoint(run.id)
    checkpointed_ids = {
        h["id"] for h in checkpoint["state"]["state"]["hypotheses"]
    }
    assert checkpointed_ids
    assert store.get_latest_report(run.id) is None  # not finished yet
    high_water = checkpoint["last_event_seq"]

    # Resume: restore the checkpoint and re-enter at the orchestrator.
    resume_events = await _drain_all(
        _engine_stream(run.id, run.research_goal, cfg, resume=True)
    )
    _assert_published_report(run.id)  # latent-only ideas ranked + published
    assert resume_events[-1]["payload"].get("status") == "completed"

    # Completed work preserved; artifacts persist exactly once (no dup).
    final_hyps = store.list_hypotheses(run.id)
    assert checkpointed_ids <= {h["id"] for h in final_hyps}
    _assert_unique_ids(final_hyps)
    _assert_unique_ids(store.list_matches(run.id))

    # No replay: supervisor never re-runs; seqs stay unique/monotonic and
    # continue above the high-water mark.
    assert "supervisor.plan" not in [e["type"] for e in resume_events]
    _assert_events_unique_and_monotonic(run.id)
    after_hw = store.list_events(run.id, after_seq=high_water)
    assert after_hw and min(e["seq"] for e in after_hw) > high_water


async def test_engine_resume_from_unreviewed_pool_self_heals(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming from a post-generate checkpoint schedules the missing review.

    Interrupting after ``generate`` (hypotheses present, none reviewed) is a
    different end-to-end composition than the post-review boundary: on resume
    the orchestrator must schedule REFLECT -> review -> safety_screen ->
    ranking to catch up, exercising the adaptive self-heal path from a restored
    checkpoint (not just the scheduler rules in isolation). It also proves the
    P0.4 pre-ranking safety screen still runs when resume drives the first
    review/rank.
    """
    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()
    run = store.create_run("Engine resume unreviewed", "standard", "engine", {})

    # Interrupt after generate: hypotheses exist but none reviewed yet.
    await _drain_until(
        _engine_stream(run.id, run.research_goal, cfg),
        _post_generate_boundary(run.id),
    )
    checkpointed = _latest_checkpoint(run.id)["state"]["state"]["hypotheses"]
    assert checkpointed and all(not h.get("reviews") for h in checkpointed)
    checkpointed_ids = {h["id"] for h in checkpointed}

    resume_events = await _drain_all(
        _engine_stream(run.id, run.research_goal, cfg, resume=True)
    )
    # The resume caught up: it ran review + the pre-ranking safety screen.
    resumed_types = [e["type"] for e in resume_events]
    assert "review" in resumed_types
    assert "safety_screen" in resumed_types
    assert "supervisor.plan" not in resumed_types  # supervisor never re-runs

    # Completed generation preserved; latent-only output published.
    _assert_published_report(run.id)
    final_ids = {h["id"] for h in store.list_hypotheses(run.id)}
    assert checkpointed_ids <= final_ids
    assert resume_events[-1]["payload"].get("status") == "completed"


async def test_engine_resume_does_not_repeat_completed_llm_calls(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming makes fewer LLM calls than a full run (work is reused)."""
    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()
    calls = _count_llm_calls(monkeypatch)

    # Baseline: an uninterrupted run's total LLM-call count.
    full_run = store.create_run("Engine full", "standard", "engine", {})
    await _drain_all(_engine_stream(full_run.id, full_run.research_goal, cfg))
    full_run_calls = calls["n"]
    assert full_run_calls > 0

    # Interrupt a fresh run at the safe boundary, then resume.
    calls["n"] = 0
    run = store.create_run("Engine resume calls", "standard", "engine", {})

    await _drain_until(
        _engine_stream(run.id, run.research_goal, cfg),
        _reviewed_boundary(run.id),
    )
    calls_before_resume = calls["n"]

    await _drain_all(
        _engine_stream(run.id, run.research_goal, cfg, resume=True)
    )
    resume_calls = calls["n"] - calls_before_resume

    # A true resume re-enters at the orchestrator and re-runs only the
    # remaining nodes, so the resumed segment makes strictly fewer LLM calls
    # than a full run from the goal would. A from-zero re-run (the old
    # behavior) would instead repeat the entire first pass.
    assert 0 < resume_calls < full_run_calls


async def test_launch_resume_drives_engine_resume_end_to_end(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The app's real resume launcher resumes an engine run from its checkpoint.

    Exercises ``runs._launch_resume`` (the endpoint's launcher) rather than the
    adapter seam directly, proving the engine branch does not clear derived
    data — the pre-interruption events survive — and drives a true resume.
    """
    import app.runs as runs_mod

    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()
    run = store.create_run("Launch resume", "standard", "engine", {})

    await _drain_until(
        _engine_stream(run.id, run.research_goal, cfg),
        _reviewed_boundary(run.id),
    )
    pre_resume_seqs = {e["seq"] for e in store.list_events(run.id)}
    assert pre_resume_seqs  # supervisor..review events were persisted
    # An interrupted run is left non-terminal; the launcher requires that.
    store.update_run_status(run.id, store.RunStatus.RUNNING)

    await runs_mod._launch_resume(run.id)
    await asyncio.gather(*list(runs_mod._resume_tasks))

    # Engine checkpoint => derived data NOT cleared => pre-resume events kept.
    all_seqs = [e["seq"] for e in store.list_events(run.id)]
    assert pre_resume_seqs <= set(all_seqs)
    _assert_events_unique_and_monotonic(run.id)
    # The launcher reaches finalization once; latent-only ideas are ranked and
    # published (badged "Unverified") rather than blocked.
    _assert_published_report(run.id)
    final = store.get_run(run.id)
    assert final is not None
    assert final.status == store.RunStatus.COMPLETED.value


async def test_launch_resume_rebootstraps_legacy_mock_checkpoint(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy mock-envelope resume re-runs fresh through the durable path.

    Covers ``runs._launch_resume``'s non-engine-checkpoint fallback -- the
    exact path a production resume of an old ``provider="mock"`` run takes
    after the mock's retirement. There is no persisted engine WorkflowState to
    restore, so the launcher clears the run's stale derived data and
    re-bootstraps it through the durable worker as a fresh offline engine run,
    rather than the old in-process re-derive. Proves (1) the stale mock-era
    artifacts are cleared, (2) the durable bootstrap task drives the run, and
    (3) it completes with a ranked, published report.
    """
    import app.runs as runs_mod

    _install_fake_engine_llm(monkeypatch)
    run = store.create_run(
        "Legacy mock resume", "express", "mock", {"tier": "express"}
    )

    # Stale mock-era artifacts a re-bootstrap must clear, plus a legacy mock
    # envelope checkpoint (not an engine WorkflowState) -- the fallback trigger.
    stale_id = _seed_stale_mock_run(run.id)
    _save_legacy_mock_checkpoint(run.id)
    assert not engine_adapter.is_engine_checkpoint(
        store.get_latest_checkpoint(run.id)
    )
    # An interrupted run is left non-terminal; the launcher requires that.
    store.update_run_status(run.id, store.RunStatus.PAUSED)

    await runs_mod._launch_resume(run.id)
    await asyncio.gather(*list(runs_mod._resume_tasks))

    # Legacy checkpoint => stale data cleared; re-bootstrapped run completes.
    _assert_rebootstrapped_completed(run.id, stale_id)


async def test_resume_does_not_execute_run_work_on_the_event_loop(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming a run must leave the API's event loop free to serve requests.

    The durable worker does synchronous SQLite writes and serializes whole
    WorkflowState blobs, so driving it with ``create_task`` runs that
    blocking work on the API loop. Starting a run has always handed the
    cohort to a thread; resume did not, so a boot carrying interrupted runs
    stopped answering /health, Railway killed the container mid-run, and the
    next boot inherited one more interrupted run -- a spiral in which runs
    only advanced during the doomed startup window.
    """
    import app.runs as runs_mod

    run = store.create_run("loop freedom", "standard", "engine", {})
    _enqueue_paused_blocking_task(run.id, isolated_db)
    _install_blocking_execute(monkeypatch)

    stop = asyncio.Event()
    probe = asyncio.create_task(_worst_loop_stall(stop))
    await runs_mod._launch_resume(run.id)
    await asyncio.gather(*list(runs_mod._resume_tasks))
    stop.set()
    worst_stall = await probe

    assert worst_stall < 0.5, (
        f"event loop stalled {worst_stall:.2f}s while a resumed run executed"
    )

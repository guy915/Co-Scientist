"""App-level double-resume-cycle coverage (CKPT-FAILINJECT-001).

The engine-level ``test_double_restart_preserves_pool_and_completes``
proves two consecutive checkpoint/restore cycles survive on a bare
``WorkflowState``. Nothing at the app layer replayed that composition
against the *durable task queue* -- the mock-era ``test_double_resume_is_
stable`` covered it but was dropped with the mock workflow, and the
single-interruption coverage that replaced it
(``test_resume_engine.py``, ``test_runs_edge.py::
test_engine_queue_can_pause_and_resume_without_process_handle``) never
went further than one pause/resume.

Drives the durable task queue one task at a time
(``task_worker.run_once``) rather than relying on the embedded worker's
own background timing, so both pause boundaries land at a known point
in the run instead of racing a thread -- the app-layer analogue of the
engine test's precise ``_pre_orchestrator_index`` cut point.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import store, task_worker
from app.config import settings
from tests._client import make_client as _client

_WORKER = "double-resume-test"


async def _advance(run_id: str, count: int, db_path: str) -> None:
    """Execute exactly ``count`` ready durable tasks for ``run_id``."""
    for _ in range(count):
        worked = await task_worker.run_once(
            _WORKER, run_id=run_id, db_path=db_path
        )
        assert worked, "run finished (or stalled) earlier than the test expects"


async def _advance_until_pool_nonempty(
    run_id: str, db_path: str, *, cap: int = 30
) -> set[str]:
    """Run tasks one at a time until the checkpointed pool is non-empty.

    A fixed task count would hard-code the exact shape of generation's
    fan-out (strategy items + an aggregate that is the one commit
    actually merging hypotheses into state), which is not this test's
    concern and would make it brittle to that shape changing. Bounded so
    a run that never grows a pool fails loudly instead of hanging.
    """
    for _ in range(cap):
        worked = await task_worker.run_once(
            _WORKER, run_id=run_id, db_path=db_path
        )
        assert worked, "run finished before its pool ever grew"
        pool = _checkpoint_hypothesis_ids(run_id, db_path)
        if pool:
            return pool
    raise AssertionError(f"pool still empty after {cap} tasks")


def _pause_and_resume(client: Any, run_id: str) -> None:
    """One durable pause/resume cycle over HTTP, asserting both succeed."""
    paused = client.post(f"/api/runs/{run_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = client.post(f"/api/runs/{run_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"


def _checkpoint_hypothesis_ids(run_id: str, db_path: str) -> set[str]:
    """Read the hypothesis ids out of the run's latest raw checkpoint.

    Indexes the stored envelope directly (``checkpoint["state"]`` is
    ``co_scientist.checkpoint.serialize_workflow_state``'s own envelope,
    whose payload sits one level further under its own ``"state"`` key)
    rather than going through ``restore_workflow_state``, since this only
    needs to read ids, not reconstruct live ``Hypothesis`` objects.
    """
    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    payload = checkpoint["state"]["state"]
    return {str(h["id"]) for h in payload.get("hypotheses") or []}


@pytest.mark.asyncio
async def test_two_resume_cycles_still_complete_with_pool_intact(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two pause/resume cycles on one run still reach a completed report.

    Embedded worker execution is disabled so nothing but this test's own
    ``task_worker.run_once`` calls advances the run -- the same technique
    ``test_engine_queue_can_pause_and_resume_without_process_handle`` uses
    for a single cycle, extended here to two, through to completion, with
    an explicit check that the pool captured before the second
    interruption survives into the published report.
    """
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    created = client.post(
        "/api/runs",
        json={"research_goal": "Double resume coverage", "tier": "express"},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200

    # First interruption: right after bootstrap, before any checkpoint
    # has ever needed to be resumed from at all.
    await _advance(run_id, 1, isolated_db)
    _pause_and_resume(client, run_id)

    # Second interruption: after enough further work that the pool is no
    # longer empty, so there is something real to prove survives.
    pool_before = await _advance_until_pool_nonempty(run_id, isolated_db)
    _pause_and_resume(client, run_id)

    # Drain the rest of the run to completion, still entirely by hand.
    await task_worker.run_run_until_idle(run_id, _WORKER, db_path=isolated_db)

    final_run = store.get_run(run_id, db_path=isolated_db)
    assert final_run is not None
    assert final_run.status == "completed", final_run.error
    report = store.get_latest_report(run_id, db_path=isolated_db)
    assert report is not None
    final_ids = {
        str(row["id"])
        for row in store.list_hypotheses(run_id, db_path=isolated_db)
    }
    # The drain (engine_adapter.drain.persist_final_state) writes each
    # hypothesis under its own engine-assigned id, so this is a genuine
    # identity check, not just a non-empty-pool one.
    assert pool_before <= final_ids

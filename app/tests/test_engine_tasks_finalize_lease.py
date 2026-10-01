"""Regression guard for the b82f9162 finalize-lease incident (2026-09-06).

Finalize's claim-grounding wave used to run synchronously on the durable
task's own event loop, which starved ``task_worker._heartbeat_lease`` for
the wave's whole duration -- a healthy finalize task lost its lease and its
retry budget under a real production ultra run.
``drain_claim_grounding._assess_claims`` now runs that wave off the loop
(``async_bridge.run_off_loop``) so the heartbeat keeps renewing while it
runs; see the root AGENTS.md lease/heartbeat Gotcha.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from co_scientist.models import Article, Hypothesis

from app import engine_tasks, store, task_worker
from app.engine_adapter import drain_claim_grounding
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_restore_generator,
    _seed_checkpoint,
    _task_state,
)


def _seed_finalize_task(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> Any:
    """Seed a groundable finalize task, mirroring the dispatch fixture."""
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
    )
    state = _task_state(run_id)
    state["hypotheses"] = [hypothesis]
    state["articles"] = [
        Article(
            title="Synaptic energetics",
            url="https://example.org/synaptic",
            abstract="Astrocyte lactate accelerates synaptic ATP recovery.",
        )
    ]
    _seed_checkpoint(run_id, state, db_path=db_path)
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=engine_tasks.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=db_path,
    )
    _patch_restore_generator(monkeypatch, _Generator(state))
    return task


def _count_lease_renewals(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Patch ``store.renew_task_lease`` with a counter, return the counter.

    Mirrors ``test_task_worker_leases._count_lease_renewals``.
    """
    box = {"renewals": 0}
    real_renew = store.renew_task_lease

    def _renew(*args: Any, **kwargs: Any) -> bool:
        box["renewals"] += 1
        return real_renew(*args, **kwargs)

    monkeypatch.setattr(store, "renew_task_lease", _renew)
    return box


@pytest.mark.asyncio
async def test_finalize_lease_survives_a_slow_grounding_wave(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grounding wave that outlives the lease interval still renews it.

    ``assess_hypothesis_claims`` is patched to a real (fast) call wrapped in
    a deliberate blocking ``time.sleep`` -- reproducing the incident's
    shape, a synchronous provider wave -- with the lease interval shrunk
    far below that sleep (``renew_every = lease_seconds / 3`` is well under
    it). The discriminator is the heartbeat's renewal count, not merely
    "the task eventually completes": awaiting a coroutine that resolves
    with no real suspension point (as a broken, on-loop wave would) never
    hands control back to the event loop at all, so the whole task runs to
    completion in one synchronous stretch and a competing worker never even
    gets to *try* claiming it -- that would pass a weaker assertion for the
    wrong reason. A live heartbeat renewing during the wave is the fix's
    actual, positive signature.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _seed_finalize_task(run.id, monkeypatch, isolated_db)
    renewals = _count_lease_renewals(monkeypatch)

    real_assess = (
        drain_claim_grounding.assess_hypothesis_claims  # type: ignore[attr-defined]
    )
    sleep_seconds = 0.3

    def _slow_assess(*args: Any, **kwargs: Any) -> Any:
        time.sleep(sleep_seconds)
        return real_assess(*args, **kwargs)

    monkeypatch.setattr(
        drain_claim_grounding, "assess_hypothesis_claims", _slow_assess
    )

    completed = await task_worker.run_once(
        "worker-a", db_path=isolated_db, lease_seconds=0.06
    )

    assert completed
    # A blocked loop still fires exactly one belated "catch up" renewal the
    # instant it finally regains control after the wave -- so ">= 1" alone
    # would not catch a regression. A live heartbeat renews on its own
    # schedule *throughout* the 0.3s wave (renew_every ~= 0.02s here), which
    # is several renewals, not one; measured fixed=6 vs. broken=1.
    assert renewals["renewals"] >= 3, (
        "the lease heartbeat barely renewed during the grounding wave -- "
        "the wave is blocking the task's event loop again"
    )
    persisted_run = store.get_run(run.id, db_path=isolated_db)
    assert persisted_run is not None
    assert persisted_run.status == "completed"
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "completed"

"""Tests for the guards that overrule a Supervisor allocation.

``_resolve_planner_decision`` substitutes the deterministic baseline when the
model repeats a task without a work-cycle advance, or asks to grow the pool
after the iteration budget is spent. Both are statements about the *next
task*; the proposal's queue actions -- the only automatic route back for a
failed durable row -- must survive either substitution.
"""

from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.supervisor import supervisor_decision
from co_scientist.scheduling import Budget, SchedulerStats, TaskType
from co_scientist.state import WorkflowState
from tests._state import make_state

_RETRY = {
    "action": "retry",
    "task_id": "task-9",
    "reason": "Transient provider failure.",
}


def _state() -> WorkflowState:
    """A state whose durable queue holds one failed row to revive."""
    return make_state(
        research_goal="Find a testable mechanism.",
        supervisor_model_name="test/model",
        run_id="run-1",
        supervisor_guidance={"workflow_plan": {}},
        task_history=[],
        meta_review={},
        pending_steering=False,
        held_for_review=[],
        durable_task_queue=[
            {
                "task_id": "task-9",
                "task_type": "engine.fanout.review.item",
                "status": "failed",
                "error": "provider unavailable",
            }
        ],
    )


def _allocating(task: str) -> Any:
    """Build a planner stub asking for ``task`` plus the failed row's retry."""

    async def _allocation(**_kwargs: Any) -> dict[str, Any]:
        return {
            "next_task": task,
            "reason": "Revive the failed row and keep working.",
            "queue_actions": [dict(_RETRY)],
        }

    return _allocation


@pytest.mark.asyncio
async def test_post_budget_growth_guard_still_delivers_the_queue_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The terminal drain must not strand the revival it just asked for.

    ``stats.iteration`` never decreases, so this guard's condition holds for
    every remaining loop point. Discarding the action here therefore discarded
    it for the rest of the run: measured over the real loop, 60 of 60 planning
    calls in the drain carried a revival and none of them landed.
    """
    monkeypatch.setattr(
        supervisor_decision, "call_llm_json", _allocating("generate")
    )
    stats = SchedulerStats(
        pool_size=8,
        reviewed_count=6,
        unreviewed_count=2,
        rankable_count=8,
        iteration=2,
    )

    decision, provenance, _ = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=2)
    )

    # The guard still owns the next task: growth is refused.
    assert decision.next_task is not TaskType.GENERATE
    assert provenance == "hard-invariant"
    assert decision.queue_actions == (_RETRY,)


@pytest.mark.asyncio
async def test_non_progress_guard_still_delivers_the_queue_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refusing a repeated pass must not also refuse the queue action."""
    monkeypatch.setattr(
        supervisor_decision, "call_llm_json", _allocating("proximity")
    )
    state = _state()
    state["task_history"] = [
        {
            "task_type": "proximity",
            "status": "queued",
            "reason": "First proximity refresh.",
            "iteration": 1,
        }
    ]
    stats = SchedulerStats(
        pool_size=8,
        reviewed_count=8,
        rankable_count=8,
        total_matches=16,
        match_coverage=2.0,
        iteration=1,
        last_work_task=TaskType.GENERATE,
    )

    decision, provenance, _ = await supervisor_decision.choose_supervisor_task(
        state, stats, Budget(max_iterations=4)
    )

    assert decision.next_task is not TaskType.PROXIMITY
    assert provenance == "hard-invariant"
    assert decision.queue_actions == (_RETRY,)


@pytest.mark.asyncio
async def test_guard_without_queue_actions_returns_the_baseline_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty proposal leaves the baseline decision untouched."""
    monkeypatch.setattr(
        supervisor_decision, "call_llm_json", _allocating("generate")
    )

    async def _no_actions(**_kwargs: Any) -> dict[str, Any]:
        return {"next_task": "generate", "reason": "Grow the pool."}

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _no_actions)
    stats = SchedulerStats(
        pool_size=8,
        reviewed_count=6,
        unreviewed_count=2,
        rankable_count=8,
        iteration=2,
    )

    decision, provenance, _ = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=2)
    )

    assert provenance == "hard-invariant"
    assert decision.queue_actions == ()

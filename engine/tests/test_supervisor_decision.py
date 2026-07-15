"""Tests for model-directed Supervisor task allocation."""

from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.supervisor import supervisor_decision
from co_scientist.scheduling import Budget, SchedulerStats, TaskType
from co_scientist.state import WorkflowState


def _state() -> WorkflowState:
    return {  # type: ignore[typeddict-item]
        "research_goal": "Find a testable mechanism.",
        "supervisor_model_name": "test/model",
        "run_id": "run-1",
        "supervisor_guidance": {"workflow_plan": {}},
        "task_history": [],
        "meta_review": {},
        "pending_steering": False,
        "held_for_review": [],
    }


@pytest.mark.asyncio
async def test_model_selects_productive_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid model allocation controls the next productive task."""

    async def _allocation(**_kwargs: Any) -> dict[str, Any]:
        return {
            "next_task": "evolve",
            "reason": "Improve mature leaders.",
            "priority": "73",
            "queue_actions": [
                {
                    "action": "reprioritize",
                    "task_id": "task-1",
                    "priority": 88,
                    "reason": "Evidence gap is urgent.",
                }
            ],
        }

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _allocation)
    stats = SchedulerStats(pool_size=4, reviewed_count=4, iteration=1)
    decision, provenance = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=4)
    )
    assert decision.next_task is TaskType.EVOLVE
    assert decision.priority == 73
    assert decision.queue_actions[0]["task_id"] == "task-1"
    assert provenance == "model"


@pytest.mark.asyncio
async def test_hard_budget_stop_bypasses_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model cannot schedule work after a hard compute limit."""

    async def _unexpected(**_kwargs: Any) -> dict[str, str]:
        raise AssertionError("model must not be called")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _unexpected)
    stats = SchedulerStats(
        pool_size=4, reviewed_count=4, iteration=1, llm_calls=10
    )
    decision, provenance = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=4, max_llm_calls=10)
    )
    assert decision.terminate
    assert provenance == "hard-invariant"


@pytest.mark.asyncio
async def test_iteration_budget_blocks_model_directed_pool_growth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model cannot evolve again while terminal review work remains."""

    async def _allocation(**_kwargs: Any) -> dict[str, str]:
        return {
            "next_task": "evolve",
            "reason": "Keep expanding the pool.",
        }

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _allocation)
    stats = SchedulerStats(
        pool_size=8,
        reviewed_count=7,
        unreviewed_count=1,
        iteration=2,
    )

    decision, provenance = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=2)
    )

    assert decision.next_task is TaskType.REFLECT
    assert provenance == "hard-invariant"


@pytest.mark.asyncio
async def test_provider_failure_records_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider failure remains recoverable and auditable."""

    async def _failed(**_kwargs: Any) -> dict[str, str]:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _failed)
    stats = SchedulerStats(pool_size=1, reviewed_count=1, iteration=0)
    decision, provenance = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=4)
    )
    assert decision.next_task is TaskType.GENERATE
    assert provenance == "reconstructed-fallback"


@pytest.mark.asyncio
async def test_scientist_steering_reprioritizes_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User feedback overrides a lower-value model allocation immediately."""

    async def _allocation(**_kwargs: Any) -> dict[str, Any]:
        return {
            "next_task": "reflect",
            "reason": "Continue reviewing the existing pool.",
            "priority": 20,
        }

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _allocation)
    state = _state()
    state["pending_steering"] = True
    decision, provenance = await supervisor_decision.choose_supervisor_task(
        state,
        SchedulerStats(
            pool_size=4,
            reviewed_count=4,
            iteration=1,
            pending_steering=True,
        ),
        Budget(max_iterations=4),
    )

    assert decision.next_task is TaskType.GENERATE
    assert decision.priority == 100
    assert provenance == "model"


@pytest.mark.asyncio
async def test_repeated_maintenance_cannot_stall_iteration_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model cannot repeat a no-progress reflection loop indefinitely."""

    async def _allocation(**_kwargs: Any) -> dict[str, str]:
        return {
            "next_task": "reflect",
            "reason": "Run reflection again without new work.",
        }

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _allocation)
    state = _state()
    state["task_history"] = [
        {
            "task_type": "reflect",
            "status": "queued",
            "reason": "First reflection pass.",
            "iteration": 0,
        }
    ]
    stats = SchedulerStats(
        pool_size=8,
        reviewed_count=8,
        unreviewed_count=0,
        total_matches=16,
        match_coverage=2.0,
        iteration=0,
        last_work_task=TaskType.GENERATE,
    )

    decision, provenance = await supervisor_decision.choose_supervisor_task(
        state, stats, Budget(max_iterations=2)
    )

    assert decision.next_task is TaskType.EVOLVE
    assert provenance == "hard-invariant"

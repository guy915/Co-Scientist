"""Tests for model-directed Supervisor task allocation."""

from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.supervisor import supervisor_decision
from co_scientist.scheduling import Budget, SchedulerStats, TaskType
from co_scientist.state import WorkflowState
from tests._state import make_state


def _state() -> WorkflowState:
    return make_state(
        research_goal="Find a testable mechanism.",
        supervisor_model_name="test/model",
        run_id="run-1",
        supervisor_guidance={"workflow_plan": {}},
        task_history=[],
        meta_review={},
        pending_steering=False,
        held_for_review=[],
    )


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

    # The backlog is a required transition, so this is now settled before
    # the model is asked rather than by overruling its answer.
    assert decision.next_task is TaskType.REFLECT
    assert provenance == "required-transition"


@pytest.mark.asyncio
async def test_provider_failure_records_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider failure remains recoverable and auditable."""

    async def _failed(**_kwargs: Any) -> dict[str, str]:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _failed)
    # Open choice: no required transition fires, so the model is consulted
    # and its failure is what the fallback has to absorb.
    stats = SchedulerStats(pool_size=4, reviewed_count=4, iteration=1)
    decision, provenance = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=4)
    )
    assert decision.next_task is TaskType.EVOLVE
    assert provenance == "reconstructed-fallback"


@pytest.mark.asyncio
async def test_scientist_steering_reprioritizes_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User feedback preempts the planning call, not just its answer."""

    async def _unexpected(**_kwargs: Any) -> dict[str, str]:
        raise AssertionError("model must not be called")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _unexpected)
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
    assert provenance == "required-transition"


@pytest.mark.asyncio
async def test_review_backlog_skips_the_planning_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreviewed backlog is forced work, so it costs no model call."""

    async def _unexpected(**_kwargs: Any) -> dict[str, str]:
        raise AssertionError("model must not be called")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _unexpected)
    stats = SchedulerStats(
        pool_size=8, reviewed_count=5, unreviewed_count=3, iteration=1
    )

    decision, provenance = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=4)
    )

    assert decision.next_task is TaskType.REFLECT
    assert provenance == "required-transition"


@pytest.mark.asyncio
async def test_small_pool_skips_the_planning_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pool too small to rank leaves nothing for a model to decide."""

    async def _unexpected(**_kwargs: Any) -> dict[str, str]:
        raise AssertionError("model must not be called")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _unexpected)
    stats = SchedulerStats(pool_size=1, reviewed_count=1, iteration=0)

    decision, provenance = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=4)
    )

    assert decision.next_task is TaskType.GENERATE
    assert provenance == "required-transition"


@pytest.mark.asyncio
async def test_proximity_refresh_skips_the_planning_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A grown pool must re-cluster before anything else is worth choosing."""

    async def _unexpected(**_kwargs: Any) -> dict[str, str]:
        raise AssertionError("model must not be called")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _unexpected)
    stats = SchedulerStats(
        pool_size=6,
        reviewed_count=6,
        rankable_count=6,
        total_matches=12,
        match_coverage=2.0,
        pool_grew_since_proximity=True,
        iteration=1,
    )

    decision, provenance = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=4)
    )

    assert decision.next_task is TaskType.PROXIMITY
    assert provenance == "required-transition"


@pytest.mark.asyncio
async def test_failed_durable_task_still_consults_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed task is revived only by a model queue action, so ask.

    The forced transition is still returned, but skipping the call would
    strand the failed row: nothing automatic requeues it.
    """
    calls: list[str] = []

    async def _allocation(**_kwargs: Any) -> dict[str, Any]:
        calls.append("planning")
        return {
            "next_task": "reflect",
            "reason": "Review the backlog and retry the failed task.",
            "queue_actions": [
                {
                    "action": "retry",
                    "task_id": "task-9",
                    "reason": "Transient provider failure.",
                }
            ],
        }

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _allocation)
    state = _state()
    state["durable_task_queue"] = [
        {
            "task_id": "task-9",
            "task_type": "engine.node.review",
            "status": "failed",
            "error": "provider unavailable",
        }
    ]
    stats = SchedulerStats(
        pool_size=8, reviewed_count=5, unreviewed_count=3, iteration=1
    )

    decision, provenance = await supervisor_decision.choose_supervisor_task(
        state, stats, Budget(max_iterations=4)
    )

    assert calls == ["planning"]
    assert decision.next_task is TaskType.REFLECT
    assert decision.queue_actions[0]["action"] == "retry"
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

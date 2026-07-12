"""Tests for model-directed Supervisor task allocation."""

from __future__ import annotations

from typing import Any

import pytest

from co_scientist.nodes import supervisor_decision
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

    async def _allocation(**_kwargs: Any) -> dict[str, str]:
        return {"next_task": "evolve", "reason": "Improve mature leaders."}

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _allocation)
    stats = SchedulerStats(pool_size=4, reviewed_count=4, iteration=1)
    decision, provenance = await supervisor_decision.choose_supervisor_task(
        _state(), stats, Budget(max_iterations=4)
    )
    assert decision.next_task is TaskType.EVOLVE
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

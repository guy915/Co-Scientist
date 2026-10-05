from __future__ import annotations

import json
from typing import Any

import pytest

from co_scientist.agents.supervisor import supervisor, supervisor_decision
from co_scientist.agents.supervisor.supervisor import supervisor_node
from co_scientist.llm import call as llm_call
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
)
from co_scientist.state import WorkflowState
from tests._llm_fake import mock_call_llm_json, stub_call_llm_json
from tests._state import make_allocation_response, make_state


async def test_guidance_carries_response_subobjects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "research_goal_analysis": {
            "summary": "study alpha pathway",
            "key_areas": ["a", "b"],
        },
        "workflow_plan": {"iterations": 3},
        "config_synthesis": {
            "preferences": ["testable within 2 years"],
            "review_instructions": ["check the assay measures the claim"],
            "attributes": [
                {"name": "Feasibility", "rubric": "1 impossible .. 5 routine"}
            ],
        },
        "performance_assessment": {"status": "on track"},
        "adjustment_recommendations": ["broaden search"],
        "output_preparation": {"format": "ranked list"},
    }
    stub_call_llm_json(monkeypatch, supervisor, response)

    result = await supervisor_node(make_state())

    guidance = result["supervisor_guidance"]
    for key in (
        "research_goal_analysis",
        "workflow_plan",
        "config_synthesis",
        "performance_assessment",
        "adjustment_recommendations",
        "output_preparation",
    ):
        assert guidance[key] == response[key]
    assert result["metrics"] is not None
    assert result["metrics"].llm_calls == 1
    assert result["messages"][0]["metadata"]["phase"] == "supervisor"


def _supervisor_decision_state() -> WorkflowState:
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


def _stub_allocation(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> None:
    stub_call_llm_json(monkeypatch, supervisor_decision, response)


def _forbid_allocation(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_call_llm_json(
        monkeypatch,
        supervisor_decision,
        side_effect=AssertionError("model must not be called"),
    )


@pytest.mark.asyncio
async def test_model_selects_productive_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    _stub_allocation(
        monkeypatch,
        make_allocation_response(
            "evolve",
            "Improve mature leaders.",
            priority="73",
            queue_actions=[
                {
                    "action": "reprioritize",
                    "task_id": "task-1",
                    "priority": 88,
                    "reason": "Evidence gap is urgent.",
                }
            ],
        ),
    )
    stats = SchedulerStats(pool_size=4, reviewed_count=4, iteration=1)
    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        _supervisor_decision_state(), stats, Budget(max_iterations=4)
    )
    assert decision.next_task is TaskType.EVOLVE
    assert decision.priority == 73
    assert decision.queue_actions[0]["task_id"] == "task-1"
    assert provenance == "model"


@pytest.mark.asyncio
async def test_hard_budget_stop_bypasses_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    _forbid_allocation(monkeypatch)
    stats = SchedulerStats(
        pool_size=4, reviewed_count=4, iteration=1, llm_calls=10
    )
    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        _supervisor_decision_state(),
        stats,
        Budget(max_iterations=4, max_llm_calls=10),
    )
    assert decision.terminate
    assert provenance == "hard-invariant"


@pytest.mark.asyncio
async def test_iteration_budget_blocks_model_directed_pool_growth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    _stub_allocation(
        monkeypatch,
        make_allocation_response("evolve", "Keep expanding the pool."),
    )
    stats = SchedulerStats(
        pool_size=8,
        reviewed_count=7,
        unreviewed_count=1,
        iteration=2,
    )

    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        _supervisor_decision_state(), stats, Budget(max_iterations=2)
    )

    assert decision.next_task is TaskType.REFLECT
    assert provenance == "required-transition"


@pytest.mark.asyncio
async def test_provider_failure_records_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    mock_call_llm_json(
        monkeypatch,
        supervisor_decision,
        side_effect=RuntimeError("provider unavailable"),
    )
    stats = SchedulerStats(pool_size=4, reviewed_count=4, iteration=1)
    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        _supervisor_decision_state(), stats, Budget(max_iterations=4)
    )
    assert decision.next_task is TaskType.GENERATE
    assert provenance == "reconstructed-fallback"


@pytest.mark.asyncio
async def test_scientist_steering_reprioritizes_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    _forbid_allocation(monkeypatch)
    state = _supervisor_decision_state()
    state["pending_steering"] = True
    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
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
@pytest.mark.parametrize(
    ("stats", "task"),
    [
        (
            SchedulerStats(
                pool_size=8, reviewed_count=5, unreviewed_count=3, iteration=1
            ),
            TaskType.REFLECT,
        ),
        (
            SchedulerStats(pool_size=1, reviewed_count=1, iteration=0),
            TaskType.GENERATE,
        ),
        (
            SchedulerStats(
                pool_size=6,
                reviewed_count=6,
                rankable_count=6,
                total_matches=12,
                match_coverage=2.0,
                pool_grew_since_proximity=True,
                iteration=1,
            ),
            TaskType.PROXIMITY,
        ),
    ],
    ids=["review_backlog", "small_pool", "proximity_refresh"],
)
async def test_required_transitions_skip_the_planning_call(
    monkeypatch: pytest.MonkeyPatch, stats: SchedulerStats, task: TaskType
) -> None:
    _forbid_allocation(monkeypatch)

    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        _supervisor_decision_state(), stats, Budget(max_iterations=4)
    )

    assert decision.next_task is task
    assert provenance == "required-transition"


@pytest.mark.asyncio
async def test_failed_durable_task_still_consults_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only model queue actions revive failed rows; skipping allocation
    strands them."""
    calls: list[str] = []

    async def _allocation(**_kwargs: Any) -> dict[str, Any]:
        calls.append("planning")
        return make_allocation_response(
            "reflect",
            "Review the backlog and retry the failed task.",
            queue_actions=[
                {
                    "action": "retry",
                    "task_id": "task-9",
                    "reason": "Transient provider failure.",
                }
            ],
        )

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _allocation)
    state = _supervisor_decision_state()
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

    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        state, stats, Budget(max_iterations=4)
    )

    assert calls == ["planning"]
    assert decision.next_task is TaskType.REFLECT
    assert decision.queue_actions[0]["action"] == "retry"
    assert provenance == "model"


@pytest.mark.asyncio
async def test_corrected_allocation_still_delivers_the_queue_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated rank correction must not discard the failed row's only
    revival path."""
    retry = {"action": "retry", "task_id": "task-9", "reason": "Transient."}

    _stub_allocation(
        monkeypatch,
        make_allocation_response(
            "rank",
            "Rank once the failed match is revived.",
            queue_actions=[retry],
        ),
    )
    state = _supervisor_decision_state()
    state["durable_task_queue"] = [
        {"task_id": "task-9", "status": "failed", "error": "unavailable"}
    ]
    stats = SchedulerStats(
        pool_size=6, reviewed_count=6, rankable_count=1, iteration=1
    )

    decision, _, _ = await supervisor_decision.choose_supervisor_task(
        state, stats, Budget(max_iterations=4)
    )

    assert decision.next_task is TaskType.GENERATE
    assert "corrected" in decision.reason
    assert decision.queue_actions[0]["task_id"] == "task-9"


@pytest.mark.asyncio
async def test_allocation_runs_on_the_worker_model_with_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def _allocation(**kwargs: Any) -> dict[str, str]:
        seen.update(kwargs)
        return make_allocation_response("evolve", "Improve leaders.")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _allocation)
    state = _supervisor_decision_state()
    stats = SchedulerStats(pool_size=4, reviewed_count=4, iteration=1)

    _, provenance, _ = await supervisor_decision.choose_supervisor_task(
        state, stats, Budget(max_iterations=4)
    )

    assert provenance == "model"
    assert seen["spec"].model_name == state["model_name"]
    assert seen["spec"].model_name != state["supervisor_model_name"]
    assert seen["options"].enable_thinking is True
    # Identical live-state prompts recur; allocation must never replay from
    # cache.
    assert seen["options"].use_cache is False


@pytest.mark.asyncio
async def test_repeated_maintenance_cannot_stall_iteration_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    _stub_allocation(
        monkeypatch,
        make_allocation_response(
            "reflect", "Run reflection again without new work."
        ),
    )
    state = _supervisor_decision_state()
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

    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        state, stats, Budget(max_iterations=2)
    )

    assert decision.next_task is TaskType.GENERATE
    assert provenance == "hard-invariant"


_RETRY = {
    "action": "retry",
    "task_id": "task-9",
    "reason": "Transient provider failure.",
}


def _supervisor_decision_guards_state() -> WorkflowState:
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

    async def _allocation(**_kwargs: Any) -> dict[str, Any]:
        return make_allocation_response(
            task,
            "Revive the failed row and keep working.",
            queue_actions=[dict(_RETRY)],
        )

    return _allocation


@pytest.mark.asyncio
async def test_post_budget_growth_guard_still_delivers_the_queue_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal-drain guard holds forever; dropping revival there strands
    the row permanently."""
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
        _supervisor_decision_guards_state(), stats, Budget(max_iterations=2)
    )

    assert decision.next_task is not TaskType.GENERATE
    assert provenance == "hard-invariant"
    assert decision.queue_actions == (_RETRY,)


@pytest.mark.asyncio
async def test_non_progress_guard_still_delivers_the_queue_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        supervisor_decision, "call_llm_json", _allocating("proximity")
    )
    state = _supervisor_decision_guards_state()
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


def test_hard_stop_yields_to_owed_coverage_but_not_to_safety() -> None:
    from co_scientist.agents.supervisor.supervisor_decision import _hard_stop
    from co_scientist.scheduling import (
        Budget,
        SchedulerStats,
        SupervisorDecision,
        TaskType,
    )

    budget = Budget(max_iterations=5, max_llm_calls=10)
    settling = SupervisorDecision(next_task=TaskType.RANK, reason="settle")
    stats = SchedulerStats(
        pool_size=6,
        rankable_count=6,
        unmatched_rankable_count=2,
        owed_coverage_rounds=2,
        llm_calls=99,
    )

    assert _hard_stop(stats, budget, settling) is None

    blocked = SchedulerStats(
        pool_size=6,
        rankable_count=6,
        unmatched_rankable_count=2,
        owed_coverage_rounds=2,
        llm_calls=99,
        safety_blocked=True,
    )
    stop = _hard_stop(blocked, budget, settling)

    assert stop is not None
    assert stop.next_task is TaskType.TERMINATE


def test_hard_stop_deferral_reads_the_allowance_not_the_baseline() -> None:
    """A model can choose a non-rank task; the allowance must bound deferral
    on that path."""
    from co_scientist.agents.supervisor.supervisor_decision import _hard_stop
    from co_scientist.scheduling import (
        Budget,
        SchedulerStats,
        SupervisorDecision,
        TaskType,
        TerminationReason,
    )

    budget = Budget(max_iterations=5, max_llm_calls=10)
    reflecting = SupervisorDecision(
        next_task=TaskType.REFLECT, reason="review backlog"
    )
    owed = SchedulerStats(
        pool_size=6,
        rankable_count=6,
        unmatched_rankable_count=2,
        owed_coverage_rounds=2,
        llm_calls=99,
    )

    assert _hard_stop(owed, budget, reflecting) is None

    spent = SchedulerStats(
        pool_size=6,
        rankable_count=6,
        unmatched_rankable_count=2,
        owed_coverage_rounds=2,
        settlement_allowance=0,
        llm_calls=99,
    )
    stop = _hard_stop(
        spent,
        budget,
        SupervisorDecision(next_task=TaskType.RANK, reason="settle"),
    )

    assert stop is not None
    assert stop.termination_reason is TerminationReason.BUDGET


def test_hard_stop_enforces_max_ideas_ahead_of_the_model() -> None:
    from co_scientist.agents.supervisor.supervisor_decision import _hard_stop
    from co_scientist.scheduling import (
        Budget,
        SchedulerStats,
        SupervisorDecision,
        TaskType,
        TerminationReason,
    )

    budget = Budget(max_iterations=5, max_ideas=10)
    baseline = SupervisorDecision(next_task=TaskType.GENERATE, reason="grow")
    at_ceiling = SchedulerStats(pool_size=10, unreviewed_count=0)

    stop = _hard_stop(at_ceiling, budget, baseline)

    assert stop is not None
    assert stop.termination_reason is TerminationReason.MAX_IDEAS

    with_backlog = SchedulerStats(pool_size=10, unreviewed_count=2)
    assert _hard_stop(with_backlog, budget, baseline) is None


def test_hard_stop_enforces_max_matches_per_idea_ahead_of_the_model() -> None:
    from co_scientist.agents.supervisor.supervisor_decision import _hard_stop
    from co_scientist.scheduling import (
        Budget,
        SchedulerStats,
        SupervisorDecision,
        TaskType,
        TerminationReason,
    )

    budget = Budget(max_iterations=5, max_matches_per_idea=3.0)
    baseline = SupervisorDecision(next_task=TaskType.RANK, reason="rank")
    at_ceiling = SchedulerStats(rankable_count=6, match_coverage=3.0)

    stop = _hard_stop(at_ceiling, budget, baseline)

    assert stop is not None
    assert stop.termination_reason is TerminationReason.MAX_MATCHES_PER_IDEA


# This model lacks native schema support; these constraints must hold locally.
_JSON_OBJECT_MODEL = "deepseek/deepseek-v4-flash"


def _allocation_text(**queue_action: Any) -> str:
    return json.dumps(
        make_allocation_response(
            "evolve",
            "Improve mature leaders.",
            queue_actions=[
                {
                    "action": "reprioritize",
                    "task_id": "task-1",
                    "reason": "Evidence gap is urgent.",
                    **queue_action,
                }
            ],
        )
    )


async def _allocate(
    monkeypatch: pytest.MonkeyPatch,
    raw_response: str,
    model: str = _JSON_OBJECT_MODEL,
) -> tuple[SupervisorDecision, str, list[str]]:
    prompts: list[str] = []

    async def _fake_call(
        prompt: str, spec: Any, enable_thinking: bool = True
    ) -> str:
        prompts.append(prompt)
        return raw_response

    monkeypatch.setattr(llm_call, "_call_llm_for_json", _fake_call)
    state = make_state(
        research_goal="Find a testable mechanism.",
        model_name=model,
        supervisor_model_name=model,
        run_id="run-1",
        supervisor_guidance={"workflow_plan": {}},
        task_history=[],
        meta_review={},
        pending_steering=False,
        held_for_review=[],
    )
    decision, provenance, _ = await supervisor_decision.choose_supervisor_task(
        state,
        SchedulerStats(pool_size=4, reviewed_count=4, iteration=1),
        Budget(max_iterations=4),
    )
    return decision, provenance, prompts


@pytest.mark.asyncio
async def test_in_range_queue_action_priority_reaches_the_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision, provenance, prompts = await _allocate(
        monkeypatch, _allocation_text(priority=88)
    )

    assert provenance == "model"
    assert decision.next_task is TaskType.EVOLVE
    assert decision.queue_actions[0]["priority"] == 88
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_out_of_range_queue_action_priority_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision, provenance, prompts = await _allocate(
        monkeypatch, _allocation_text(priority=999)
    )

    assert provenance == "reconstructed-fallback"
    assert decision.queue_actions == ()
    assert len(prompts) == 5
    assert "VALIDATION ERROR" in prompts[1]
    assert "maximum" in prompts[1]


@pytest.mark.asyncio
async def test_missing_next_task_is_backfilled_on_json_object_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON-object backfill uses the first enum, potentially attributing a
    decision never made."""
    first_of_enum = supervisor_decision._PRODUCTIVE_TASKS[0]
    decision, provenance, prompts = await _allocate(
        monkeypatch, json.dumps({"reason": "No next_task field at all."})
    )

    assert provenance == "model"
    assert decision.next_task is first_of_enum
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_queue_action_required_fields_are_not_backfilled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backfill stops at non-dicts and cannot fill required fields inside
    queue-action arrays."""
    body = make_allocation_response(
        "evolve",
        "Improve mature leaders.",
        queue_actions=[{"action": "cancel", "reason": "Superseded."}],
    )
    decision, provenance, _ = await _allocate(monkeypatch, json.dumps(body))

    assert provenance == "reconstructed-fallback"
    assert decision.queue_actions == ()

"""Offline contracts for supervisor."""

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
from tests._llm_fake import stub_call_llm_json
from tests._state import make_state


async def test_guidance_carries_response_subobjects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each response sub-object is copied verbatim into supervisor_guidance."""
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
    # Every response sub-object is carried into guidance verbatim.
    for key in (
        "research_goal_analysis",
        "workflow_plan",
        "config_synthesis",
        "performance_assessment",
        "adjustment_recommendations",
        "output_preparation",
    ):
        assert guidance[key] == response[key]
    # Metrics update is always emitted (one LLM call this node).
    assert result["metrics"] is not None
    assert result["metrics"].llm_calls == 1


async def test_missing_response_fields_default_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty response yields guidance with empty defaults, not a crash."""
    stub_call_llm_json(monkeypatch, supervisor, {})

    result = await supervisor_node(make_state())

    guidance = result["supervisor_guidance"]
    assert guidance["research_goal_analysis"] == {}
    assert guidance["workflow_plan"] == {}
    assert guidance["config_synthesis"] == {}
    assert guidance["performance_assessment"] == {}
    assert guidance["adjustment_recommendations"] == []
    assert guidance["output_preparation"] == {}


async def test_list_research_goal_analysis_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A list research_goal_analysis falls back to empty key_areas safely.

    The node only reads ``key_areas`` when the analysis is a dict; a list must
    pass through the logging guard without raising and still be carried in the
    guidance unchanged.
    """
    analysis = ["area one", "area two"]
    stub_call_llm_json(
        monkeypatch, supervisor, {"research_goal_analysis": analysis}
    )

    result = await supervisor_node(make_state())

    guidance = result["supervisor_guidance"]
    assert guidance["research_goal_analysis"] == analysis
    # key_areas falls back to empty, so the message metadata reports zero.
    assert result["messages"][0]["metadata"]["key_areas"] == 0


async def test_key_areas_feed_message_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Present key_areas are counted into the emitted message metadata."""
    stub_call_llm_json(
        monkeypatch,
        supervisor,
        {
            "research_goal_analysis": {
                "key_areas": ["alpha", "beta", "gamma", "delta"],
            }
        },
    )

    result = await supervisor_node(make_state())

    assert result["supervisor_guidance"]["research_goal_analysis"][
        "key_areas"
    ] == ["alpha", "beta", "gamma", "delta"]
    message = result["messages"][0]
    assert message["metadata"]["phase"] == "supervisor"
    assert message["metadata"]["key_areas"] == 4


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
    """A model cannot schedule work after a hard compute limit."""

    async def _unexpected(**_kwargs: Any) -> dict[str, str]:
        raise AssertionError("model must not be called")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _unexpected)
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

    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        _supervisor_decision_state(), stats, Budget(max_iterations=2)
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
    # and its failure is what the fallback has to absorb. Default stats are a
    # yield tie with no measured leaderboard stagnation, so the deterministic
    # fallback generates.
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
    """User feedback preempts the planning call, not just its answer."""

    async def _unexpected(**_kwargs: Any) -> dict[str, str]:
        raise AssertionError("model must not be called")

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _unexpected)
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

    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        _supervisor_decision_state(), stats, Budget(max_iterations=4)
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

    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        _supervisor_decision_state(), stats, Budget(max_iterations=4)
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

    (
        decision,
        provenance,
        _,
    ) = await supervisor_decision.choose_supervisor_task(
        _supervisor_decision_state(), stats, Budget(max_iterations=4)
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
    """Correcting the next task must not discard the failed row's revival.

    An unrankable pool invites the model to keep asking for RANK, so the rank
    correction fires on every round with these stats. The action is the failed
    row's only route back, so dropping it stranded it for as long as the pool
    stayed unrankable rather than for one loop point.
    """
    retry = {"action": "retry", "task_id": "task-9", "reason": "Transient."}

    async def _allocation(**_kwargs: Any) -> dict[str, Any]:
        return {
            "next_task": "rank",
            "reason": "Rank once the failed match is revived.",
            "queue_actions": [retry],
        }

    monkeypatch.setattr(supervisor_decision, "call_llm_json", _allocation)
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
    """Allocation reasons, on the worker model, uncached."""
    seen: dict[str, Any] = {}

    async def _allocation(**kwargs: Any) -> dict[str, str]:
        seen.update(kwargs)
        return {"next_task": "evolve", "reason": "Improve leaders."}

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
    # Allocation must never be served from cache: it is a decision about
    # live state, and identical prompts recur across loop points.
    assert seen["options"].use_cache is False


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

    # A yield tie with no measured leaderboard stagnation (rank_stable_cycles
    # defaults to 0) falls back to GENERATE; the invariant under test is that
    # the model's repeated "reflect" is overruled, not the specific baseline
    # task, so this only needs to match whatever the deterministic policy
    # picks for these stats.
    assert decision.next_task is TaskType.GENERATE
    assert provenance == "hard-invariant"


_RETRY = {
    "action": "retry",
    "task_id": "task-9",
    "reason": "Transient provider failure.",
}


def _supervisor_decision_guards_state() -> WorkflowState:
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
        _supervisor_decision_guards_state(), stats, Budget(max_iterations=2)
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
        _supervisor_decision_guards_state(), stats, Budget(max_iterations=2)
    )

    assert provenance == "hard-invariant"
    assert decision.queue_actions == ()


def test_hard_stop_yields_to_owed_coverage_but_not_to_safety() -> None:
    """_hard_stop defers budget stops when coverage remains, but not safety.

    _hard_stop runs after required_transition, so without this the RANK the
    policy just chose is overridden and the feature never reaches a run.
    """
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
    """The deferral is bounded by the allowance on any baseline task.

    _needs_queue_adjudication can route past the forced decision, and the
    model may then answer with a task other than RANK -- which charges
    nothing, so a baseline-derived deferral had no bound on that path.
    """
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


def test_hard_stop_defers_for_an_under_covered_pool() -> None:
    """The deferral reads the same owed-rounds figure the scheduler does.

    _hard_stop runs before required_transition, so a pool that owes rounds
    without holding a single unmatched idea -- every idea at one match of the
    two -- was stopped here on the budget before the settlement round the
    scheduler was about to force could ever run.
    """
    from co_scientist.agents.supervisor.supervisor_decision import _hard_stop
    from co_scientist.scheduling import (
        Budget,
        SchedulerStats,
        SupervisorDecision,
        TaskType,
    )

    budget = Budget(max_iterations=5, max_llm_calls=10)
    settling = SupervisorDecision(next_task=TaskType.RANK, reason="settle")
    under_covered = SchedulerStats(
        pool_size=10,
        rankable_count=10,
        unmatched_rankable_count=0,
        owed_coverage_rounds=5,
        llm_calls=99,
    )

    assert _hard_stop(under_covered, budget, settling) is None


def test_hard_stop_enforces_max_ideas_ahead_of_the_model() -> None:
    """The MaxIdeas ceiling (F11) is a code-enforced stop, mirroring policy.

    ``_hard_stop_checks`` must carry the same predicate as
    ``policy_checks._max_ideas_check``: without it a model consulted for the
    open generate/evolve choice could keep growing a pool this run's own
    configured ceiling says is full.
    """
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

    # An unreviewed backlog still owed at the ceiling is not stopped here.
    with_backlog = SchedulerStats(pool_size=10, unreviewed_count=2)
    assert _hard_stop(with_backlog, budget, baseline) is None


def test_hard_stop_enforces_max_matches_per_idea_ahead_of_the_model() -> None:
    """The MaxMatchesPerIdea ceiling (F11) is a code-enforced stop."""
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


def test_stale_cancelled_flag_is_not_a_hard_stop() -> None:
    """A stray ``cancelled=True`` on stats is no longer code-enforced.

    ``SchedulerStats.cancelled`` is retained (the orchestrator still
    constructs it), but nothing in the scheduling policy reads it (F12).
    """
    from co_scientist.agents.supervisor.supervisor_decision import _hard_stop
    from co_scientist.scheduling import (
        Budget,
        SchedulerStats,
        SupervisorDecision,
        TaskType,
    )

    budget = Budget(max_iterations=5, max_llm_calls=10)
    baseline = SupervisorDecision(next_task=TaskType.GENERATE, reason="grow")
    stats = SchedulerStats(pool_size=6, cancelled=True)

    assert _hard_stop(stats, budget, baseline) is None


# A model whose profile states json_schema=False (DeepSeek), i.e. the
# production shape: the json_schema response format is unavailable, so
# whatever holds has to hold in-process.
_JSON_OBJECT_MODEL = "deepseek/deepseek-v4-flash"


def _allocation_text(**queue_action: Any) -> str:
    """Serialize a well-formed allocation carrying one queue action.

    Args:
        **queue_action: Fields to add to (or override on) the single
            ``reprioritize`` action, e.g. ``priority=999``.

    Returns:
        The raw JSON response text a model attempt would return.
    """
    return json.dumps(
        {
            "next_task": "evolve",
            "reason": "Improve mature leaders.",
            "queue_actions": [
                {
                    "action": "reprioritize",
                    "task_id": "task-1",
                    "reason": "Evidence gap is urgent.",
                    **queue_action,
                }
            ],
        }
    )


async def _allocate(
    monkeypatch: pytest.MonkeyPatch,
    raw_response: str,
    model: str = _JSON_OBJECT_MODEL,
) -> tuple[SupervisorDecision, str, list[str]]:
    """Run one allocation over the real call_llm_json parse/validate loop.

    Args:
        monkeypatch: Fixture used to install the raw-response seam.
        raw_response: The text every attempt's LLM call returns.
        model: Model name, which decides whether the json_object
            provider-capability shim applies.

    Returns:
        The decision, its provenance, and the prompt sent on each attempt
        (so a caller can assert on the retry count and its feedback).
    """
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
    """A schema-conforming queue action survives validation intact.

    The control for the two rejection tests below: without it they could
    both pass because the seam never delivered a usable response at all.
    """
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
    """A priority past the declared maximum never reaches the decision.

    Not clamped: rejected. The retry hands the model the validation error,
    and a model that keeps violating loses the allocation to the
    deterministic scheduler rather than having its value quietly bounded.
    """
    decision, provenance, prompts = await _allocate(
        monkeypatch, _allocation_text(priority=999)
    )

    assert provenance == "reconstructed-fallback"
    assert decision.queue_actions == ()
    assert len(prompts) == 5
    assert "VALIDATION ERROR" in prompts[1]
    assert "maximum" in prompts[1]


@pytest.mark.asyncio
async def test_non_integer_queue_action_priority_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-integer priority never reaches the decision either.

    The declared type is as load-bearing as the bounds: this is the value
    that would otherwise be handed to a downstream ``int()``.
    """
    decision, provenance, _ = await _allocate(
        monkeypatch, _allocation_text(priority="urgent")
    )

    assert provenance == "reconstructed-fallback"
    assert decision.queue_actions == ()


@pytest.mark.asyncio
async def test_null_queue_action_priority_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Null stays legal: the bounds constrain numbers, not the union.

    ``["integer", "null"]`` with ``minimum``/``maximum`` alongside is easy
    to misread as bounding null out. It does not, and must not -- null is
    how a cancel/retry action declines to set a priority at all.
    """
    decision, provenance, prompts = await _allocate(
        monkeypatch, _allocation_text(priority=None)
    )

    assert provenance == "model"
    assert decision.queue_actions[0]["priority"] is None
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_integral_float_priority_is_normalized_to_an_int(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The surviving live effect of the top-level clamp.

    JSON Schema's "integer" admits a float with no fractional part, so
    ``55.0`` validates. The clamp's ``int()`` is what makes the value that
    leaves the engine a real int.
    """
    body = json.loads(_allocation_text(priority=88))
    body["priority"] = 55.0
    decision, provenance, _ = await _allocate(monkeypatch, json.dumps(body))

    assert provenance == "model"
    assert decision.priority == 55
    assert isinstance(decision.priority, int)


@pytest.mark.asyncio
async def test_missing_next_task_is_backfilled_on_json_object_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one constraint in this schema that production does not enforce.

    ``required`` is relaxed at the top level by the json_object shim: a
    reply with no ``next_task`` at all is completed with the enum's first
    value and recorded as provenance "model" -- a decision the model never
    made -- without so much as a retry. Asserted against the enum source
    rather than the literal, because the substituted value silently
    follows whatever ``_PRODUCTIVE_TASKS`` lists first.
    """
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
    """The backfill's reach stops at the array, bounding the gap above.

    ``reshape_json_output`` returns at a non-dict, so it never
    descends into ``queue_actions`` items. A queue action missing
    ``task_id`` is therefore rejected even on the provider whose top-level
    required fields get filled in for it.
    """
    body = {
        "next_task": "evolve",
        "reason": "Improve mature leaders.",
        "queue_actions": [{"action": "cancel", "reason": "Superseded."}],
    }
    decision, provenance, _ = await _allocate(monkeypatch, json.dumps(body))

    assert provenance == "reconstructed-fallback"
    assert decision.queue_actions == ()

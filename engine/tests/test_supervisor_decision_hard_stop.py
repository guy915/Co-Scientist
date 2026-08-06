"""Tests for ``_hard_stop``'s budget-deferral behavior in isolation.

``_hard_stop`` runs after ``required_transition`` in the Supervisor's
decision pipeline: a settlement round already owed to an under-covered
pool must still be allowed to run even once the iteration/call budget is
technically spent, but a cancelled run must not be granted that same
deferral. These tests drive ``_hard_stop`` directly against hand-built
``SchedulerStats``/``Budget``/``SupervisorDecision`` values -- no model
call, no ``choose_supervisor_task`` pipeline -- so the deferral condition
itself is pinned independent of the routing tests in the sibling
``test_supervisor_decision.py``.
"""

from __future__ import annotations


def test_hard_stop_yields_to_owed_coverage_but_not_to_cancellation() -> None:
    """_hard_stop defers budget stops when coverage remains, but not cancels.

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

    cancelled = SchedulerStats(
        pool_size=6,
        rankable_count=6,
        unmatched_rankable_count=2,
        owed_coverage_rounds=2,
        llm_calls=99,
        cancelled=True,
    )
    stop = _hard_stop(cancelled, budget, settling)

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

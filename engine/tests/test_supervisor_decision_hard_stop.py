"""Tests for ``_hard_stop``'s budget-deferral behavior in isolation.

``_hard_stop`` runs after ``required_transition`` in the Supervisor's
decision pipeline: a settlement round already owed to an under-covered
pool must still be allowed to run even once the iteration/call budget is
technically spent, but a safety block must not be granted that same
deferral. These tests drive ``_hard_stop`` directly against hand-built
``SchedulerStats``/``Budget``/``SupervisorDecision`` values -- no model
call, no ``choose_supervisor_task`` pipeline -- so the deferral condition
itself is pinned independent of the routing tests in the sibling
``test_supervisor_decision.py``.
"""

from __future__ import annotations


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

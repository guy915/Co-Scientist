"""Owed-review acceptance tests for scheduling policy.

Covers the budget-exhaustion window HITL-MANUAL-HYP-001 records: a
hypothesis admitted (by generation, evolution, or a scientist's own
contribution) on the same cycle that exhausts the run's budget has no
peer review, and the scheduler's ordinary review-backlog transition
(``_check_review_backlog``) sits below ``_budget_termination`` so it
never gets the chance to run before the run stops.

``_check_owed_review`` sits above budget termination -- mirroring
``_check_owed_coverage`` immediately above it -- but unlike that check it
is itself gated on the budget already being exhausted: its marker is a
permanent per-hypothesis one-way door (``agents.reflection.owed_review``),
so it must never spend itself on a healthy run's ordinary backlog.

Every scenario that exhausts the budget here does so via ``max_tasks``,
not ``max_llm_calls``: the LLM-call ceiling is also enforced *inside* a
task by the provider-request seam (``llm.admission.call_budget``), at the
identical boundary with zero headroom, so the check refuses to override that one
reason specifically -- see ``test_owed_review_refuses_to_override_the_
llm_call_ceiling`` below and the full argument in
``scheduling.policy_budget._check_owed_review``'s docstring.

All assertions here are against the pure :func:`decide_next_task`
function. The per-hypothesis marker, the marking side effect, and the
"a failed review does not re-arm it" property live in
``test_orchestrator_owed_review.py``.
"""

from co_scientist.scheduling import (
    TaskType,
    TerminationReason,
    decide_next_task,
)
from tests._scheduling import BUDGET, healthy_stats


def test_owed_review_outranks_budget_termination() -> None:
    stats = healthy_stats(owed_review_count=1, tasks_run=100)

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.REFLECT
    assert "review" in decision.reason


def test_owed_review_refuses_to_override_the_llm_call_ceiling() -> None:
    # The one exhaustion reason this override may never buy against: see
    # scheduling.policy_budget._check_owed_review's docstring for why a
    # forced REFLECT here would crash rather than run.
    stats = healthy_stats(owed_review_count=1, llm_calls=1000)

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


def test_owed_review_stays_inert_while_the_budget_has_room() -> None:
    # A healthy run must never pay for this override: the marker it would
    # spend is permanent, so firing here would exhaust it on an ordinary
    # cycle long before a genuinely budget-exhausting admission needed one.
    stats = healthy_stats(owed_review_count=1)

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.GENERATE


def test_safety_block_outranks_owed_review() -> None:
    stats = healthy_stats(
        owed_review_count=1, tasks_run=100, safety_blocked=True
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.SAFETY


def test_steering_outranks_owed_review() -> None:
    stats = healthy_stats(
        owed_review_count=1, tasks_run=100, pending_steering=True
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.GENERATE
    assert "steering" in decision.reason


def test_owed_coverage_outranks_owed_review() -> None:
    # Both can fire on the same exhausted-budget cycle; owed coverage keeps
    # its existing precedence over every budget-adjacent check below it.
    stats = healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        owed_coverage_rounds=1,
        owed_review_count=1,
        tasks_run=100,
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.next_task is TaskType.RANK


def test_zero_owed_review_leaves_budget_termination_alone() -> None:
    stats = healthy_stats(owed_review_count=0, llm_calls=1000)

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


def test_budget_outranks_ordinary_backlog_without_an_owed_review() -> None:
    # Restates the existing test_budget_outranks_backlog with the new field
    # present and zero: an unreviewed backlog alone (nothing specifically
    # owed the override) still yields to a spent budget exactly as before.
    stats = healthy_stats(
        unreviewed_count=5, owed_review_count=0, llm_calls=1000
    )

    decision = decide_next_task(stats, BUDGET)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET

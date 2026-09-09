"""Scientist steering vs. a spent budget, at the policy precedence level.

Split from ``test_scheduling_policy.py`` to keep that file under the
repo's file-size ceiling. All assertions are against the pure
:func:`decide_next_task` function, independent of the graph topology.
Shared ``BUDGET``/``healthy_stats`` fixtures live in ``tests._scheduling``.
"""

from co_scientist.scheduling import Budget, TaskType, decide_next_task
from tests._scheduling import healthy_stats


def test_steering_outranks_budget_exhaustion() -> None:
    """Pending steering buys one cycle even against an exhausted budget.

    HITL-STEERING-001 / HITL-MANUAL-HYP-001: a scientist contribution
    admitted the same cycle the budget runs out (an admission also queues
    a steering message; see app.runs_contrib._steer_and_continue) must not
    be silently dropped by an immediate termination -- _check_steering
    (step 2) outranks _budget_termination (step 4), so the message still
    gets its one GENERATE cycle before the run may stop. Note this closes
    only the "steering silently dropped" half: it does not by itself
    guarantee the admitted idea gets *reviewed* before a later cycle
    terminates on the same exhausted budget -- see
    test_scheduling_policy.py::test_budget_outranks_backlog, which shows
    an exhausted budget still wins over an unreviewed backlog once no
    further steering remains to defer it.
    """
    budget = Budget(max_iterations=100, max_llm_calls=10)
    stats = healthy_stats(llm_calls=10, pending_steering=True)
    decision = decide_next_task(stats, budget)
    assert decision.next_task is TaskType.GENERATE
    assert not decision.terminate

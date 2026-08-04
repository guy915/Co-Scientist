"""Shared ``SchedulerStats``/``Budget`` fixtures for scheduling-policy tests.

Every scheduling-policy acceptance test starts from the same mid-run,
no-backlog snapshot and overrides only the fields it exercises, paired with
a budget generous enough that its ceilings never fire unless a test sets its
own. Both ``test_scheduling_policy.py`` and
``test_scheduling_policy_coverage.py`` build on this baseline.
"""

from co_scientist.scheduling import Budget, SchedulerStats

# A generous budget so budget ceilings never fire unless a test sets them.
BUDGET = Budget(max_iterations=5, max_llm_calls=1000, max_tasks=100)


def healthy_stats(**overrides: object) -> SchedulerStats:
    """A mid-run pool with no backlog, adequate coverage, room to iterate."""
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 0,
        "rankable_count": 6,
        "match_coverage": 3.0,
        "iteration": 1,
        "rank_stable_cycles": 0,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]

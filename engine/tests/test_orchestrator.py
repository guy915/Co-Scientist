from __future__ import annotations

import asyncio

import pytest

from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor
from co_scientist.agents.reflection import owed_review
from co_scientist.agents.reflection.owed_review import (
    mark_owed_review_issued,
    owed_review_count,
    owed_review_issued,
    owed_review_targets,
)
from co_scientist.agents.reflection.owed_review import (
    owed_review_count as _owed_review_count,
)
from co_scientist.agents.supervisor import orchestrator
from co_scientist.agents.supervisor.orchestrator import (
    _init_bookkeeping,
    _initial_settlement_allowance,
    _is_owed_review_override,
    _next_bookkeeping,
    _owed_review_override_marks,
    _rankable_coverage,
    orchestrator_node,
)
from co_scientist.models import Hypothesis
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
)
from co_scientist.state import WorkflowState
from tests._state import make_hypothesis, make_review, make_state


def _hyp(hyp_id: str, wins: int = 0, losses: int = 0) -> Hypothesis:
    """Coverage is owed only to reviewed ideas; new entrants first owe a
    review."""
    return Hypothesis(
        id=hyp_id,
        text=f"statement {hyp_id}",
        win_count=wins,
        loss_count=losses,
        reviews=[make_review()],
    )


def _pool(unmatched: int, covered: int = 0) -> list[Hypothesis]:
    return [_hyp(f"u{i}") for i in range(unmatched)] + [
        _hyp(f"c{i}", wins=1, losses=1) for i in range(covered)
    ]


def test_rankable_coverage_counts_never_matched_hypotheses() -> None:
    # Average coverage can hide individual ideas that have never played.
    rankable, avg, unmatched = _rankable_coverage(
        [_hyp("a", wins=2), _hyp("b", losses=2), _hyp("c")]
    )

    assert rankable == 3
    assert avg > 1.0
    assert unmatched == 1


def test_rankable_coverage_ignores_unrankable_hypotheses() -> None:
    # Evidence-blocked ideas cannot settle match debt and must not hold coverage
    # open.
    blocked = _hyp("blocked")
    blocked.review_disposition = "evidence_blocked"

    rankable, _, unmatched = _rankable_coverage([_hyp("a", wins=1), blocked])

    assert rankable == 1
    assert unmatched == 0


def _settlement_stats(**overrides: object) -> SchedulerStats:
    base: dict[str, object] = {
        "pool_size": 6,
        "rankable_count": 6,
        "unmatched_rankable_count": 4,
        "owed_coverage_rounds": 4,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


_RANK = SupervisorDecision(next_task=TaskType.RANK, reason="settle")


def test_allowance_is_the_tournament_coverage_floor() -> None:
    """Half-covered pools owe rounds even when their zero-match count is
    zero."""
    untouched = _pool(10)
    partially = [_hyp(f"h{i}", wins=1) for i in range(10)]
    covered = _pool(0, 10)

    assert _initial_settlement_allowance(partially) == 5
    for pool in (untouched, partially, covered):
        assert _initial_settlement_allowance(pool) == _coverage_floor(pool)


def test_first_settlement_initialises_and_spends_one_round() -> None:
    book = _next_bookkeeping(
        _init_bookkeeping([]), _settlement_stats(), _RANK, _pool(4, 2)
    )

    assert book["settlement_allowance"] == 3
    assert book["owed_at_last_settlement"] == 4


def test_allowance_is_bounded_by_distinct_pairs() -> None:
    stats = _settlement_stats(
        pool_size=2,
        rankable_count=2,
        unmatched_rankable_count=2,
        owed_coverage_rounds=1,
    )

    book = _next_bookkeeping(_init_bookkeeping([]), stats, _RANK, _pool(2))

    assert book["settlement_allowance"] == 0


def test_allowance_decrements_and_never_refills() -> None:
    # New arrivals cannot refill an allowance without removing its bound.
    book = {
        "settlement_allowance": 3,
        "owed_at_last_settlement": 2,
        "pool_at_last_decision": 6,
    }

    updated = _next_bookkeeping(
        book,
        _settlement_stats(unmatched_rankable_count=40, owed_coverage_rounds=40),
        _RANK,
        _pool(40),
    )

    assert updated["settlement_allowance"] == 2


def test_allowance_floors_at_zero() -> None:
    book = {"settlement_allowance": 0, "owed_at_last_settlement": 1}

    updated = _next_bookkeeping(book, _settlement_stats(), _RANK, _pool(4, 2))

    assert updated["settlement_allowance"] == 0


def test_non_settlement_rank_leaves_the_allowance_alone() -> None:
    book = _init_bookkeeping([])

    updated = _next_bookkeeping(
        book,
        _settlement_stats(unmatched_rankable_count=0, owed_coverage_rounds=0),
        _RANK,
        _pool(0, 6),
    )

    assert updated.get("settlement_allowance") is None


def _loop_stats(book: dict[str, object], **overrides: object) -> SchedulerStats:
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "rankable_count": 6,
        "settlement_allowance": book.get("settlement_allowance"),
        "owed_at_last_settlement": book.get("owed_at_last_settlement"),
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_pool_at_one_match_each_opens_a_settlement_episode() -> None:
    """A zero-match trigger misses pools where every idea still owes its
    second match."""
    budget = Budget(max_iterations=5, max_llm_calls=10)
    pool = [_hyp(f"h{i}", wins=1) for i in range(10)]
    stats = _loop_stats(
        _init_bookkeeping([]),
        pool_size=10,
        reviewed_count=10,
        rankable_count=10,
        unmatched_rankable_count=0,
        owed_coverage_rounds=_coverage_floor(pool),
        llm_calls=999,
    )

    decision = decide_next_task(stats, budget)

    assert decision.next_task is TaskType.RANK
    book = _next_bookkeeping(_init_bookkeeping([]), stats, decision, pool)
    assert book["settlement_allowance"] == 4
    assert book["owed_at_last_settlement"] == 5


def test_under_covered_pool_does_not_rearm_the_allowance() -> None:
    """Closing an episode before all debt clears would rearm its allowance
    indefinitely."""
    pool = [_hyp(f"h{i}", wins=1) for i in range(10)]
    book = {"settlement_allowance": 2, "owed_at_last_settlement": 5}
    stats = _settlement_stats(
        rankable_count=10,
        unmatched_rankable_count=0,
        owed_coverage_rounds=_coverage_floor(pool),
        settlement_allowance=2,
        owed_at_last_settlement=5,
    )

    updated = _next_bookkeeping(book, stats, _RANK, pool)

    assert updated["settlement_allowance"] == 2
    assert updated["owed_at_last_settlement"] == 5


def test_late_backlog_settles_after_an_early_episode_cleared() -> None:
    budget = Budget(max_iterations=5, max_llm_calls=10)
    book = _init_bookkeeping([])

    early = _loop_stats(
        book, unmatched_rankable_count=1, owed_coverage_rounds=1
    )
    early_decision = decide_next_task(early, budget)
    assert early_decision.next_task is TaskType.RANK
    book = _next_bookkeeping(book, early, early_decision, _pool(1, 5))

    cleared = _loop_stats(
        book, unmatched_rankable_count=0, owed_coverage_rounds=0
    )
    book = _next_bookkeeping(
        book, cleared, decide_next_task(cleared, budget), _pool(0, 6)
    )

    late = _loop_stats(
        book,
        pool_size=48,
        reviewed_count=48,
        rankable_count=48,
        unmatched_rankable_count=13,
        owed_coverage_rounds=13,
        llm_calls=999,
    )

    assert decide_next_task(late, budget).next_task is TaskType.RANK


def test_cleared_backlog_rearms_the_allowance() -> None:
    book = {
        "settlement_allowance": 0,
        "owed_at_last_settlement": 2,
    }

    updated = _next_bookkeeping(
        book,
        _settlement_stats(unmatched_rankable_count=0, owed_coverage_rounds=0),
        _RANK,
        _pool(0, 6),
    )

    assert updated["settlement_allowance"] is None
    assert updated["owed_at_last_settlement"] is None


def test_ordinary_ranking_does_not_charge_the_allowance() -> None:
    # Only rounds requested by the settlement check can consume its allowance.
    stats = _settlement_stats(
        unmatched_rankable_count=2,
        owed_coverage_rounds=2,
        settlement_allowance=5,
        owed_at_last_settlement=2,
    )
    book = {"settlement_allowance": 5, "owed_at_last_settlement": 2}

    updated = _next_bookkeeping(book, stats, _RANK, _pool(2, 4))

    assert updated["settlement_allowance"] == 5
    assert updated["owed_at_last_settlement"] == 2


def test_stall_guard_does_not_compare_across_episodes() -> None:
    book = {
        "settlement_allowance": None,
        "owed_at_last_settlement": 2,
    }
    cleared = _settlement_stats(
        unmatched_rankable_count=0, owed_coverage_rounds=0
    )

    updated = _next_bookkeeping(book, cleared, _RANK, _pool(0, 6))
    stats = _settlement_stats(
        rankable_count=48,
        unmatched_rankable_count=13,
        owed_coverage_rounds=13,
        settlement_allowance=updated["settlement_allowance"],
        owed_at_last_settlement=updated["owed_at_last_settlement"],
        llm_calls=999,
    )

    decision = decide_next_task(
        stats, Budget(max_iterations=5, max_llm_calls=10)
    )

    assert decision.next_task is TaskType.RANK


def test_settlement_terminates_while_the_backlog_still_shrinks() -> None:
    # Two ideas admit one pair; the distinct-pair cap makes the allowance bind
    # before debt clears.
    budget = Budget(max_iterations=5, max_llm_calls=10)
    book = _init_bookkeeping([])
    backlog = 2
    decision = None
    rounds = 0

    for _ in range(50):
        pool = _pool(backlog, 2 - backlog)
        stats = SchedulerStats(
            pool_size=2,
            reviewed_count=2,
            rankable_count=2,
            unmatched_rankable_count=backlog,
            owed_coverage_rounds=_coverage_floor(pool),
            llm_calls=999,
            settlement_allowance=book.get("settlement_allowance"),
            owed_at_last_settlement=book.get("owed_at_last_settlement"),
        )
        decision = decide_next_task(stats, budget)
        if decision.terminate:
            break
        book = _next_bookkeeping(book, stats, decision, pool)
        backlog -= 1
        rounds += 1

    assert decision is not None
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET
    assert rounds == 1
    assert backlog > 0


def test_settlement_terminates_when_ranking_never_helps() -> None:
    budget = Budget(max_iterations=5, max_llm_calls=10)
    book = _init_bookkeeping([])
    decision = None

    pool = _pool(8)

    for _ in range(50):
        stats = SchedulerStats(
            pool_size=8,
            reviewed_count=8,
            rankable_count=8,
            unmatched_rankable_count=8,
            owed_coverage_rounds=_coverage_floor(pool),
            llm_calls=999,
            settlement_allowance=book.get("settlement_allowance"),
            owed_at_last_settlement=book.get("owed_at_last_settlement"),
        )
        decision = decide_next_task(stats, budget)
        if decision.terminate:
            break
        book = _next_bookkeeping(book, stats, decision, pool)

    assert decision is not None
    assert decision.terminate


def test_settlement_allowance_is_monotonically_decreasing() -> None:
    # The allowance never increases after opening, regardless of changing pool
    # size.
    book = _init_bookkeeping([])
    seen: list[int] = []

    for pool in (_pool(4), _pool(4), _pool(6), _pool(1, 3), _pool(8)):
        unmatched = sum(1 for h in pool if h.total_matches == 0)
        stats = _settlement_stats(
            pool_size=len(pool),
            rankable_count=len(pool),
            unmatched_rankable_count=unmatched,
            owed_coverage_rounds=_coverage_floor(pool),
            settlement_allowance=book.get("settlement_allowance"),
        )
        book = _next_bookkeeping(book, stats, _RANK, pool)
        seen.append(int(book["settlement_allowance"]))

    assert seen == sorted(seen, reverse=True)
    assert seen[-1] == 0


_EXHAUSTED_BUDGET = Budget(max_iterations=5, max_tasks=3)
_HEALTHY_BUDGET = Budget(max_iterations=5, max_tasks=1000)


def _owed_stats(**overrides: object) -> SchedulerStats:
    base: dict[str, object] = {
        "pool_size": 2,
        "reviewed_count": 1,
        "unreviewed_count": 1,
        "rankable_count": 1,
        "owed_review_count": 1,
        "tasks_run": 3,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


def test_the_override_marks_the_hypothesis_owed_this_cycle() -> None:
    hypothesis = make_hypothesis()
    stats = _owed_stats()

    marked = _owed_review_override_marks(stats, _EXHAUSTED_BUDGET, [hypothesis])

    assert marked == [hypothesis]
    assert owed_review_issued(hypothesis)


def test_an_ordinary_backlog_reflect_on_a_healthy_run_marks_nothing() -> None:
    hypothesis = make_hypothesis()
    stats = _owed_stats(owed_review_count=0)

    marked = _owed_review_override_marks(stats, _HEALTHY_BUDGET, [hypothesis])

    assert marked == []
    assert not owed_review_issued(hypothesis)


def test_marking_does_not_depend_on_which_task_actually_executes() -> None:
    # A consulted planner can divert the forced task; spend the override when
    # the check fires.
    hypothesis = make_hypothesis()
    stats = _owed_stats()

    assert _is_owed_review_override(stats, _EXHAUSTED_BUDGET)
    marked = _owed_review_override_marks(stats, _EXHAUSTED_BUDGET, [hypothesis])

    assert marked == [hypothesis]
    assert owed_review_issued(hypothesis)


def test_orchestrator_forces_review_before_budget_can_terminate() -> None:
    hypothesis = make_hypothesis("newcomer")
    state = make_state(
        hypotheses=[hypothesis],
        budget={"max_iterations": 5, "max_tasks": 1},
        task_history=[{"task_type": "generate", "iteration": 0}],
        current_iteration=0,
    )

    delta = asyncio.run(orchestrator_node(state))

    assert delta["next_task"] == TaskType.REFLECT.value
    assert not delta.get("termination_reason")
    marked = delta["hypotheses"]
    assert marked == [hypothesis]
    assert owed_review_issued(hypothesis)


def test_orchestrator_does_not_touch_hypotheses_on_an_unrelated_decision() -> (
    None
):
    """Coverage is owed only to reviewed ideas; new entrants first owe a
    review."""
    hyps = [make_hypothesis(f"h{i}", elo_rating=1200) for i in range(4)]
    state = make_state(hypotheses=hyps, current_iteration=0)

    delta = asyncio.run(orchestrator_node(state))

    assert delta.get("hypotheses") in (None, [])


def test_a_failed_review_does_not_re_arm_the_override_next_cycle() -> None:
    hypothesis = make_hypothesis()
    pool: list[Hypothesis] = [hypothesis]
    stats = SchedulerStats(
        pool_size=1,
        unreviewed_count=1,
        owed_review_count=_owed_review_count(pool),
        tasks_run=3,
    )
    decision = decide_next_task(stats, _EXHAUSTED_BUDGET)
    assert decision.next_task is TaskType.REFLECT

    marked = _owed_review_override_marks(stats, _EXHAUSTED_BUDGET, pool)
    assert marked == pool
    assert owed_review_issued(hypothesis)

    next_stats = SchedulerStats(
        pool_size=1,
        unreviewed_count=1,
        owed_review_count=_owed_review_count(pool),
        tasks_run=3,
    )
    next_decision = decide_next_task(next_stats, _EXHAUSTED_BUDGET)

    assert next_decision.terminate
    assert next_decision.termination_reason is TerminationReason.MAX_TASKS


def test_a_successful_review_also_terminates_cleanly_next_cycle() -> None:
    hypothesis = make_hypothesis()
    pool: list[Hypothesis] = [hypothesis]
    stats = SchedulerStats(
        pool_size=1,
        unreviewed_count=1,
        owed_review_count=_owed_review_count(pool),
        tasks_run=3,
    )
    decision = decide_next_task(stats, _EXHAUSTED_BUDGET)
    assert decision.next_task is TaskType.REFLECT
    _owed_review_override_marks(stats, _EXHAUSTED_BUDGET, pool)

    hypothesis.reviews.append(make_review())

    next_stats = SchedulerStats(
        pool_size=1,
        unreviewed_count=0,
        owed_review_count=_owed_review_count(pool),
        tasks_run=3,
    )
    next_decision = decide_next_task(next_stats, _EXHAUSTED_BUDGET)

    assert next_decision.terminate
    assert next_decision.termination_reason is TerminationReason.MAX_TASKS


def test_the_override_never_fires_against_an_exhausted_llm_call_budget() -> (
    None
):
    hypothesis = make_hypothesis()
    exhausted_llm_budget = Budget(max_iterations=5, max_llm_calls=10)
    stats = _owed_stats(tasks_run=0, llm_calls=10)

    decision = decide_next_task(stats, exhausted_llm_budget)

    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET
    marked = _owed_review_override_marks(
        stats, exhausted_llm_budget, [hypothesis]
    )
    assert marked == []
    assert not owed_review_issued(hypothesis)


def _state_with_steering(pending: bool) -> WorkflowState:
    hyps = [make_hypothesis(f"h{i}", elo_rating=1200) for i in range(4)]
    return make_state(
        hypotheses=hyps,
        pending_steering=pending,
        current_iteration=0,
    )


def test_pending_steering_schedules_generate_and_clears_flag() -> None:
    delta = asyncio.run(orchestrator_node(_state_with_steering(True)))
    assert delta["next_task"] == TaskType.GENERATE.value
    assert delta["pending_steering"] is False


def test_no_steering_does_not_force_generate_for_steering() -> None:
    delta = asyncio.run(orchestrator_node(_state_with_steering(False)))
    assert "steering" not in str(delta["messages"]).lower()
    assert delta["pending_steering"] is False


def test_activity_uses_live_facts_not_planner_assertions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def _hallucinated_decision(
        *_args: object, **_kwargs: object
    ) -> tuple[SupervisorDecision, str, int]:
        return (
            SupervisorDecision(
                next_task=TaskType.GENERATE,
                reason="No hypotheses have been generated yet.",
                priority=80,
            ),
            "model",
            1,
        )

    monkeypatch.setattr(
        orchestrator, "choose_supervisor_task", _hallucinated_decision
    )
    state = _state_with_steering(False)
    delta = asyncio.run(orchestrator_node(state))

    message = str(delta["messages"])
    assert "No hypotheses" not in message
    assert "4 hypotheses" in message
    record = delta["task_history"][-1]
    assert record["reason"].startswith(
        "Supervisor selected generate from live state"
    )
    assert record["planner_reason"] == "No hypotheses have been generated yet."


def _unreviewed(index: int = 0) -> Hypothesis:
    return make_hypothesis(text=f"unreviewed idea {index}")


def _reviewed(index: int = 0) -> Hypothesis:
    return make_hypothesis(
        text=f"reviewed idea {index}", reviews=[make_review()]
    )


def test_only_unreviewed_hypotheses_are_owed() -> None:
    unreviewed = _unreviewed(0)
    pool = [unreviewed, _reviewed(1)]

    assert owed_review_targets(pool) == [unreviewed]
    assert owed_review_count(pool) == 1


def test_marking_removes_a_hypothesis_from_the_owed_set() -> None:
    hypothesis = _unreviewed()
    mark_owed_review_issued(hypothesis)

    assert owed_review_issued(hypothesis)
    assert owed_review_targets([hypothesis]) == []
    assert owed_review_count([hypothesis]) == 0


def test_marking_is_permanent_even_if_the_hypothesis_stays_unreviewed() -> None:
    hypothesis = _unreviewed()
    mark_owed_review_issued(hypothesis)

    assert not hypothesis.reviews
    assert owed_review_count([hypothesis]) == 0


def test_the_marker_survives_a_checkpoint_round_trip() -> None:
    hypothesis = _unreviewed()
    mark_owed_review_issued(hypothesis)

    restored = Hypothesis.from_dict(hypothesis.to_dict())

    assert owed_review_targets([restored]) == []


def test_an_unreviewed_but_already_archived_duplicate_is_not_owed() -> None:
    # Proximity can archive unreviewed ideas; a forced review of an archived
    # idea buys nothing.
    hypothesis = _unreviewed()
    hypothesis.review_disposition = "duplicate"

    assert owed_review_targets([hypothesis]) == []


def test_the_run_wide_ceiling_bounds_a_pathological_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(owed_review, "MAX_OWED_REVIEW_OVERRIDES_PER_RUN", 3)
    pool = [_unreviewed(i) for i in range(10)]

    first = owed_review_targets(pool)
    for hypothesis in first:
        mark_owed_review_issued(hypothesis)
    second = owed_review_targets(pool)

    assert len(first) == 3
    assert second == []

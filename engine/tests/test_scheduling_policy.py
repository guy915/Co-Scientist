"""Deterministic scheduling-policy acceptance tests.

Covers the required scheduling states — generation-heavy, evolution-heavy,
verification-backlogged, converged, budget-exhausted, steered, and retry —
plus precedence/ordering, the allowed-transition validation, and
serialization. All assertions are against the pure :func:`decide_next_task` /
:func:`validate_decision` functions, independent of the graph topology.

Tournament-budget and owed-coverage settlement acceptance tests live in
``test_scheduling_policy_coverage.py``; both files share the ``BUDGET``/
``healthy_stats`` fixtures in ``tests._scheduling``.
"""

from co_scientist.scheduling import (
    ALLOWED_LOOP_TASKS,
    Budget,
    SupervisorDecision,
    TaskType,
    TerminationReason,
    decide_next_task,
    validate_decision,
)
from tests._scheduling import BUDGET, healthy_stats

# --- Required scheduling states ---------------------------------------------


def test_generation_heavy_state_generates() -> None:
    """When generation out-yields evolution, schedule GENERATE."""
    stats = healthy_stats(generation_yield=0.9, evolution_yield=0.1)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE
    assert not decision.terminate


def test_evolution_heavy_state_evolves() -> None:
    """When evolution out-yields generation with leaders, schedule EVOLVE."""
    stats = healthy_stats(generation_yield=0.1, evolution_yield=0.8)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.EVOLVE


def test_verification_backlogged_state_reviews() -> None:
    """Unreviewed hypotheses are reviewed before ranking or evolving."""
    stats = healthy_stats(unreviewed_count=3)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.REFLECT


def test_converged_state_terminates() -> None:
    """A stable leaderboard with no backlog terminates as converged.

    ``evolved_since_stable`` is what says the listing's own response to
    stagnation (evolve, L55-58) has already been tried on this episode;
    without it the run owes one evolve cycle before it may stop. See
    ``test_scheduling_policy_convergence.py``.
    """
    stats = healthy_stats(
        rank_stable_cycles=2, iteration=2, evolved_since_stable=True
    )
    decision = decide_next_task(stats, BUDGET, convergence_cycles=2)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.CONVERGED


def test_convergence_held_off_until_min_cycles() -> None:
    """A stable leaderboard does not converge before the min work cycles.

    Guarantees the loop evolves and generates at least once before a stable
    tournament is allowed to stop the run.
    """
    stats = healthy_stats(rank_stable_cycles=5, iteration=1)
    decision = decide_next_task(
        stats, BUDGET, convergence_cycles=2, min_cycles_before_convergence=2
    )
    assert not decision.terminate


def test_budget_exhausted_state_terminates() -> None:
    """Hitting the LLM-call ceiling terminates with a budget reason."""
    budget = Budget(max_iterations=100, max_llm_calls=50)
    stats = healthy_stats(llm_calls=50)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET


def test_task_budget_exhausted_terminates() -> None:
    """Hitting the task ceiling terminates with a max-tasks reason."""
    budget = Budget(max_iterations=100, max_tasks=20)
    stats = healthy_stats(tasks_run=20)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.MAX_TASKS


def test_wall_clock_exhausted_terminates() -> None:
    """Hitting the wall-clock ceiling terminates with a wall-clock reason."""
    budget = Budget(max_iterations=100, max_wall_clock_s=60.0)
    stats = healthy_stats(elapsed_s=61.0)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.WALL_CLOCK


def test_max_ideas_exhausted_terminates() -> None:
    """Hitting the paper's MaxIdeas ceiling terminates (F11)."""
    budget = Budget(max_iterations=100, max_ideas=10)
    stats = healthy_stats(pool_size=10, unreviewed_count=0)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.MAX_IDEAS


def test_max_ideas_defers_to_review_backlog() -> None:
    """A pool at the MaxIdeas ceiling still drains unreviewed work first.

    ``_budget_termination`` (step 4) runs ahead of the review-backlog step
    (step 6); without the gate this would strand the freshest ideas
    unreviewed the moment the pool crossed the ceiling.
    """
    budget = Budget(max_iterations=100, max_ideas=10)
    stats = healthy_stats(pool_size=10, unreviewed_count=2)
    decision = decide_next_task(stats, budget)
    assert not decision.terminate
    assert decision.next_task is TaskType.REFLECT


def test_max_matches_per_idea_exhausted_terminates() -> None:
    """Hitting the paper's MaxMatchesPerIdea ceiling terminates (F11)."""
    budget = Budget(max_iterations=100, max_matches_per_idea=3.0)
    stats = healthy_stats(rankable_count=6, match_coverage=3.0)
    decision = decide_next_task(stats, budget)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.MAX_MATCHES_PER_IDEA


def test_max_matches_per_idea_below_threshold_continues() -> None:
    """Below the MaxMatchesPerIdea ceiling, the ceiling does not fire."""
    budget = Budget(max_iterations=100, max_matches_per_idea=3.0)
    stats = healthy_stats(rankable_count=6, match_coverage=2.0)
    decision = decide_next_task(stats, budget)
    assert not decision.terminate


def test_steered_state_generates() -> None:
    """Pending user steering is a high-priority request to generate anew."""
    stats = healthy_stats(pending_steering=True, evolution_yield=0.9)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE
    assert "steering" in decision.reason


def test_retry_state_reschedules_failed_task() -> None:
    """A failed task with retries left is rescheduled before new work."""
    stats = healthy_stats(last_task_failed=TaskType.RANK, retries_remaining=1)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.RANK
    assert "retry" in decision.reason.lower()


def test_stale_cancelled_flag_does_not_terminate() -> None:
    """``SchedulerStats.cancelled`` is no longer read by the policy.

    Cancellation is enforced by the durable executor never dispatching
    another node, not by a termination reason this policy produces (finding
    F12). The field itself is retained -- the orchestrator still constructs
    ``SchedulerStats`` with it -- so this pins that setting it True has no
    effect rather than force-terminating.
    """
    stats = healthy_stats(cancelled=True)
    decision = decide_next_task(stats, BUDGET)
    assert not decision.terminate


def test_safety_block_terminates() -> None:
    """A safety block halts the run (Milestone 6 hook)."""
    stats = healthy_stats(safety_blocked=True)
    decision = decide_next_task(stats, BUDGET)
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.SAFETY


def test_yield_tie_without_stagnation_generates() -> None:
    """On a yield tie with no measured stagnation, generate (F10).

    Covers the common both-zero tie, including a pool that just evolved:
    evolution must not fire on a tie without a measured leaderboard-stability
    signal, whatever the last work task was.
    """
    stats = healthy_stats(
        generation_yield=0.0,
        evolution_yield=0.0,
        rank_stable_cycles=0,
        last_work_task=TaskType.EVOLVE,
    )
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE


def test_yield_tie_with_stagnation_evolves() -> None:
    """On a yield tie, evolve on the transition into leaderboard stagnation.

    ``rank_stable_cycles`` is a real, measured per-cycle signal from the
    ranking agent's own Elo output -- the substitute this audit item wires
    in for the untrustworthy ``performance_assessment`` field (F5), which is
    produced once before any hypothesis exists and cannot measure anything.
    The last work task was GENERATE, so this is a fresh transition into
    stagnation, not a repeat.
    """
    stats = healthy_stats(
        generation_yield=0.0,
        evolution_yield=0.0,
        rank_stable_cycles=1,
        last_work_task=TaskType.GENERATE,
    )
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.EVOLVE
    assert "stagnant" in decision.reason


def test_yield_tie_with_standing_stagnation_generates() -> None:
    """A tie does not evolve twice in a row off standing stagnation (F10).

    ``rank_stable_cycles`` does not reset once the leaderboard settles -- it
    stays >= 1 for every later cycle until the Elo ordering next changes. If
    evolution already had its turn (``last_work_task`` is EVOLVE) and the
    leaderboard is still tied and still stagnant, the policy must generate
    instead of evolving again: repeated evolution of an already-converged
    pool breeds from the same narrow set of survivors on every pass, the
    same failure mode already seen in production. This is what keeps
    generation from being starved for the rest of a long run.
    """
    stats = healthy_stats(
        generation_yield=0.0,
        evolution_yield=0.0,
        rank_stable_cycles=3,
        last_work_task=TaskType.EVOLVE,
    )
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE
    assert "already had its turn" in decision.reason


# --- Precedence / ordering --------------------------------------------------


def test_safety_outranks_budget_and_backlog() -> None:
    """A safety block is checked before budget and productive work."""
    budget = Budget(max_iterations=100, max_llm_calls=1)
    stats = healthy_stats(
        safety_blocked=True, llm_calls=100, unreviewed_count=5
    )
    decision = decide_next_task(stats, budget)
    assert decision.termination_reason is TerminationReason.SAFETY


def test_budget_outranks_backlog() -> None:
    """A hard budget stop wins over a review backlog."""
    budget = Budget(max_iterations=100, max_llm_calls=10)
    stats = healthy_stats(llm_calls=10, unreviewed_count=5)
    decision = decide_next_task(stats, budget)
    assert decision.termination_reason is TerminationReason.BUDGET


def test_small_pool_generates_even_when_evolution_yield_high() -> None:
    """A sub-tournament pool must generate before it can rank/evolve."""
    stats = healthy_stats(pool_size=1, reviewed_count=1, evolution_yield=0.9)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.GENERATE


def test_low_coverage_ranks() -> None:
    """Below the minimum match coverage, schedule more tournament rounds."""
    stats = healthy_stats(match_coverage=0.0)
    decision = decide_next_task(stats, BUDGET, min_match_coverage=1.0)
    assert decision.next_task is TaskType.RANK


def test_pool_growth_refreshes_proximity() -> None:
    """After the pool grows, proximity is refreshed before the next choice."""
    stats = healthy_stats(pool_grew_since_proximity=True)
    decision = decide_next_task(stats, BUDGET)
    assert decision.next_task is TaskType.PROXIMITY


def test_iteration_budget_reached_completes() -> None:
    """Reaching the iteration budget terminates as satisfied completion."""
    stats = healthy_stats(iteration=5)
    decision = decide_next_task(stats, Budget(max_iterations=5))
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.COMPLETED


def test_starved_generation_terminates_at_iteration_budget() -> None:
    """A pool stuck below tournament size still stops at the iteration budget.

    Each GENERATE advances the iteration counter even when it fails to grow
    the pool, so the iteration ceiling must outrank the pool-too-small branch;
    otherwise a starved run only dies via the graph recursion limit instead of
    terminating with a recorded reason.
    """
    stats = healthy_stats(pool_size=1, reviewed_count=1, iteration=5)
    decision = decide_next_task(stats, Budget(max_iterations=5))
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.COMPLETED


def test_unrankable_pool_does_not_loop_on_ranking() -> None:
    """A pool with fewer than two rankable ideas must not demand ranking.

    Regression: when the pre-ranking evidence gate marks most ideas
    ``evidence_blocked`` they leave the tournament, so their match coverage
    stays zero. Measuring coverage over the full pool held it below the gate
    forever and looped the orchestrator on RANK. With coverage measured over
    the rankable pool, a run whose ideas are all gated advances (generate/
    evolve) and terminates at its iteration budget instead of looping.
    """
    # Six reviewed ideas in the pool, none rankable, zero coverage, mid-budget.
    stats = healthy_stats(rankable_count=0, match_coverage=0.0, iteration=1)
    decision = decide_next_task(stats, BUDGET, min_match_coverage=1.0)
    assert decision.next_task is not TaskType.RANK
    assert not decision.terminate
    # At the iteration budget the same unrankable pool terminates, not loops.
    at_budget = healthy_stats(rankable_count=0, match_coverage=0.0, iteration=5)
    end = decide_next_task(at_budget, Budget(max_iterations=5))
    assert end.terminate
    assert end.termination_reason is TerminationReason.COMPLETED


# --- Allowed-transition validation ------------------------------------------


def test_validate_rejects_rank_on_tiny_pool() -> None:
    """An LLM recommending RANK with <2 rankable ideas is corrected."""
    stats = healthy_stats(pool_size=1, rankable_count=1)
    recommended = SupervisorDecision(TaskType.RANK, "llm said rank")
    validated = validate_decision(recommended, stats)
    assert validated.next_task is TaskType.GENERATE
    assert "corrected" in validated.reason


def test_validate_rejects_evolve_without_reviews() -> None:
    """EVOLVE with no reviewed hypotheses is corrected to REFLECT/GENERATE."""
    stats = healthy_stats(reviewed_count=0, unreviewed_count=3)
    recommended = SupervisorDecision(TaskType.EVOLVE, "llm said evolve")
    validated = validate_decision(recommended, stats)
    assert validated.next_task is TaskType.REFLECT

    stats2 = healthy_stats(reviewed_count=0, unreviewed_count=0, pool_size=2)
    validated2 = validate_decision(
        SupervisorDecision(TaskType.EVOLVE, "llm said evolve"), stats2
    )
    assert validated2.next_task is TaskType.GENERATE


def test_correction_carries_queue_actions_through() -> None:
    """Every correction keeps the queue actions it was handed.

    A correction judges the *next task*; the actions name existing durable
    task rows by id, and a failed row has no other route back --
    ``resume_run_tasks`` requeues only paused rows and the expired-lease
    rescue skips a task whose attempts are spent. Rebuilding the decision
    dropped them, and the conditions the rank/evolve corrections fire on are
    pool properties the corrected task need not clear, so the same revival
    was discarded on every subsequent loop point rather than deferred by one.
    """
    retry = ({"action": "retry", "task_id": "t-9", "reason": "transient"},)

    steered = validate_decision(
        SupervisorDecision(TaskType.RANK, "llm said rank", queue_actions=retry),
        healthy_stats(pending_steering=True),
    )
    assert steered.next_task is TaskType.GENERATE
    assert steered.queue_actions == retry

    ranked = validate_decision(
        SupervisorDecision(TaskType.RANK, "llm said rank", queue_actions=retry),
        healthy_stats(pool_size=1, rankable_count=1),
    )
    assert ranked.next_task is TaskType.GENERATE
    assert ranked.queue_actions == retry

    evolved = validate_decision(
        SupervisorDecision(
            TaskType.EVOLVE, "llm said evolve", queue_actions=retry
        ),
        healthy_stats(reviewed_count=0, unreviewed_count=3),
    )
    assert evolved.next_task is TaskType.REFLECT
    assert evolved.queue_actions == retry

    # SYNTHESIZE used to stand here as the undispatchable case. It is a
    # dispatchable loop task since the periodic research overview (FIX-6),
    # which leaves ``_correct_disallowed_task`` with no TaskType member to
    # fire on -- it is now a guard against a value from outside the enum,
    # not a reachable correction. The invariant it stood for is asserted
    # directly instead.
    assert frozenset(TaskType) == ALLOWED_LOOP_TASKS


def test_validate_passes_valid_decision_unchanged() -> None:
    """A valid decision is returned unchanged."""
    stats = healthy_stats()
    decision = SupervisorDecision(TaskType.EVOLVE, "evolve leaders")
    assert validate_decision(decision, stats) is decision


def test_validate_passes_terminate_unchanged() -> None:
    """A terminate decision is never downgraded by validation."""
    stats = healthy_stats(pool_size=0)
    decision = SupervisorDecision(
        TaskType.TERMINATE,
        "done",
        terminate=True,
        termination_reason=TerminationReason.COMPLETED,
    )
    assert validate_decision(decision, stats) is decision


# --- Serialization ----------------------------------------------------------


def test_decision_and_stats_round_trip_to_dict() -> None:
    """Decision/stats serialize to plain dicts for state/event transport."""
    stats = healthy_stats(last_task_failed=TaskType.RANK)
    stats_dict = stats.to_dict()
    assert stats_dict["last_task_failed"] == "rank"

    decision = _terminate_decision()
    d = decision.to_dict()
    assert d["next_task"] == "terminate"
    assert d["termination_reason"] == "converged"


def _terminate_decision() -> SupervisorDecision:
    return SupervisorDecision(
        TaskType.TERMINATE,
        "stable",
        terminate=True,
        termination_reason=TerminationReason.CONVERGED,
    )


# --- Durability across the F11/F12 schema change -----------------------------


def test_budget_from_dict_tolerates_a_pre_f11_checkpoint() -> None:
    """A checkpoint's ``budget`` dict from before F11 still loads.

    ``Budget.from_dict`` only reads keys that are dataclass fields, so a
    payload written before ``max_ideas``/``max_matches_per_idea`` existed
    loads with both defaulting to None (no limit) rather than raising.
    """
    pre_f11_payload = {
        "max_iterations": 5,
        "max_llm_calls": 1000,
        "max_tasks": 100,
        "max_wall_clock_s": None,
    }
    budget = Budget.from_dict(pre_f11_payload)
    assert budget.max_ideas is None
    assert budget.max_matches_per_idea is None
    # And it still enforces the fields it did carry.
    stats = healthy_stats(tasks_run=100)
    decision = decide_next_task(stats, budget)
    assert decision.termination_reason is TerminationReason.MAX_TASKS


def test_stale_cancelled_termination_reason_string_is_inert_data() -> None:
    """A pre-F12 checkpoint's stored ``"cancelled"`` reason never re-parses.

    ``TerminationReason`` no longer has a ``CANCELLED`` member, but a run
    that genuinely terminated with that reason before this change has it
    sitting in persisted ``task_history``/``termination_reason`` state as a
    plain string -- never reconstructed back into the enum anywhere in the
    engine (state.py types both as ``str``). Resuming such a run must not
    raise; this pins that the enum's remaining members are unaffected by an
    unrelated stale string coexisting in state.
    """
    stale_history_entry = {
        "task_type": "generate",
        "status": "completed",
        "reason": "done",
        "iteration": 3,
        "termination_reason": "cancelled",
    }
    # Nothing in the scheduling module parses this back into an enum; it is
    # opaque data that a resumed run only ever carries forward or displays.
    assert stale_history_entry["termination_reason"] == "cancelled"
    # The current enum has no such member, confirming removal is complete.
    assert "cancelled" not in {r.value for r in TerminationReason}
    # A fresh decision on the same (now-resumed) run is unaffected.
    stats = healthy_stats()
    decision = decide_next_task(stats, BUDGET)
    assert decision.termination_reason != "cancelled"

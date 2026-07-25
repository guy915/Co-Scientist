# Uncompared Idea Settlement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a run from ending with hypotheses that never entered the Elo tournament, unless it was explicitly cancelled or safety-blocked.

**Architecture:** One new check (`_check_owed_coverage`) is inserted into the scheduler's ordered precedence between the cancel/safety stop signals and the budget ceilings. It fires per-hypothesis rather than on an average, and is bounded by a settlement allowance stored in orchestrator bookkeeping that strictly decreases and never refills — so it terminates by construction, not by detecting progress.

**Tech Stack:** Python 3.10+, pytest, ruff (format + lint, 80 columns), mypy strict. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-25-uncompared-idea-settlement-design.md`.
- Ruff formatting, **80 columns**, config in `engine/pyproject.toml`.
- Google-format docstrings, capitalised, full sentences (`Args:`/`Returns:`).
- `logger.debug()` lowercase; `info`/`warning`/`error` capitalised.
- No emojis or unicode decoration in code or logs.
- No Rich library in core engine code (`examples/` and `dev/` only).
- `decide_next_task` / `required_transition` must stay **pure** functions of `SchedulerStats` and `Budget`. The policy reads the allowance; it never mutates it.
- Commit messages: `<type>(<scope>): <subject>`. **Never** mention AI tooling or add AI co-author trailers.

### Running tests in this worktree — read this first

The shared virtualenv at `/Users/guy/Code/Co-Scientist/.venv` has the engine
installed editable from the **main checkout**, not from this worktree. Running
pytest without an override collects this worktree's test files but exercises
the main checkout's `co_scientist` source, so your edits appear to do nothing
and tests pass for the wrong reasons.

Every test command in this plan is run from `engine/` and must be prefixed:

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src \
  /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest <args>
```

Referred to below as `PYTEST`. Verify the override once before starting:

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src \
  /Users/guy/Code/Co-Scientist/.venv/bin/python -c "import co_scientist; print(co_scientist.__file__)"
```

Expected: a path under `.claude/worktrees/baseline-elo-scoring-bfd98b/`.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/src/co_scientist/scheduling/models.py` | Carries the three new observable fields on `SchedulerStats`. Data only. |
| `engine/src/co_scientist/scheduling/policy.py` | Owns `_check_owed_coverage` and its position in `_ordered_checks`. Pure decision logic. |
| `engine/src/co_scientist/agents/supervisor/orchestrator.py` | Computes the observables from `WorkflowState` and owns the allowance lifecycle in bookkeeping. |
| `engine/src/co_scientist/agents/supervisor/supervisor_decision.py` | Mirrors the precedence in `_hard_stop` so the model path cannot bypass owed coverage. |
| `engine/tests/test_scheduling_policy.py` | Policy-level acceptance tests (existing file, extended). |
| `engine/tests/test_supervisor_decision.py` | Hard-stop precedence test (existing file, extended). |
| `engine/tests/test_orchestrator_settlement.py` | New. Allowance lifecycle and the termination guarantee. |

---

### Task 1: Observable fields on SchedulerStats

**Files:**
- Modify: `engine/src/co_scientist/scheduling/models.py:106` (after `rankable_count`)
- Modify: `engine/src/co_scientist/agents/supervisor/orchestrator.py:178` (`_rankable_coverage`), `:49` (`_StatsScalars`), `:204` (`_build_scheduler_stats`)
- Test: `engine/tests/test_orchestrator_settlement.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `SchedulerStats.unmatched_rankable_count: int`, `SchedulerStats.settlement_allowance: int | None`, `SchedulerStats.unmatched_at_last_settlement: int | None`. `orchestrator._rankable_coverage(hyps) -> tuple[int, float, int]` (was `tuple[int, float]`; third element is the unmatched count).

This task adds the signal and changes no behaviour.

- [ ] **Step 1: Write the failing test**

Create `engine/tests/test_orchestrator_settlement.py`:

```python
"""Settlement-allowance lifecycle and the owed-coverage termination bound.

Covers the orchestrator-side half of owed-coverage settlement: deriving the
unmatched count from the pool, and initialising, decrementing, and never
refilling the allowance that bounds how long the scheduler may override a
budget ceiling to finish owed tournament rounds.
"""

from co_scientist.agents.supervisor.orchestrator import _rankable_coverage
from co_scientist.models import Hypothesis


def _hyp(hyp_id: str, wins: int = 0, losses: int = 0) -> Hypothesis:
    """A minimal rankable hypothesis with the given match tally."""
    return Hypothesis(
        id=hyp_id,
        text=f"statement {hyp_id}",
        win_count=wins,
        loss_count=losses,
    )


def test_rankable_coverage_counts_never_matched_hypotheses() -> None:
    # A healthy average hides individual zeros: two ideas at two matches
    # each averages 1.33 across three, passing a 1.0 average gate while one
    # idea has never played.
    rankable, avg, unmatched = _rankable_coverage(
        [_hyp("a", wins=2), _hyp("b", losses=2), _hyp("c")]
    )

    assert rankable == 3
    assert avg > 1.0
    assert unmatched == 1


def test_rankable_coverage_ignores_unrankable_hypotheses() -> None:
    # An evidence-gate-rejected idea can never accrue matches, so counting
    # it as unmatched would demand tournament rounds that cannot help it.
    blocked = _hyp("blocked")
    blocked.review_disposition = "evidence_blocked"

    rankable, _, unmatched = _rankable_coverage([_hyp("a", wins=1), blocked])

    assert rankable == 1
    assert unmatched == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run from `engine/`:

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest tests/test_orchestrator_settlement.py -v
```

Expected: FAIL — `ValueError: too many values to unpack (expected 3)`, because `_rankable_coverage` still returns a 2-tuple.

- [ ] **Step 3: Add the fields to SchedulerStats**

In `engine/src/co_scientist/scheduling/models.py`, immediately after the
`rankable_count: int = 0` line and its comment block, insert:

```python
    # Rankable hypotheses with zero tournament matches. Tracked alongside the
    # average below because an average cannot see them: 35 ideas at two
    # matches each averages 1.46 across 48 and clears a 1.0 threshold while
    # 13 have never played once. The average gates ordering refinement; this
    # gates whether anyone has been left out entirely.
    unmatched_rankable_count: int = 0
    # Remaining tournament rounds the scheduler may spend overriding a budget
    # ceiling to settle owed coverage. None means the override has not fired
    # yet and may; 0 means the allowance is spent and it never fires again.
    # Strictly decreasing and never refilled, which is what bounds the
    # override rather than any assumption that ranking makes progress.
    settlement_allowance: int | None = None
    # Unmatched count observed at the previous settlement round, or None if
    # there was none. Lets the scheduler stop early when a round changed
    # nothing. A cost optimisation only -- termination rests on the allowance.
    unmatched_at_last_settlement: int | None = None
```

- [ ] **Step 4: Compute the unmatched count in the orchestrator**

In `engine/src/co_scientist/agents/supervisor/orchestrator.py`, replace
`_rankable_coverage` entirely:

```python
def _rankable_coverage(
    hyps: list[Hypothesis],
) -> tuple[int, float, int]:
    """Return (rankable_count, average coverage, unmatched count).

    Coverage is measured over the rankable pool only. An un-rankable idea
    (undermined or review/evidence-gate rejected) can never accrue matches,
    so counting it in the denominator would hold average coverage below the
    gate forever and loop the orchestrator on ranking.

    The unmatched count is reported separately because the average cannot
    represent it: a pool can clear its average threshold while individual
    hypotheses have never been matched at all.

    Args:
        hyps: The full hypothesis pool.

    Returns:
        The rankable count, their average match coverage, and how many of
        them have never been matched.
    """
    rankable = [h for h in hyps if h.is_rankable()]
    rankable_count = len(rankable)
    rankable_matches = sum(h.total_matches for h in rankable)
    avg_coverage = rankable_matches / rankable_count if rankable_count else 0.0
    unmatched = sum(1 for h in rankable if h.total_matches == 0)
    return rankable_count, avg_coverage, unmatched
```

Add `unmatched_rankable_count: int` to the `_StatsScalars` dataclass, after
`avg_coverage: float`.

In `_compute_stats`, change the unpack line from:

```python
    rankable_count, avg_coverage = _rankable_coverage(hyps)
```

to:

```python
    rankable_count, avg_coverage, unmatched = _rankable_coverage(hyps)
```

and add `unmatched_rankable_count=unmatched,` to the `_StatsScalars(...)`
construction, after `avg_coverage=avg_coverage,`.

In `_build_scheduler_stats`, add to the `SchedulerStats(...)` construction,
after `match_coverage=scalars.avg_coverage,`:

```python
        unmatched_rankable_count=scalars.unmatched_rankable_count,
        settlement_allowance=book.get("settlement_allowance"),
        unmatched_at_last_settlement=book.get(
            "unmatched_at_last_settlement"
        ),
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest tests/test_orchestrator_settlement.py tests/test_scheduling_policy.py tests/test_supervisor.py -v
```

Expected: PASS. The existing suites must stay green — this task changes no
behaviour.

- [ ] **Step 6: Lint, format, typecheck**

From `engine/`:

```bash
ruff format . && ruff check . && /Users/guy/Code/Co-Scientist/.venv/bin/python -m mypy .
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add engine/src/co_scientist/scheduling/models.py engine/src/co_scientist/agents/supervisor/orchestrator.py engine/tests/test_orchestrator_settlement.py
git commit -m "feat(scheduling): observe hypotheses with zero tournament matches"
```

---

### Task 2: The owed-coverage check

**Files:**
- Modify: `engine/src/co_scientist/scheduling/policy.py` (add check near `_check_stop_signals:144`; wire into `_ordered_checks:313`)
- Test: `engine/tests/test_scheduling_policy.py`

**Interfaces:**
- Consumes: `SchedulerStats.unmatched_rankable_count`, `.settlement_allowance`, `.unmatched_at_last_settlement`, `.rankable_count` (Task 1).
- Produces: `policy._check_owed_coverage(stats: SchedulerStats) -> SupervisorDecision | None`, returning a `TaskType.RANK` decision or `None`.

The check reads only. It never mutates the allowance — Task 3 owns that.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/test_scheduling_policy.py`:

```python
# --- Owed tournament coverage ----------------------------------------------


def test_uncompared_idea_ranks_despite_healthy_average() -> None:
    # An average cannot see an individual zero: 2 ideas at 2 matches each
    # averages 1.33 across 3 and clears the 1.0 threshold while one idea has
    # never played. The per-hypothesis check is what catches it.
    stats = _healthy_stats(
        rankable_count=3, match_coverage=1.33, unmatched_rankable_count=1
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.RANK


def test_owed_coverage_outranks_budget_termination() -> None:
    # A spent budget must not strand an idea that never played. The ceiling
    # is a runaway backstop, and the allowance bounds the overshoot.
    stats = _healthy_stats(
        rankable_count=3, unmatched_rankable_count=1, llm_calls=1000
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.RANK


def test_cancellation_outranks_owed_coverage() -> None:
    # The operator asked the run to stop; further tournament work is wrong.
    stats = _healthy_stats(
        rankable_count=3, unmatched_rankable_count=1, cancelled=True
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.CANCELLED


def test_safety_block_outranks_owed_coverage() -> None:
    stats = _healthy_stats(
        rankable_count=3, unmatched_rankable_count=1, safety_blocked=True
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.SAFETY


def test_spent_allowance_stops_overriding_the_budget() -> None:
    # The allowance is what bounds the override. At zero the check is inert
    # even though an idea is still uncompared, so the run can stop.
    stats = _healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        settlement_allowance=0,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.BUDGET


def test_stalled_settlement_stops_overriding_the_budget() -> None:
    # A round that did not reduce the backlog will not reduce it next time
    # either; spending the rest of the allowance on it wastes real debates.
    stats = _healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=2,
        settlement_allowance=5,
        unmatched_at_last_settlement=2,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE


def test_settlement_continues_while_backlog_shrinks() -> None:
    stats = _healthy_stats(
        rankable_count=3,
        unmatched_rankable_count=1,
        settlement_allowance=5,
        unmatched_at_last_settlement=3,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.RANK


def test_single_rankable_hypothesis_never_settles() -> None:
    # Nothing to pair against, so demanding coverage could never be met.
    stats = _healthy_stats(
        pool_size=1,
        rankable_count=1,
        unmatched_rankable_count=1,
        llm_calls=1000,
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is not TaskType.RANK


def test_fully_compared_pool_is_unaffected() -> None:
    # Regression guard: with nothing owed, the budget ceiling still stops.
    stats = _healthy_stats(
        rankable_count=3, unmatched_rankable_count=0, llm_calls=1000
    )

    decision = decide_next_task(stats, _BUDGET)

    assert decision.next_task is TaskType.TERMINATE
    assert decision.termination_reason is TerminationReason.BUDGET
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest tests/test_scheduling_policy.py -k "owed or uncompared or settle or allowance or stalled or fully_compared" -v
```

Expected: FAIL — the budget-termination and average-coverage tests return
`TERMINATE`/`GENERATE` where `RANK` is asserted.

- [ ] **Step 3: Add the check**

In `engine/src/co_scientist/scheduling/policy.py`, insert immediately after
`_check_stop_signals` (which ends at line 152):

```python
def _check_owed_coverage(
    stats: SchedulerStats,
) -> SupervisorDecision | None:
    """Step 2: settle hypotheses that have never entered the tournament.

    Ranked above the budget ceilings and below the cancel/safety stops. A
    hypothesis that leaves a run unmatched has no tournament result at all,
    which is a worse outcome than a small, bounded overshoot of a ceiling
    that exists to catch runaways rather than to meter work. Cancellation
    and safety blocks still win outright: the operator asked to stop, or the
    content is unsafe, and more work is wrong in both cases.

    Per-hypothesis rather than the average used by
    :func:`_check_tournament_coverage`, which cannot represent this state:
    35 hypotheses at two matches each averages 1.46 across 48 and clears a
    1.0 threshold while 13 have never been matched once.

    Bounded by ``settlement_allowance``, which strictly decreases and is
    never refilled, so this check fires finitely many times and the run
    always reaches a terminal decision. That bound is structural -- it does
    not assume ranking makes progress, that pairings remain, or that the
    pool holds still. The stall test below is a cost optimisation on top of
    it, not the thing that makes the loop safe.
    """
    if stats.unmatched_rankable_count < 1:
        return None
    # Nothing to pair against: demanding coverage could never be satisfied.
    if stats.rankable_count < 2:
        return None
    allowance = stats.settlement_allowance
    if allowance is not None and allowance < 1:
        return None
    previous = stats.unmatched_at_last_settlement
    if (
        previous is not None
        and stats.unmatched_rankable_count >= previous
    ):
        return None
    return SupervisorDecision(
        next_task=TaskType.RANK,
        reason=(
            f"{stats.unmatched_rankable_count} hypothesis(es) have no "
            "tournament matches; settle coverage before terminating"
        ),
    )
```

In `_ordered_checks`, insert the new lambda between the stop-signal and
budget-termination entries, and update the docstring's step count:

```python
) -> tuple[Callable[[], SupervisorDecision | None], ...]:
    """Builds the precedence-ordered scheduling checks (steps 1-11)."""
    return (
        lambda: _check_stop_signals(stats),
        lambda: _check_owed_coverage(stats),
        lambda: _budget_termination(stats, budget),
        lambda: _check_retry(stats),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest tests/test_scheduling_policy.py -v
```

Expected: PASS, including all pre-existing tests in the file.

- [ ] **Step 5: Lint, format, typecheck**

```bash
ruff format . && ruff check . && /Users/guy/Code/Co-Scientist/.venv/bin/python -m mypy .
```

- [ ] **Step 6: Commit**

```bash
git add engine/src/co_scientist/scheduling/policy.py engine/tests/test_scheduling_policy.py
git commit -m "feat(scheduling): settle owed tournament coverage before a budget stop"
```

---

### Task 3: The settlement allowance lifecycle

**Files:**
- Modify: `engine/src/co_scientist/agents/supervisor/orchestrator.py:88` (`_init_bookkeeping`), `:248` (`_next_bookkeeping`)
- Test: `engine/tests/test_orchestrator_settlement.py`

**Interfaces:**
- Consumes: `SchedulerStats.unmatched_rankable_count` (Task 1); the `RANK` decision from `_check_owed_coverage` (Task 2).
- Produces: bookkeeping keys `"settlement_allowance"` and `"unmatched_at_last_settlement"`, read back into stats by `_build_scheduler_stats` (already wired in Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/test_orchestrator_settlement.py`:

```python
from co_scientist.agents.supervisor.orchestrator import (
    _init_bookkeeping,
    _next_bookkeeping,
)
from co_scientist.scheduling import SchedulerStats, SupervisorDecision, TaskType


def _settlement_stats(**overrides: object) -> SchedulerStats:
    """Stats for a pool mid-settlement, with overridable allowance state."""
    base: dict[str, object] = {
        "pool_size": 6,
        "rankable_count": 6,
        "unmatched_rankable_count": 4,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


_RANK = SupervisorDecision(next_task=TaskType.RANK, reason="settle")


def test_first_settlement_initialises_and_spends_one_round() -> None:
    # Four unmatched ideas need at most two rounds (two per pairing); the
    # first firing spends one of them.
    book = _next_bookkeeping(_init_bookkeeping([]), _settlement_stats(), _RANK)

    assert book["settlement_allowance"] == 1
    assert book["unmatched_at_last_settlement"] == 4


def test_allowance_is_bounded_by_distinct_pairs() -> None:
    # Two rankable ideas admit exactly one pairing, however many are
    # unmatched, so the allowance can never exceed it.
    stats = _settlement_stats(rankable_count=2, unmatched_rankable_count=2)

    book = _next_bookkeeping(_init_bookkeeping([]), stats, _RANK)

    assert book["settlement_allowance"] == 0


def test_allowance_decrements_and_never_refills() -> None:
    # New hypotheses arriving mid-settlement must not hand the run more
    # rounds: a refillable counter would not bound anything.
    book = {
        "settlement_allowance": 3,
        "unmatched_at_last_settlement": 2,
        "pool_at_last_decision": 6,
    }

    updated = _next_bookkeeping(
        book, _settlement_stats(unmatched_rankable_count=99), _RANK
    )

    assert updated["settlement_allowance"] == 2


def test_allowance_floors_at_zero() -> None:
    book = {"settlement_allowance": 0, "unmatched_at_last_settlement": 1}

    updated = _next_bookkeeping(book, _settlement_stats(), _RANK)

    assert updated["settlement_allowance"] == 0


def test_non_settlement_rank_leaves_the_allowance_alone() -> None:
    # A ranking round requested for ordinary calibration, with nothing owed,
    # must not consume settlement budget.
    book = _init_bookkeeping([])

    updated = _next_bookkeeping(
        book, _settlement_stats(unmatched_rankable_count=0), _RANK
    )

    assert updated.get("settlement_allowance") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest tests/test_orchestrator_settlement.py -v
```

Expected: FAIL — `KeyError: 'settlement_allowance'`, since `_next_bookkeeping`
does not write the key yet.

- [ ] **Step 3: Implement the lifecycle**

In `engine/src/co_scientist/agents/supervisor/orchestrator.py`, add these two
helpers immediately above `_next_bookkeeping`:

```python
def _is_settlement_rank(
    stats: SchedulerStats, decision: SupervisorDecision
) -> bool:
    """Return whether this decision is a ranking round that settles coverage.

    Identified from the decision and the stats that produced it rather than
    signalled by the policy, which stays a pure function. A ranking round
    chosen while hypotheses are unmatched draws on the allowance whichever
    check selected it -- charging every such round keeps the counter
    monotonically decreasing on every path, which is what the termination
    bound rests on.
    """
    return (
        decision.next_task is TaskType.RANK
        and stats.unmatched_rankable_count > 0
    )


def _initial_settlement_allowance(stats: SchedulerStats) -> int:
    """Return the most settlement rounds that could ever be useful.

    One round covers at most two unmatched hypotheses, and the pool admits
    only so many distinct pairings, so the allowance is the smaller of the
    two. Mirrors ``ranking_lifecycle._coverage_floor``, which bounds the
    rounds an individual tournament schedules for the same reason.
    """
    rankable = stats.rankable_count
    max_pairs = rankable * (rankable - 1) // 2
    return min((stats.unmatched_rankable_count + 1) // 2, max_pairs)
```

Then, inside `_next_bookkeeping`, immediately before the final `return
updated`, insert:

```python
    if _is_settlement_rank(stats, decision):
        allowance = updated.get("settlement_allowance")
        if allowance is None:
            allowance = _initial_settlement_allowance(stats)
        # Charged whether or not the round helps, and never replenished, so
        # the override can only fire finitely many times regardless of what
        # ranking does or how the pool changes underneath it.
        updated["settlement_allowance"] = max(0, int(allowance) - 1)
        updated["unmatched_at_last_settlement"] = (
            stats.unmatched_rankable_count
        )
```

Add the two keys to `_init_bookkeeping`'s returned dict, after
`"last_work_task"`, with a comment:

```python
        # None until the first settlement round: the override may fire, and
        # the allowance is sized from the backlog observed at that moment.
        "settlement_allowance": None,
        "unmatched_at_last_settlement": None,
```

Ensure `SupervisorDecision` is imported in the module's imports if it is not
already (it is used in existing type hints, so it should be).

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest tests/test_orchestrator_settlement.py tests/test_supervisor.py tests/test_orchestrator_steering.py -v
```

Expected: PASS.

- [ ] **Step 5: Lint, format, typecheck**

```bash
ruff format . && ruff check . && /Users/guy/Code/Co-Scientist/.venv/bin/python -m mypy .
```

- [ ] **Step 6: Commit**

```bash
git add engine/src/co_scientist/agents/supervisor/orchestrator.py engine/tests/test_orchestrator_settlement.py
git commit -m "feat(scheduling): bound coverage settlement with a spending allowance"
```

---

### Task 4: Mirror the precedence on the model path

**Files:**
- Modify: `engine/src/co_scientist/agents/supervisor/supervisor_decision.py:82` (`_hard_stop`)
- Test: `engine/tests/test_supervisor_decision.py`

**Interfaces:**
- Consumes: `SchedulerStats.unmatched_rankable_count` (Task 1); the `RANK` baseline produced by `required_transition` (Task 2).
- Produces: no new names. `_hard_stop` gains the behaviour of returning `None` for budget-family stops when the baseline settles coverage.

**Why this task is required, not optional.** In `choose_supervisor_task`,
`_hard_stop` is consulted *after* `required_transition`. Without this change it
re-imposes `TERMINATE` over the `RANK` that Task 2 produced, and the whole
feature is dead on the real execution path while the policy unit tests pass.

- [ ] **Step 1: Write the failing test**

Append to `engine/tests/test_supervisor_decision.py`:

```python
def test_hard_stop_yields_to_owed_coverage_but_not_to_cancellation() -> None:
    # _hard_stop runs after required_transition, so without this the RANK the
    # policy just chose is overridden and the feature never reaches a run.
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
        llm_calls=99,
    )

    assert _hard_stop(stats, budget, settling) is None

    cancelled = SchedulerStats(
        pool_size=6,
        rankable_count=6,
        unmatched_rankable_count=2,
        llm_calls=99,
        cancelled=True,
    )
    stop = _hard_stop(cancelled, budget, settling)

    assert stop is not None
    assert stop.next_task is TaskType.TERMINATE
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest tests/test_supervisor_decision.py -k hard_stop_yields -v
```

Expected: FAIL — the first assertion gets a `TERMINATE` decision, not `None`.

- [ ] **Step 3: Implement**

In `engine/src/co_scientist/agents/supervisor/supervisor_decision.py`, add
above `_hard_stop`:

```python
# Stops no amount of owed tournament coverage may defer. The operator asked
# the run to stop, or the content is unsafe; more work is wrong either way.
# The budget family defers instead, because a hypothesis stranded without any
# tournament result is a worse outcome than a bounded overshoot of a ceiling
# that exists to catch runaways.
_IMMEDIATE_STOP_REASONS = frozenset(
    {TerminationReason.CANCELLED, TerminationReason.SAFETY}
)
```

Then, inside `_hard_stop`, replace the body after `termination_reason, message
= reason` so it reads:

```python
    termination_reason, message = reason
    settles_coverage = (
        baseline.next_task is TaskType.RANK
        and stats.unmatched_rankable_count > 0
    )
    if settles_coverage and termination_reason not in _IMMEDIATE_STOP_REASONS:
        # Defer to the scheduler's owed-coverage round. Bounded by the
        # settlement allowance, so this cannot postpone the stop forever.
        return None
    return SupervisorDecision(
        next_task=TaskType.TERMINATE,
        reason=message,
        terminate=True,
        termination_reason=termination_reason,
    )
```

Add `TaskType` to the module's imports from `co_scientist.scheduling` if it is
not already imported there.

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest tests/test_supervisor_decision.py tests/test_scheduling_policy.py -v
```

Expected: PASS.

- [ ] **Step 5: Lint, format, typecheck**

```bash
ruff format . && ruff check . && /Users/guy/Code/Co-Scientist/.venv/bin/python -m mypy .
```

- [ ] **Step 6: Commit**

```bash
git add engine/src/co_scientist/agents/supervisor/supervisor_decision.py engine/tests/test_supervisor_decision.py
git commit -m "fix(supervisor): let owed coverage defer a budget stop, never a cancel"
```

---

### Task 5: The termination guarantee

**Files:**
- Test: `engine/tests/test_orchestrator_settlement.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4. Adds no production code.

This is the load-bearing test. It drives the real decision loop from a state
where ranking never reduces the backlog — the exact shape that would spin
forever without the allowance — and asserts the run terminates.

- [ ] **Step 1: Write the test**

Append to `engine/tests/test_orchestrator_settlement.py`:

```python
from co_scientist.scheduling import Budget, TerminationReason, decide_next_task


def test_settlement_terminates_while_the_backlog_still_shrinks() -> None:
    # The load-bearing case. The backlog falls by one every round, so the
    # stall guard never fires and cannot be what stops this -- only the
    # allowance can. A pool of 8 with 8 unmatched is granted 4 rounds, which
    # runs out long before a backlog shrinking one at a time reaches zero.
    #
    # The loop cap is a test failsafe, not the mechanism under test: 50 is
    # far above the largest allowance this pool could be granted.
    budget = Budget(max_iterations=5, max_llm_calls=10)
    book = _init_bookkeeping([])
    backlog = 8
    decision = None
    rounds = 0

    for _ in range(50):
        stats = SchedulerStats(
            pool_size=8,
            reviewed_count=8,
            rankable_count=8,
            unmatched_rankable_count=backlog,
            llm_calls=999,
            settlement_allowance=book.get("settlement_allowance"),
            unmatched_at_last_settlement=book.get(
                "unmatched_at_last_settlement"
            ),
        )
        decision = decide_next_task(stats, budget)
        if decision.terminate:
            break
        book = _next_bookkeeping(book, stats, decision)
        backlog -= 1
        rounds += 1

    assert decision is not None
    assert decision.terminate
    assert decision.termination_reason is TerminationReason.BUDGET
    # Stopped on the allowance (4 rounds), with work still outstanding.
    assert rounds == 4
    assert backlog > 0


def test_settlement_terminates_when_ranking_never_helps() -> None:
    # The stall guard's own case: a round that changes nothing must not be
    # repeated. Terminates faster than the allowance alone would.
    budget = Budget(max_iterations=5, max_llm_calls=10)
    book = _init_bookkeeping([])
    decision = None

    for _ in range(50):
        stats = SchedulerStats(
            pool_size=8,
            reviewed_count=8,
            rankable_count=8,
            unmatched_rankable_count=8,
            llm_calls=999,
            settlement_allowance=book.get("settlement_allowance"),
            unmatched_at_last_settlement=book.get(
                "unmatched_at_last_settlement"
            ),
        )
        decision = decide_next_task(stats, budget)
        if decision.terminate:
            break
        book = _next_bookkeeping(book, stats, decision)

    assert decision is not None
    assert decision.terminate


def test_settlement_allowance_is_monotonically_decreasing() -> None:
    # The termination proof rests on this and nothing else: the counter
    # never increases, on any path, whatever the pool does.
    book = _init_bookkeeping([])
    seen: list[int] = []

    for unmatched in (8, 8, 12, 3, 40):
        stats = _settlement_stats(
            rankable_count=8,
            unmatched_rankable_count=unmatched,
            settlement_allowance=book.get("settlement_allowance"),
        )
        book = _next_bookkeeping(book, stats, _RANK)
        seen.append(int(book["settlement_allowance"]))

    assert seen == sorted(seen, reverse=True)
    assert seen[-1] == 0
```

- [ ] **Step 2: Run the tests**

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest tests/test_orchestrator_settlement.py -v
```

Expected: PASS. If either loop test hits the 50-iteration cap, the allowance
is being refilled somewhere — check that `_next_bookkeeping` reads the
existing value rather than recomputing it from the current backlog.

The `rounds == 4` assertion in the first test is the one that matters: it
proves the allowance stopped the loop rather than the stall guard, which
never fires there because the backlog falls every round.

- [ ] **Step 3: Run the full engine suite**

```bash
PYTHONPATH=/Users/guy/Code/Co-Scientist/.claude/worktrees/baseline-elo-scoring-bfd98b/engine/src /Users/guy/Code/Co-Scientist/.venv/bin/python -m pytest -q
```

Expected: all pass. Note any pre-existing failures against a clean checkout
before attributing them to this work.

- [ ] **Step 4: Lint, format, typecheck**

```bash
ruff format . && ruff check . && /Users/guy/Code/Co-Scientist/.venv/bin/python -m mypy .
```

- [ ] **Step 5: Commit**

```bash
git add engine/tests/test_orchestrator_settlement.py
git commit -m "test(scheduling): prove coverage settlement always terminates"
```

---

## Verification

After Task 5, confirm the spec's acceptance shape end to end:

- A pool of 48 rankable hypotheses with 13 unmatched and an average coverage
  of 1.46 schedules `RANK` rather than terminating.
- The same pool with `cancelled=True` terminates immediately.
- Repeated settlement rounds that never reduce the backlog terminate within
  the allowance.

All three are covered by the tests above; re-read them against the spec's
"Testing" section before declaring the work done.

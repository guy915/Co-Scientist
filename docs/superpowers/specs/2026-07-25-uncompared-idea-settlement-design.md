# Settling uncompared ideas before a run ends

Date: 2026-07-25
Status: approved, not yet implemented

## Problem

A run can finish with hypotheses that never entered the tournament. They have
no Elo result, and the Ideas tab now labels them "Unranked" (as distinct from
"Disqualified", which names ideas the reviews or the evidence gate excluded on
the merits).

An unranked idea is a real cost: it was generated, reviewed, and paid for, and
then presented with no indication of where it stands. In a recent production
run 13 of 48 ideas had no matches.

## Root causes

Two independent mechanisms produce the same end state.

### A. The coverage gate is an average

`policy._check_tournament_coverage` (step 7 of `_ordered_checks`) schedules a
tournament while `stats.match_coverage < min_match_coverage`, where
`match_coverage` is the *mean* matches per rankable hypothesis and the
threshold is 1.0.

A mean of 1.0 is satisfiable with individual hypotheses at zero: 35 ideas at
two matches each averages 1.46 across 48, passing the gate while 13 have never
played. No interruption is required. This is the likely cause of the observed
run.

A per-hypothesis floor does exist — `ranking_lifecycle._coverage_floor`, which
guarantees `_tournament_round_count` returns enough rounds to cover every
never-matched idea even after `tournament_pairs` is spent. But it applies only
once ranking has been scheduled. The average gate decides whether ranking is
scheduled at all, so the floor is never consulted.

### B. Termination outranks owed coverage

In `_ordered_checks`, `_check_stop_signals` (cancel, safety) is step 1 and
`_budget_termination` (LLM calls, tasks, wall clock) is step 2, both above the
coverage check at step 7. `supervisor_decision._hard_stop` enforces the same
precedence over the model's advisory allocation.

So a run that trips any hard ceiling terminates immediately, with owed
comparisons outstanding and no settle-up step.

## Design

One new check, inserted between stop signals and budget termination. Both root
causes are addressed by its position and its predicate.

```
1. _check_stop_signals          (cancel, safety)      unchanged, still wins
2. _check_owed_coverage         NEW
3. _budget_termination
4. ...                                                unchanged
```

The new check returns `RANK` when **any** rankable hypothesis has zero matches.
Being per-hypothesis rather than an average fixes A; sitting above
`_budget_termination` fixes B. Sitting below `_check_stop_signals` preserves
immediate cancel and safety stops, which was an explicit decision: the operator
asked to stop, or the content is unsafe, and further work is wrong in both
cases.

The existing average gate at step 7 is unchanged. It serves a different goal —
refining the ordering once everyone has played at least once — and continues to
do so.

### Why this does not reinstate the loop the average was chosen to avoid

`SchedulerStats.match_coverage` documents the existing rationale: "Average
rather than minimum so the gate is reachable by a bounded tournament." A
minimum-based gate can demand rounds a bounded tournament cannot supply and
loop forever.

That reasoning is correct and the new check does not violate it, because the
new check is not gated on reachability at all. It is bounded by an allowance
that decreases whether or not it succeeds, so it terminates even when its
condition is permanently unsatisfiable. The average gate keeps its reachability
property; the new check replaces reachability with a variant argument.

### The settlement allowance

A counter in the orchestrator bookkeeping (`orchestrator_state`, already
checkpointed and restored on resume):

- **Initialised once**, on the check's first firing, to
  `min(ceil(unmatched / 2), max_pairs)` where `max_pairs` is
  `rankable_count * (rankable_count - 1) / 2` — the same bound
  `_coverage_floor` already computes, being the most rounds that could ever be
  useful.
- **Decremented by one on every firing**, whether or not the round reduced the
  uncompared count.
- **Never increased and never re-initialised** for the life of the run: not
  when hypotheses are added mid-settlement, not on resume from a checkpoint.
- At zero the check is permanently inert.

The policy does not mutate the counter. `required_transition` and
`decide_next_task` are documented as pure functions of `SchedulerStats` and
`Budget`, and that purity is what makes the ordered checks testable in
isolation — so the allowance travels the same way every other signal does. The
orchestrator reads it from bookkeeping into `SchedulerStats`; the policy only
reads it; `_next_bookkeeping` writes the decremented value back after the
decision is made. It identifies a settlement `RANK` by the condition that
produced it (`stats.unmatched_rankable_count > 0` and the decision is `RANK`),
which is derivable from what it already receives.

**Termination guarantee.** The allowance is a natural number that strictly
decreases on every firing and is never increased. It therefore fires finitely
many times, and the run reaches a terminal decision.

The guarantee is structural. It does not depend on ranking making progress, on
matchmaking covering any particular hypothesis, on distinct pairs remaining, or
on the pool holding still. Nothing outside the counter can feed the counter.

### Stall detection (optimisation, not safety)

The check also stops claiming priority when a tournament ran and the uncompared
count did not fall, comparing against the count recorded at the previous
firing. On the first firing there is no previous count and the check proceeds.
This exists to avoid spending the full allowance on rounds that achieve
nothing — each round is a real LLM debate.

It is explicitly **not** load-bearing. If it were removed or broken,
termination would still hold by the allowance alone. Implementations and
reviews should treat it as a cost optimisation.

### Secondary guard

The check does not fire when `rankable_count < 2`, matching the existing
coverage check. With fewer than two eligible ideas there is nothing to pair.

## Components

| File | Change |
|---|---|
| `engine/src/co_scientist/scheduling/models.py` | Add `unmatched_rankable_count`, `settlement_allowance`, and `unmatched_at_last_settlement` to `SchedulerStats`, documented like their neighbours. |
| `engine/src/co_scientist/scheduling/policy.py` | Add `_check_owed_coverage`; insert it into `_ordered_checks` between `_check_stop_signals` and `_budget_termination`. Reads only; mutates nothing. |
| `engine/src/co_scientist/agents/supervisor/orchestrator.py` | Compute `unmatched_rankable_count` in `_rankable_coverage`; thread the three new fields through `_StatsScalars` and `_build_scheduler_stats`; own the allowance lifecycle in `_init_bookkeeping` / `_next_bookkeeping`. |
| `engine/src/co_scientist/agents/supervisor/supervisor_decision.py` | Mirror the precedence in `_hard_stop` so the model path cannot bypass owed coverage either. |

The allowance lives in the bookkeeping dict the orchestrator already threads
and checkpoints, so no new persistence surface is introduced.

## Data flow

1. `orchestrator_node` computes `SchedulerStats`, now including
   `unmatched_rankable_count` and the allowance fields read from bookkeeping.
2. `required_transition` runs the ordered checks. Cancel and safety stop first.
3. `_check_owed_coverage` returns `RANK` when ideas are uncompared, at least
   two are rankable, the allowance is non-zero, and the previous firing (if
   any) reduced the uncompared count. It reads these from `stats` and mutates
   nothing.
4. Otherwise the run proceeds to budget termination and the rest unchanged.
5. `_next_bookkeeping` recognises a settlement `RANK`, initialises the
   allowance if this was the first firing, decrements it, and records the
   uncompared count observed at this firing.

## Error handling and edge cases

- **Fewer than two rankable ideas**: check inert; run stops normally.
- **All distinct pairs exhausted**: ranking returns no matches, stall detection
  fires after one round, allowance guarantees the stop regardless.
- **Hypotheses added mid-settlement** (scientist input, late continuation):
  allowance does not refill; they may end Unranked, which is correct and
  labelled.
- **Crash and resume**: allowance restores from the checkpoint at its decremented
  value. A resumed run cannot refill it.
- **Ranking task fails and exhausts retries**: unchanged behaviour — nothing
  automatically recovers a failed task. The allowance drains and the run stops.
- **Worst case overall**: allowance exhausts with ideas still uncompared. This
  is today's behaviour, now honestly labelled "Unranked".

## Testing

All decision logic is a pure function of `SchedulerStats` and `Budget`, so
these are fast, exact unit tests in the engine suite.

**Load-bearing test.** Drive the decision loop from a state where ranking never
reduces the uncompared count, and assert a terminal decision is reached within
the allowance. This encodes the termination guarantee directly rather than a
symptom of it.

Supporting tests:

- Healthy average with uncompared ideas (the 35/13 shape) schedules `RANK`.
- Budget exhausted with ideas owed returns `RANK`, not `TERMINATE`.
- Cancelled with ideas owed returns `TERMINATE`.
- Safety-blocked with ideas owed returns `TERMINATE`.
- Allowance does not refill when hypotheses are added mid-settlement.
- `rankable_count < 2` leaves the check inert.
- Every idea already compared reproduces current behaviour exactly.
- `_hard_stop` mirrors the precedence on the model path.

## Out of scope

- The "don't start a wave you cannot afford to rank" alternative. Rejected: it
  must predict wave size and comparison cost before either exists, and a
  conservative estimate silently ends runs early, doing less than the budget
  allowed. The settle-up approach needs no estimate because the work has
  already happened when the amount owed is computed.
- Changing `tournament_pairs` tier defaults.
- The frontend labels, already shipped in `dc69499b`.

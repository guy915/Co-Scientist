# Engine operation boundaries after the second architecture pass

The [second pass](../../decisions/2026-10-02-architecture-second-pass.md)
finished generation operations, evidence ownership, API services, MCP storage,
evaluation identities and frontend refresh ownership. This design covers the
remaining API imports of private Ranking, Reflection and Evolution helpers.
It is forward work, separate from the completed campaign in root `PLAN.md`.

## Goal and ownership

The app should consume named engine operations for scientific work. The engine
owns prompt/context assembly, scientific selection, review gates, debate depth,
Elo calculation and evolution context. The app retains durable scheduling,
eligibility admission, leases, task isolation, checkpoint guards, telemetry,
ownership checks and transaction commits. Engine operations perform no store
writes and import no app modules.

Each agent package exports its supported operations and their result types.
Move shared behavior below graph orchestration; keep graph nodes as consumers.
Existing private engine compatibility imports may remain where tests or library
callers still use them. App production code must consume the public boundary.
Do not replace private imports with dynamic attribute access or a renamed
facade whose implementation reaches back into graph orchestration.

## Ranking

Expose round preparation/budget/finalization, deterministic pairings, immutable
prompt and judging contexts, one-match judging and one-match Elo application.
The public judgment carries the winner, raw response and budgeted turns; the
applied result carries the serialized matchup detail and actual call count.

Preserve these graph/durable adaptations:

- The durable skip check computes its budget over the full hypothesis pool;
  tournament preparation uses the eligible pool.
- Graph matchmaking selects one pair after each Elo commit. Durable scheduling
  selects a bounded wave from one rating snapshot. The app keeps wave selection,
  exclusions, failure isolation and wave-order commits.
- Graph retains its sorted eligible list; durable waves rebuild eligible ideas
  in checkpoint pool order. Preserve that order because weighted selection uses
  it. Durable admission requires peer review; graph admission uses rankability.
- Graph prompt guidance is captured for the tournament, and its median Elo is
  refreshed before each match. Durable guidance and median are captured once
  per checkpointed wave. Context construction must not repeat an O(pool size)
  median calculation for every concurrent matchup.
- Graph judging receives `preferences`; durable judging currently omits them.
  Both receive scientist criteria. Make preferences an explicit optional input
  to the public prompt-context operation and characterize both callers.
- Count response `debate_turns` when present, falling back to budgeted depth.
  Preserve confidence-based Elo knobs, detail provenance and progress payloads.

## Reflection

Expose initial review gating, deep-verification selection, a single-hypothesis
verification operation, verification-result validation, observation analysis
and one mature review. Engine operations assemble private contexts, bounded
evidence and concurrency guards. A single durable verification creates a
call-local semaphore; graph batching retains its shared batch limiter.

Keep review payload and research ledger separate. Ordinary model failures may
produce no result; task-control exceptions must propagate unchanged. Durable
observation still rejects missing literature. Preserve once-ever verification
markers, fingerprints, explicit `unverified` failures, and scientist criteria.
Graph verification bounds persisted detail lists; durable aggregation currently
stores the raw result. Graph marks issuance before calls and charges non-null
degraded results; durable marks issuance on aggregation and charges successful
valid results. Graph observation passes pool indices/counts; durable passes
1/1. This pass preserves those differences and funded research-cache reuse.

## Outcome refinement

Promote the evolution context to a public immutable type. Move round-context
assembly below graph orchestration and move the selected-parent projection
from `app.outcome_refinement.context` into an engine operation. Preserve the
parent-only prompt state: goal, preferences, lab constraints and selected
parent; empty meta-review, duplicate list and supervisor guidance. Retain
run/setup/focus guidance, literature and the shared citation reference index.
Sibling hypotheses remain available only for duplicate validation. The app
continues to own action intent, safety checks, replay accounting and commits.

## Constraints and acceptance

- Use Python 3.12, Node.js 22.13+ and Bun 1.3.14 for the full application.
  The standalone engine supports Python 3.10+.
- No new dependencies, dependency-lock edits or vendor changes.
- No SQLite write lock over network I/O. Preserve task keys, leases, retry
  budgets, checkpoint ordering, wire payloads and append-only lineage.
- No asyncio primitive may be shared between worker cohorts' event loops.
- No production environment writes; preserve Railway UID, replica and cache
  placement invariants from root `AGENTS.md`.
- First-party source files remain at most 500 lines; functions at most 40
  executable lines, as enforced by the evaluation gates.
- Commit messages, when used, follow `<type>(<scope>): <subject>`; no tool
  attribution. Current work remains reviewable in the shared working tree.
- Acceptance requires zero app imports of underscore-prefixed engine symbols,
  fresh package imports and offline engine/app regression suites, strict types,
  lint, parity/evaluation smoke and the API runtime import check.

## Separate provider decisions

This section records the policy at design time. Before merge, the separate
[provider-policy change](../../decisions/2026-10-02-provider-policies.md)
introduced bounded tool retries and independent app operation budgets. Final
integration preserves that policy alongside the extraction described here.

Tool turns deliberately propagate throttle/outage/cap errors immediately,
without completion backoff, parking or retry telemetry. Mandatory-reasoning
request construction also differs. App interview, Q&A, announcements, titles,
goal restatement and BYOK probes have distinct timeout/retry/continuation
contracts. Do not route them all through one policy during this extraction.

An offline reproducer found a boundedness defect: alternating reasoning-only
responses and mandatory-reasoning refusals produced 21 physical attempts in
one tool turn before a scripted success ended it. `max_iterations` bounds tool
turns, not attempts inside a turn. Escalation revisits the same reasoning
states indefinitely when no durable call-budget scope is installed.

Correct this separately by refusing an already visited escalation rung for
escalation-only plans. Permit every distinct existing rung once, with at most
four attempts; propagate the current failure when the next rung was visited.
Do not enable standard completion backoff/parking or change request shaping,
tool execution, retry telemetry or the attempt budgets of standard plans.

Broader retry,
parking and app accounting policy changes require a dedicated design describing
which surfaces spend durable budgets and how cancellation/timeouts behave.
App telemetry must not initialize the engine's call-budget counter with an
unlimited ceiling: that registry preserves the first ceiling for the run.

# Public engine operations and finite provider recovery

This continuation follows the completed
[second architecture pass](2026-10-02-architecture-second-pass.md). The
[implementation plan](../superpowers/plans/2026-10-02-engine-operation-boundaries.md)
and [design](../superpowers/specs/2026-10-02-engine-operation-boundaries-design.md)
were written before executing these remaining boundary tasks.

## Ownership

| Boundary | Engine owner | Durable app responsibility |
|---|---|---|
| Ranking | Public lifecycle/pairing functions and immutable context, judgment and Elo operations | Admission, bounded waves, failure isolation, telemetry, successors and commits |
| Reflection | Public gates/selection/item operations; shared verification leaf below orchestration | Issuance markers, retries, aggregation, checkpoint guards and separate ledgers |
| Outcome refinement | Public immutable evolution context, round builder and selected-parent projection | Authorization, sibling duplicate validation, safety, replay accounting and one-child commits |

All fifteen app imports of private engine symbols are removed. AST contracts
guard production imports, including function-local imports, reject reverse
engine-to-app dependencies and keep shared operations below graph coordinators.
An initial lazy verification cycle was caught by a failing direction guard;
the shared context/evidence/execution code now lives in `reflection/verification.py`.

## Characterized adaptations

Ranking keeps graph guidance for a tournament and refreshes median Elo before
each match. Durable execution captures both once per wave, preserves checkpoint
pool order and commits surviving outcomes in scheduled order. Graph judging
retains preferences; durable judging continues to omit them. Scientist criteria,
actual debate-turn accounting, deterministic seeds, full-pool skip budgeting,
eligible-pool preparation and peer-review admission retain their prior rules.

Reflection keeps ordinary item degradation separate from worker control-flow
exceptions. Graph batches retain their shared limiter, issuance-before-call
marker, bounded stored details and accounting of non-null degraded results.
Durable items use call-local guards; aggregation retains raw payloads, records
issuance for all outcomes and meters valid successful items. Existing source
evidence bounds, meta-review inclusion and funded research reuse remain intact.
Malformed list/dict verdicts now return invalid instead of aborting aggregation
with an unhashable-value exception; valid verdict strings are unchanged.

Outcome refinement retains run guidance, analyzed literature and citation keys
while prompting on the selected parent, goal, preferences and lab constraints.
Unrelated meta-review, supervisor guidance, duplicates and sibling prompt text
remain excluded. Siblings still participate in duplicate validation.

## Provider boundedness fix

An offline public-entry reproducer alternated reasoning-only responses and
mandatory-reasoning refusals. Both failure orders reached a finite success
sentinel after 21 requests; without that sentinel they could repeatedly visit
the same two escalation states within one tool turn.

Escalation-only calls now visit each recovery rung once. The reproducer stops
after three requests, propagating the current failure. The current four-rung
ladder permits at most four attempts, including initial and legitimate recovery
requests. Standard completion retry budgets, request shaping, tool execution,
raw throttle/outage propagation and absent tool retry telemetry remain intact.
Broader tool backoff/parking and app provider-accounting decisions are separate.

## Test and review quality

Contract tests characterize the public operations and their observable effects.
Existing spies moved to the actual public/defining consumers. Full suites caught
remaining old verification/observation patch sites; independent review caught
outcome-gate fixtures bypassed by the new consumers. The gate regression now
asserts that the child's full/simulation review, verification and judging stubs
are reached. Existing assertions were retained. These fixes have recorded
failing and passing runs.

Independent scoped reviews of all four implementation tasks pass. Ranking,
Evolution and provider recovery had no findings; Reflection's test migration
and remaining graph alias findings were corrected and independently rechecked.

## Verification

- Full engine: 3,472 passed, four platform/optional skips.
- Full API: 2,314 passed after the consumer-fixture corrections.
- Repository Python/frontend lint and strict Python types pass; parity verifies
  all 115 ledger rows, all 214 evaluation tests pass, and offline safety/citation
  smoke passes.
- API image rebuilt with the second pass's temporary BuildKit CA-secret mount;
  source trust settings and dependency locks remain unchanged. Default-user
  runtime smoke imports all 318 engine modules and the public operations; no
  build-time database remains in the image.
- Fresh processes imported all 318 engine and 284 app production modules.
- Final whole-working-tree review passes with no new actionable regressions;
  dependency guards, source-size gates and whitespace checks pass.

No provider-backed experiment, production configuration change, deployment,
commit or push was performed. Vendored sources and dependency locks are intact.

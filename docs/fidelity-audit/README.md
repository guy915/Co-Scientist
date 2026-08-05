# Google Co-Scientist fidelity audit

How far this repository is from Google DeepMind's AI Co-Scientist (Nature 2026,
*Accelerating scientific discovery with Co-Scientist*) and the Google Labs
**Hypothesis Generation** product — and what to do about it.

| Document | Purpose |
|---|---|
| [FINDINGS.md](FINDINGS.md) | Every distinct gap, deduplicated, with severity, class, and provenance. Also: accepted divergences, the 2026-08-05 re-verification, confirmed matches, corpus-integrity corrections, evidence boundaries, audit disagreements |
| [PLAN.md](PLAN.md) | The work queue, in 13 stages |

> **This project is not a Google clone.** The audits scored it as an attempted
> replica, so every deviation read as a violation. That premise was retired on
> 2026-08-05: 21 findings are now closed as
> [accepted divergences](FINDINGS.md#accepted-divergences) and the plan's
> "visible product" stage was deleted rather than deferred. What remains is
> ordinary defect work. Read that section before acting on any row.

Evidence screenshots: [`docs/assets/fidelity-audit-2026-07-20/`](../assets/fidelity-audit-2026-07-20/)
— 15 captures at desktop 16:9, desktop 2:1, and mobile 1:2.

## Where this came from

Three independent audits, synthesized here into one register. They raised 506
rows between them in three incompatible vocabularies; the substance is preserved
in FINDINGS.md and the originals remain in git history.

| | 2026-07-12 | 2026-07-20 | 2026-07-21 |
|---|---|---|---|
| Revision | pre-campaign tree | `11a31082` | `11a31082` |
| Rows | 232 (`A01`–`M20`) | 216 (`F-*`, `EB-*`, `OP-*`) | 58 (`R1`–`R58`) |
| Method | source inspection + live local service + a real-provider run | source inspection + **isolated runtime reproduction** + **browser captures** | exhaustive source reading (14 subsystem dossiers, `file:line`) + **offline end-to-end probe** |
| Strongest evidence | a real-provider run whose citation audit was 0 verified / 0 partial / 13 unsupported | 2 reproducible offline runs with SQL reconciliation, 15 screenshots, 10 dated live Google sources | empirical confirmation of engine invariants (Elo 1200, evolution new-only, proximity `edges = 0`) |
| Only audit to cover | — | operations, privacy, packaging, CI, deployment; accessibility | corpus-integrity corrections; several specific engine defects |

All three declined to assign a numerical fidelity score, and all three concluded
a literal 1:1 claim is unprovable from public evidence. The defensible target is
an **evidence-bounded reconstruction**: exactly implement every verified public
behavior, label every local choice, and never call a proprietary unknown
"matched".

## Verdicts

- **2026-07-12** — "inspired by Google Co-Scientist", not a behavioral replica.
- **2026-07-20** — "a functioning local Co-Scientist-inspired research workbench
  with meaningful published-mechanism coverage and substantial non-faithful
  product/operations extensions."
- **2026-07-21** — "a strong, working approximation of the paper's reasoning loop
  with several correctness gaps; the product is a recognizable but clearly
  distinct re-skin."

The engine is closest to the paper; the product surface is furthest from Google's.

## Reading rules

1. **Only reachable, working behavior counts.** No audit credits names, schemas
   without consumers, dormant API clients, unused UI, comments, plans, seeded
   demos, offline fixtures, or passing tests that exercise a different shape than
   production.
2. **A feature that exceeds, replaces, or improves on Google's design is a
   fidelity violation**, not an advantage — recorded as `ext` or `divergent`.
3. **The project's own claims are not evidence.** No audit credits
   `docs/FIDELITY.md`, `docs/PARITY.md`, `docs/UI-FIDELITY.md`, `.remember/`, or
   prior closure matrices. Where those disagree with FINDINGS.md, they are the
   ones that are wrong.
4. **Much of `references/core/google-co-scientist/` files 02–09 is
   clone-invented**, not Google canon — including the Elo-leaderboard Ideas tab,
   the 12-agent roster, and the 3-persona debate. See the corpus-integrity
   corrections in FINDINGS.md before treating any reference doc as a requirement.

## The 2026-07-12 campaign

The first audit was followed by an implementation campaign that reconciled all
232 findings and reported 86 implemented, 104 partial. Eight days later the two
later audits independently found several of those behaviors absent again — most
visibly the Standard/Advanced run model, closed as *implemented* on 07-14, was
back to Express/Standard/Extended/Ultra.

Two lessons carried into PLAN.md: closure claims decay, and **behavior that lands
without a test that fails in its absence does not stay landed.**

The campaign's own honest framing is worth keeping: 104 partials, 11 unverifiable
boundaries, and no completed real-provider run — both attempted runs terminated
`blocked` at the claim-level evidence gate, which was correct fail-closed
behavior.

## Status of the findings

The `St` column in FINDINGS.md was re-verified against `main` on **2026-08-05**,
276 commits past the audited revision. Every Critical and High finding was
checked against the working tree; Mediums and Lows were checked where a nearby
commit made staleness likely.

Fifteen findings closed and eleven partly closed — see
[the re-verification log](FINDINGS.md#re-verification-2026-08-05), which cites
the file that decided each verdict and lists what was deliberately not re-read.

One verdict is a trap: **G1 was re-scoped, not fixed.** Contradicted ideas are
now withheld and merely-unsupported ones publish with an "Unverified" badge, so
a claim-gate block relabels an idea rather than suppressing it. Confirm that is
the intended policy before treating the row as closed.

## Recovering the originals

The three source audits, their implementation prompts, the 232-row closure matrix
and its JSON, the session handoffs, and the runtime evidence ledger are all in
git history:

```bash
git log --diff-filter=D --name-only -- 'docs/audits/**'
```

They were removed from the tree in favor of this synthesis, not deleted from
history.

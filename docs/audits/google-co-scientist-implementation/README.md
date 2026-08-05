# Google Co-Scientist fidelity audits

Three independent audits compared this repository against Google DeepMind's AI
Co-Scientist (Nature 2026, *Accelerating scientific discovery with Co-Scientist*)
and the Google Labs **Hypothesis Generation** product. Each is a **dated,
point-in-time record and is never updated** — later work is captured by a later
audit, not by editing an earlier one.

**Start here:** [CROSS-AUDIT-REGISTER.md](CROSS-AUDIT-REGISTER.md) deduplicates
the three registers into one concordance — every finding two or more audits
reached independently, mapped across their ID schemes, plus what has moved on
`main` since. Read that before reading any single audit end to end.

## The three audits at a glance

| | [2026-07-12](2026-07-12/) | [2026-07-20](2026-07-20/) | [2026-07-21](2026-07-21/) |
|---|---|---|---|
| Revision audited | pre-campaign tree | `11a31082` | `11a31082` |
| Findings | 232 (`A01`–`M20`) | 216 (`F-*` 90, `EB-*` 70, `OP-*` 56) | 58 (`R1`–`R58`) over domains `A`–`M` |
| Primary method | source inspection + live local service + a real-provider run | source inspection + **isolated runtime reproduction** + **browser captures** | exhaustive source reading (14 subsystem dossiers, `file:line`) + **offline end-to-end probe** |
| Distinguishing evidence | a real-provider run whose citation audit was 0 verified / 0 partial / 13 unsupported | 2 reproducible offline runs with SQL reconciliation, 15 screenshots at 3 viewports, 10 dated live Google sources | empirical confirmation of engine invariants (Elo 1200, evolution new-only, proximity `edges = 0`) |
| Unique coverage | the only audit followed by an implementation campaign | operations, privacy, packaging, CI, deployment (`OP-*`) and accessibility (`F-A11Y-*`) | corpus-integrity corrections; specific engine defects (`{{MISSING:...}}` debate prompt, ungrounded+cached assumptions, inert diversity angles) |
| Verdict | "inspired by Google Co-Scientist", not a behavioral replica | "functioning local Co-Scientist-inspired research workbench with substantial non-faithful extensions" | "a strong, working approximation of the paper's reasoning loop … a recognizable but clearly distinct re-skin" |

All three decline to assign a numerical fidelity score, and all three agree a
literal 1:1 claim is unprovable from public evidence.

## Contents

### [`2026-07-12/`](2026-07-12/) — audit **and** the implementation campaign that followed

| File | What it is |
|---|---|
| [FIDELITY-DIFF.md](2026-07-12/FIDELITY-DIFF.md) | The 232-row audit, domains A–M |
| [IMPLEMENTATION-PROMPT.md](2026-07-12/IMPLEMENTATION-PROMPT.md) | Governing prompt for the campaign: 12 ordered work areas, 17 acceptance conditions |
| [CLOSURE-MATRIX.md](2026-07-12/CLOSURE-MATRIX.md) | Per-finding ledger of all 232 rows with implementation + verification evidence |
| [closure-overrides.json](2026-07-12/closure-overrides.json) | Machine-readable source of the matrix: `findings` (232), `acceptance` (17), `verification_log` (16) |
| [HANDOFF.md](2026-07-12/HANDOFF.md) | Mid-campaign session handoff: worktree state, traps, next-action sequence |
| [FINAL-STATUS.md](2026-07-12/FINAL-STATUS.md) | Campaign outcome: 86 implemented / 104 partial / 6 matched / 13 extension / 12 missing / 11 unverifiable |
| [SESSION-SUMMARY.md](2026-07-12/SESSION-SUMMARY.md) | Condensed transcript of the audit + implementation session |

### [`2026-07-20/`](2026-07-20/) — runtime-and-browser audit

| File | What it is |
|---|---|
| [FIDELITY-DIFF.md](2026-07-20/FIDELITY-DIFF.md) | The 216-row audit, plus 15 credited working foundations (`M01`–`M15`) and 27 evidence boundaries (`U01`–`U27`) |
| [IMPLEMENTATION-PROMPT.md](2026-07-20/IMPLEMENTATION-PROMPT.md) | Phased remediation plan `P0`–`P7`, with a required test matrix and closure proofs |
| [RUNTIME-EVIDENCE.md](2026-07-20/RUNTIME-EVIDENCE.md) | Sanitized ledger for the two isolated offline runs cited as `R1`–`R3`: launch env, requests, results, reconciliation SQL |

Screenshots live at [`docs/assets/fidelity-audit-2026-07-20/`](../../assets/fidelity-audit-2026-07-20/)
(15 captures at desktop 16:9, desktop 2:1, and mobile 1:2).

### [`2026-07-21/`](2026-07-21/) — source-exhaustive audit

| File | What it is |
|---|---|
| [FIDELITY-DIFF.md](2026-07-21/FIDELITY-DIFF.md) | The 58-row severity-ordered register, domains A–M, every claim anchored to `file:line`; §4 corrects the local reference corpus; §8.5 records the empirical verification |
| [IMPLEMENTATION-PROMPT.md](2026-07-21/IMPLEMENTATION-PROMPT.md) | Self-contained remediation plan in tiers `T0`–`T3`, keyed to the `R*` register |

## Precedence when the audits disagree

1. **Later audit wins on repository state.** 07-20 and 07-21 audit the same
   revision and supersede 07-12's description of the tree — including 07-12's
   own closure claims. 07-20 records this explicitly under *Corrections to prior
   repository closure claims*.
2. **The audit that ran the code wins on runtime behavior.** Where a finding was
   reproduced (07-20's `R1`–`R8`, 07-21's §8.5), that beats source reading.
3. **07-21 wins on what is genuinely a Google requirement.** Its §4 shows that
   several things the local `references/` corpus presents as Google canon are
   clone-invented — the 12-agent roster, the 3-persona debate, the M3-blue design
   system, cross-run memory, and, most consequentially, the **Elo-leaderboard
   Ideas tab** and **NotebookLM export**. Earlier audits scored against some of
   these. See [the register's disagreements section](CROSS-AUDIT-REGISTER.md#where-the-audits-disagree).
4. **No audit credits the project's own claims.** All three explicitly refuse to
   treat `docs/FIDELITY.md`, `docs/PARITY.md`, `docs/UI-FIDELITY.md`, `.remember/`,
   or prior closure matrices as evidence.

## Why the 07-12 campaign's closure claims do not hold

The campaign reconciled all 232 findings and reported 86 implemented. Eight days
later, 07-20 and 07-21 independently found several of those behaviors absent from
the tree again — most visibly the Standard/Advanced run model (`B01`, closed as
*implemented* on 07-14) was back to Express/Standard/Extended/Ultra. Read
[FINAL-STATUS.md](2026-07-12/FINAL-STATUS.md) as a record of what was *built*,
not of what the tree *contains*; the campaign's own honest framing (104 partials,
no completed real-provider run) is in its §2–§3.

## Known caveats in these documents

- **The closure matrix generator is gone.** [CLOSURE-MATRIX.md](2026-07-12/CLOSURE-MATRIX.md)
  instructs regenerating via `python scripts/build_fidelity_closure.py`. That
  script does not exist anywhere in the tree, so the matrix and
  [closure-overrides.json](2026-07-12/closure-overrides.json) must be kept in
  sync by hand, or the matrix treated as frozen.
- **The 07-12 closure counts disagree with themselves.** Acceptance condition 17,
  in both [CLOSURE-MATRIX.md](2026-07-12/CLOSURE-MATRIX.md) and
  [closure-overrides.json](2026-07-12/closure-overrides.json), says "85
  implemented, 105 partial". Counting the 232 `findings` entries in the JSON gives
  **86 implemented / 104 partial**, which is what
  [FINAL-STATUS.md](2026-07-12/FINAL-STATUS.md) §2 and this index report. The
  acceptance-condition prose is stale by one finding.
- **One source link points at a deleted file.** 07-21's `M2` cites
  `app/app/engine_adapter/workflow.py` as dead code; it was subsequently removed
  by `4d6ed845`, so that link no longer resolves. The finding was correct and has
  been acted on — the dangling link is the evidence trail, deliberately left intact.
- **One link is an authoring placeholder.** 07-21 cites
  `engine/mcp_server/...` with a literal ellipsis; it was written that way.
- **07-20's app-suite result was load-sensitive.** Its `631 passed, 3 failed, 32
  errors` was recorded while concurrent audit services were running; the audit
  says so and declines to call every error a product defect (`OP-023`).

## Provenance

Consolidated on 2026-08-05 from three branches — `docs/fidelity-audit-2026-07-12`,
`docs/fidelity-audit-2026-07-20`, and `docs/fidelity-audit-2026-07-21` — which
branched from the same commit and shared no files. The merge was purely additive:
every document is byte-identical to its branch original apart from filename
references updated for this directory layout. Files were renamed and grouped into
dated folders; the [cross-audit register](CROSS-AUDIT-REGISTER.md) is the only new
analysis.

# Corpus Extraction Status

Closing wave of the fidelity campaign (branch `fix/published-prompt-fidelity`,
starting at HEAD `fca7a365`). Report date: 2026-09-02.

**What this document is not.** `docs/CORPUS-EXTRACTION.md`'s status column
(`done` / `work` / `reject` / `external` / `unclear` / `adapted`) is a
historical audit trail — updated ad hoc as fixes landed, and known to be
unreliable in both directions: rows marked `work` that are already built
(the table is never touched when a fix lands), and rows whose evidence does
not survive a read (see `R1-17`, already self-corrected in that file, as the
worked example of the failure mode). This document does **not** edit that
table or the Appendix. It records what is actually true right now, checked
against the code and git history, for every row still marked `work` or
`unclear`.

**Scope.** Every `work`/`unclear` row in regions R1, R6, R8, R9, R10, R11,
R12, R13, R14, MA, MC, MO, MP — 79 rows (78 ordinary rows plus `R13-12`'s
part (a), which a naive table-column split misreads because the row's own
text contains a literal `|` inside a video title). Rows already `done`,
`reject`, `adapted`, or `external` are not re-audited, except where one was
noticed in passing to be wrong — logged under "Noticed in passing" at the
end, per region.

**Method.** For each row: read the cited source/claim text (the verbatim
Appendix at `docs/CORPUS-EXTRACTION.md:1650+` for paper-text questions —
never a fresh grep against it, which is exactly how `R1-17`'s false
correction happened), then check the current code, its tests, and
`docs/PARITY.md` for the same requirement. Classify into exactly one of:

- **BUILT** — implemented; cite file:line or commit.
- **OPEN** — genuine work remaining; state what it needs in one line.
- **DECISION** — not resolvable from the corpus; state the question for the
  owner.
- **FALSE** — the row's evidence does not survive a read; quote the claim
  and state what is actually true.

**BUILT vs. FALSE, when both look like "the row says X, the code has X".**
The discriminator is which came first. `git log -S'<row text>' --
docs/CORPUS-EXTRACTION.md` (or the region's bulk-add commit — the checklist
was written in a handful of large commits, not row by row) dates the row;
the feature's own commit dates the fix. Feature commit before the row →
the row was already stale when written, but its *evidence* was still
accurate at the time → **BUILT**, not FALSE — FALSE is reserved for rows
whose cited evidence was never true, not rows the table failed to update.
Feature commit after the row → straightforwardly **BUILT** as unrecorded
follow-through. A row is **FALSE** only when reading the cited source or
code today shows the claim itself does not hold, independent of timing.

**Commit discipline.** One commit per region, immediately after that
region's section is written — this document is built incrementally so a
partial pass is never lost.

---

## Summary (filled in as each region is audited)

| Region | Rows | BUILT | OPEN | DECISION | FALSE |
|---|---|---|---|---|---|
| R1 | 3 | | | | |
| R6 | 2 | | | | |
| R8 | 3 | | | | |
| R9 | 3 | | | | |
| R10 | 9 | | | | |
| R11 | 4 | | | | |
| R12 | 13 | | | | |
| R13 | 6 | | | | |
| R14 | 20 | | | | |
| MA | 6 | | | | |
| MC | 1 | | | | |
| MO | 5 | | | | |
| MP | 3 | | | | |
| **Total** | **78** | | | | |

(R13-12 is tracked half as `work` (part (a)) and half `external` (part (b),
out of scope); it counts once, under R13, for part (a) only — hence 78, not
79, rows actually classified.)

---

## R1 — SSR consolidation

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R1-12 | Elo-quality concordance should bucket by Elo in 50-point increments and compute accuracy per bucket | **OPEN** | `evaluations/elo_concordance_eval.py` (371 lines) has zero occurrences of "bucket", "increment", or "50" — confirmed by direct grep, not the row's own claim taken on faith. It scores Kendall's tau-b rank concordance instead, a different method entirely. `docs/PARITY.md:207` (`EVAL-ELO-CALIB-001`, `partial`) names the licensed-corpus gap but not this method gap — the two are independent residuals |
| R1-13 | Scaling should partition one run's hypotheses into ten equal temporal buckets, tracking best/top-10-average Elo across them | **OPEN** | `evaluations/scaling_eval.py:64` — `scaling_curve()` sorts snapshots by `(llm_calls, tasks)` across separate runs at different compute *tiers*; there is no within-run temporal partition anywhere in the file or in `scaling_budget_driver.py`. `docs/PARITY.md:208` (`EVAL-SCALING-001`, `partial`) already states the offline curve "measures the harness rather than the model" — that residual is about credentials, not this structural gap, which is still unaddressed |
| R1-18 | Three glossary terms — "novel repurposing candidate", "novel target", "novel mechanistic explanation" — as a controlled vocabulary | **DECISION** | Not implemented as a controlled vocabulary anywhere in engine or app code. One coincidental match: `engine/src/co_scientist/config/examples/indra_ibd.yaml:39` defines "novel mechanistic explanation" as a domain-specific term for one example config (IBD), unrelated to the SSR's system-wide glossary. The open question is unchanged from the row: whether these three terms should be load-bearing (e.g. as an enum somewhere) or are merely descriptive prose the schema doesn't need |

**R1: 0 BUILT / 2 OPEN / 1 DECISION / 0 FALSE.**

Noticed in passing: none.

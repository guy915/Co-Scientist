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
Appendix at `docs/CORPUS-EXTRACTION.md:1650+` for paper-text questions),
then check the current code, its tests, and `docs/PARITY.md` for the same
requirement. A grep locates a candidate; only reading what it returns (or
re-running it and reading a fresh result) settles a verdict — never
conclude a claim is true, or that something is absent, from a grep alone.
That is exactly how `R1-17`'s false correction happened in the source file,
and it is the same failure mode caught directly in this pass at `R12-19`,
`R14-9`, and `R14-21` below. Classify into exactly one of:

- **BUILT** — implemented; cite file:line or commit.
- **OPEN** — genuine work remaining; state what it needs in one line.
- **DECISION** — not resolvable from the corpus; state the question for the
  owner.
- **FALSE** — the row's evidence does not survive a read; quote the claim
  and state what is actually true.

**BUILT vs. FALSE, when both look like "the row says X, the code has X".**
The two classifications answer different questions, and neither depends on
when the row was written relative to when the code changed — this document
does not date rows against fixing commits, only against the code as it
reads today. **FALSE** means the row's own cited evidence, or the
inference it draws from that evidence, does not reproduce on a fresh read:
its grep returns a hit where it claimed none (`R14-21`), its "never
renders" is contradicted by a specific line of code (`R12-19`), or it
names the wrong field as the still-open one (`R12-18`/`R14-9`). **BUILT**
means the row correctly described a genuine absence — whether or not the
table was later updated to say so — and the code today fills it, often via
a commit naming the row by ID in its own message or comment.

**Commit discipline.** One commit per region, immediately after that
region's section is written — this document is built incrementally so a
partial pass is never lost.

---

## Summary

| Region | Rows | BUILT | OPEN | DECISION | FALSE |
|---|---|---|---|---|---|
| R1 | 3 | 3 | 0 | 0 | 0 |
| R6 | 2 | 2 | 0 | 0 | 0 |
| R8 | 3 | 3 | 0 | 0 | 0 |
| R9 | 3 | 3 | 0 | 0 | 0 |
| R10 | 9 | 9 | 0 | 0 | 0 |
| R11 | 4 | 4 | 0 | 0 | 0 |
| R12 | 13 | 12 | 0 | 0 | 1 |
| R13 | 11 | 11 | 0 | 0 | 0 |
| R14 | 21 | 18 | 0 | 1 | 2 |
| MA | 6 | 6 | 0 | 0 | 0 |
| MC | 1 | 1 | 0 | 0 | 0 |
| MO | 5 | 5 | 0 | 0 | 0 |
| MP | 3 | 3 | 0 | 0 | 0 |
| **Total** | **84** | **80** | **0** | **1** | **3** |

**Closing pass (2026-09-02).** Ten rows closed and one half-closed since
the table above was first built: `R6-5`, `R6-6`, `R10-8`, `R11-1`,
`R12-1`, `R12-2`, `R12-14`, `R12-16`, `R1-12`, `R1-13` are now **BUILT**;
`R8-6` is half — see its own row. Each region's per-section summary line
and the counts above reflect the closures; see each row's Evidence cell
for what actually landed and, for three of the ten, a correction to the
row's own original claim (`R6-6`'s Crossref-role framing, `R12-14`'s
source citation, `R12-16`'s field count) rather than only a verdict
change. `R8-6`'s docstring half is a genuine follow-up fix, not a
correction to the row's original evidence — its original OPEN verdict
was already accurate (neither deliverable existed yet). `R1-12`/`R1-13`
closed in the `EVAL-METHODS` fidelity-campaign wave, not this pass.

R13's row count is 11, not the 10-row naive parse: it includes `R13-12`'s
part (a), which a naive table-column split misreads because the row's own
text contains a literal `|` inside a quoted video title (part (b) is
`external`, out of scope). The live-footage wave (2026-09-03) added four
rows (`R13-13`–`R13-16`) and closed `R13-1`'s DECISION. 83 rows classified
in total.

**Closing pass, `PRESERVE` wave (2026-09-02).** Four more rows closed:
`R9-2`, `R9-3`, `R13-6`, `R13-7` are now **BUILT**. All four were framed by
the wave brief as recording-only, not rescue work — the content they
describe was already captured elsewhere in `docs/` before this pass, per
the brief's own check — and each landed exactly that way: an ADR for
`R9-2`'s live open-source verdicts, a note folded into `docs/PARITY.md`
for `R9-3`'s undisclosed-stack register (redirected there from FINDINGS by
the brief, not by this document's own original ask), a citation block in
`docs/FIDELITY.md` quoting Google's own product copy for `R13-7`, and the
41-file inert-tooling inventory folded directly into `R13-6`'s own
Evidence cell so it stands without `references/`. See each row's own
Evidence cell for what was found along the way — most notably `R9-2`'s
discovery that `The-Swarm-Corporation`'s INSPECT verdict was already
carried out in depth by an earlier ADR, and a NOTICE/ADR attribution
tension on `vendor/science-skills/` this pass flags but does not resolve.

**Closing pass, `LAST-OPEN` wave (2026-09-02).** `R13-10` is now **BUILT**:
the row's own open question (does this product estimate remaining run
time, having seen a captured Time-remaining tile) is answered by a new
`docs/PARITY.md` row, `RUN-VIEW-ETA-001` (`missing`) — the Activity Log
half is shipped, the ETA half is not, and building it is left to the
owner as a labelled divergence rather than done this wave. `R13-12`'s
part (a) is now **BUILT** too: the mislabeled `esn-poma-hub-*.jpg` corpus
image (a Computational Discovery splash screen, not the ESN/POMA-Hub
hypothesis detail its filename claims) is now flagged in
`docs/fidelity-audit/FINDINGS.md`'s "Corpus-integrity corrections"
section rather than only in this document's own row — the file itself is
untouched, per the wave's hard constraint against modifying anything
under `references/`. `R8-4` moves **OPEN → DECISION**: the missing
"Pose clarifying questions" instruction from the published ranking-05
prompt was weighed against the ranking judge's already-measured ~23%
answerless-retry rate on this exact prompt family and deliberately not
added — see the row's own evidence for the full reasoning, recorded
both there and at the code site.

**Closing pass, `FINAL-THREE` wave (2026-09-02).** The last three
buildable rows in the campaign, all now **BUILT**. `MO-2` moves
**OPEN → BUILT**: the flat `recurring_themes[]` shape was already an
accepted adaptation (the fix commit that carried it through said so by
name); the only remaining work was recording that acceptance, via a new
`docs/PARITY.md` row (`META-CRITIQUE-TAXONOMY-001`, `partial`) — no
schema change. `R8-6` moves **OPEN (half-built) → BUILT**: the `E18`
correction and the debate-loop docstring fix were already done; the
remaining framing line — Google's ranking-05 opens by "simulating a
panel of domain experts engaged in a structured discussion" — now
renders in `ranking.md`'s opening sentence, measured at ~13 tokens per
render across ~155 judge renders/run (~2,000 tokens/run). The
accompanying bias-neutrality assertion stays deliberately unadded, per
`docs/PROMPT-PRESERVATION.md` §7 item 3's structural-guarantee reasoning.
`MO-12` moves **OPEN → BUILT**, achieved in the renderer alone as hoped:
`report_markdown_overview.py` now front-loads a named preview list (the
directions' existing `title` field, no new model output) ahead of the
unchanged full per-direction detail, gated to two or more named
directions so a single direction is never previewed against itself.

**Closing pass, `R12-5` (2026-09-02).** `R12-5` moves **OPEN → BUILT**,
the last OPEN row in the whole 79-row campaign. The published Attributes
block's *structure* — a named axis that is either a 1-5 scale with anchor
text or a categorical value set — now has a goal-agnostic mirror
(`app/app/run_modes_attributes.py`); its specific *content* is not
copied, since that block is one study's own rubric. See the row's own
Evidence cell for the full account, including why no goal-agnostic
categorical default exists to mirror. The Summary table's `R12` row and
Total had also gone stale by two rows: `R12-4`'s own closing pass moved
its per-region row to BUILT without updating the table, so it still read
7 BUILT / 2 OPEN (both `R12-4` and `R12-5` uncounted) instead of 8/1
even before this row's own move. Both are corrected here, to 9 BUILT / 0
OPEN. Every region now reads 0 OPEN.

**Closing pass, `R14-11` (2026-09-02).** The owner resolved owner
decision #4 below: split the report into two documents. `R14-11` moves
**DECISION → BUILT** (`app/app/report_markdown_documents.py`,
`docs/PARITY.md` `REPORT-DOCUMENT-SPLIT-001`); `R14-4`, explicitly
blocked on it, is now separately **BUILT** too
(`REPORT-ABOUT-DISCLOSURE-001`). `R14-3` and `R14-9`'s table-vs-prose
point were re-judged now that the blocker is gone, and both stay open —
for narrower, specific reasons recorded in their own rows (a goal
restatement neither document synthesizes yet; a table column,
Importance, that `critical_criteria` carries no value for), not because
splitting the report was itself insufficient. The R14 per-region row
moves 11 BUILT / 7 DECISION → 13 BUILT / 5 DECISION; the Total row moves
57 → 59 BUILT, 19 → 17 DECISION.

**Closing pass, owner-directed wave (2026-09-03).** The owner's
governing directive — where Google published an exact artifact, mirror
it, adjusted only where genuinely necessary — settles owner decisions
#2, #6, and #9 below. This entry covers decision #2 (per-assumption
wording); see the wave's later entries for #6 and #9. `R12-15`/`MO-4`
move together, **DECISION → BUILT**, mirrored at the rendering boundary
only (`app/app/engine_adapter/drain_reviews.py`, `docs/PARITY.md`
`REVIEW-ASSUMPTION-WORDING-001`) — the stored enum stays
`supported`/`uncertain`/`likely_false` since a programmatic reader keys
off it, and the third value renders as "Implausible" rather than the
published "Unknown" since Google's own exemplar never marks a genuinely
contradicted assumption, only an untested one; see `R12-15`'s own
evidence cell for the full reasoning. The R12 per-region row moves 9
BUILT / 3 DECISION → 10 BUILT / 2 DECISION; MO moves 2 BUILT / 3
DECISION → 3 BUILT / 2 DECISION; the Total row moves 59 → 61 BUILT, 17 →
15 DECISION.

This entry covers decision #6 (named contact fields; see the next entry
for #9). `R14-16` moves **DECISION → BUILT** (commit `7df19fa8`, cites
this row by ID): two named fields pinned at the rendering boundary, no
schema change -- the relevance paragraph renders under `Justification:`,
mirroring the published field's one consistent label directly, and the
second, evidence-citing field renders under `Supporting article:`, a
fixed name of this repo's own choosing rather than any one of Google's
freely-varying labels, since this schema's version of that field is
always exactly one grounded citation, never free citation prose. See
`R14-16`'s own evidence cell and `docs/PARITY.md`
`RESEARCH-CONTACTS-FIELDS-001` for the full reasoning. The R14
per-region row moves 13 BUILT / 5 DECISION → 14 BUILT / 4 DECISION; the
Total row moves 61 → 62 BUILT, 15 → 14 DECISION.

This entry covers decision #9, the last of the three. `R9-4` moves
**DECISION → BUILT**: `docs/PARITY.md`'s `TOOLS-CONFIG-001` residual now
records PubMed's primacy as an explicitly labelled local (CLONE) choice
made through the `TOOLS_CONFIG` mechanism, not a disclosed Google
integration -- Google's own sources confirm only ChEMBL and UniProt by
name. Documentation only, as the row asked for; no code change, no tool
disabled. The R9 per-region row moves 2 BUILT / 1 DECISION → 3 BUILT / 0
DECISION -- the first region in this campaign to reach 0 DECISION. The
Total row moves 62 → 63 BUILT, 14 → 13 DECISION. All three
owner-directed decisions (#2, #6, #9) are now closed.

**Closing pass, `R14-3` (2026-09-03).** `R14-3` moves **DECISION →
BUILT** on an actual build, not an accepted divergence:
`app/app/report_goal_synthesis.py` adds the missing LLM call, made once
per run at report-build time, and `report_markdown_documents.py`'s
`_ranking_sections` threads its output into the Top Ranking Hypotheses
document's `**Goal:**` line in place of the raw goal, so the two
documents' goal blocks now genuinely differ (the Research Overview
document keeps the raw goal). See `R14-3`'s own evidence cell for the
model-resolution and graceful-degradation design. Tests:
`app/tests/test_report_goal_restatement.py`,
`e2e/tests/03_create_run.spec.ts`. Owner decision #4 below is now fully
resolved (its `R14-3` residual is gone). The R14 per-region row moves 14
BUILT / 4 DECISION → 15 BUILT / 3 DECISION; the Total row moves 68 → 69
BUILT, 12 → 11 DECISION (picking up from the live-footage wave's count,
recorded locally in the R13 section below rather than narrated here).

**Closing pass, owner-accepted-divergence wave (2026-09-03).** Two more
decisions close, both via an owner call to accept the divergence rather
than build the published shape.

Owner decision #1 below (goal-intake shape and the three glossary terms)
is resolved: keep the single free-text `research_goal` field. The
interview already elicits this kind of structure conversationally and
writes it into the run plan, which fits the product better than a fixed
intake form or a load-bearing enum. `R1-18`, `R10-9`, `R14-2`, `MO-11`
(4 rows, 1 question) all move **DECISION → BUILT**; not double-counted.

Owner decision #7 below (a 14-section per-hypothesis document) is also
resolved: keep the flat per-idea entry. The Top Ranking Hypotheses
document already carries mechanism, steps to test, verdict, simulation
review, and claim evidence per idea (R14-11), so a separate document
would largely restate it. `R14-26` moves **DECISION → BUILT**.

Per-region moves: R1 2 BUILT / 1 DECISION → 3 BUILT / 0 DECISION; R10 7
BUILT / 2 DECISION → 8 BUILT / 1 DECISION; R14 15 BUILT / 3 DECISION →
17 BUILT / 1 DECISION; MO 3 BUILT / 2 DECISION → 4 BUILT / 1 DECISION.
The Total row moves 69 → 74 BUILT, 11 → 6 DECISION -- five rows closed
(`R1-18`, `R10-9`, `R14-2`, `R14-26`, `MO-11`).

**Closing pass, `R8-4`/`R12-13` (2026-09-03).** Two more DECISION rows
close, both **DECISION → BUILT**.

`R8-4`'s residual (owner decision #12 below) is resolved the same way
the owner-directed wave settled #2/#6/#9: the governing directive --
where Google published an exact prompt, mirror it -- now outweighs the
answerless-rate caution an earlier wave recorded, without waiting on a
paid live A/B. Ranking-05's "Subsequent turns:" first bullet, "Pose
clarifying questions to address any ambiguities or uncertainties,"
renders verbatim as the lead sentence of every follow-up debate turn
(`ranking_debate_turns.py::_append_debate_context`), pinned by
`engine/tests/test_ranking_debate.py::test_followup_turns_pose_clarifying_questions`
(reads the instruction out of `docs/CORPUS-EXTRACTION.md` rather than
restating it) and recorded by `docs/PARITY.md`'s new
`RANK-DEBATE-CLARIFY-001` row. Checked that nothing downstream parses
the debate transcript in a way a clarifying question could break: the
judge answers every turn against the same schema, the verdict-line
parser and its position-balanced fallback are unchanged, and the
reasoning field is read as freeform prose everywhere it is consumed.

`R12-13`'s residual (owner decision #11 below) is resolved as an
accepted divergence, the same pattern `R12-14` used: `## Top hypotheses`
stays emitted exactly once (correcting this row's own stale
`report_markdown.py:345` citation to `report_markdown_documents.py:126`,
where the R14-11 document split moved the render) rather than doubled to
match the published capture, since the corpus row itself already flags
the duplication as probably a transcription artifact, not a shape worth
mirroring into what would otherwise read as a rendering bug.
`docs/PARITY.md`'s new `REPORT-HEADING-DUPLICATION-001` row (`partial`)
records this.

Per-region moves: R8 2 BUILT / 1 DECISION → 3 BUILT / 0 DECISION; R12 10
BUILT / 2 DECISION → 11 BUILT / 1 DECISION. The Total row moves 74 → 76
BUILT, 6 → 4 DECISION -- two rows closed (`R8-4`, `R12-13`).

**Closing pass, `REVIEW-SCALE` wave (2026-09-03).** `R10-7` and `MO-5`
move **DECISION → BUILT**. The scale question -- is a review block's bare
`Answer: N` closing on a 1-5 or 1-10 scale -- is resolved from the raw
corpus tree, not the Appendix `docs/CORPUS-EXTRACTION.md` mirrors:
Google states directly that each research goal was "rated on a 1-10
quality score" and reports Reflection-agent auto-eval scores "out of
10", and 57 deduplicated `Answer: N` occurrences across the corpus span
2-9 -- impossible on a 1-5 scale. The earlier pass's "3 or 4, six times
total" reading was accurate of the Appendix alone, which mirrors only a
slice of these blocks; see `R10-7`'s own evidence cell for the full
citation. This also corrects `docs/PARITY.md`'s `EVAL-REVIEW-SCALE-001`,
a `verified` row, from "our 1-10 score is a labelled divergence from the
published scale" to "our 1-10 score matches the published per-dimension
score" -- the published system carries two different review scores at
two different scales (Figure A.23's named "co-scientist review score"
gate, 1-5, cited by `R10-3`; the per-dimension `Answer: N` closings,
1-10), and only the second is what this repo's rubric was ever meant to
be compared against. Per-region moves: R10 8 BUILT / 1 DECISION → 9
BUILT / 0 DECISION; MO 4 BUILT / 1 DECISION → 5 BUILT / 0 DECISION. The
Total row moves 77 → 79 BUILT, 3 → 1 DECISION -- two rows closed
(`R10-7`, `MO-5`); zero owner decisions now remain (see the Decisions
section below). `R14-10` also gained a fuller, self-contained record
this wave without a verdict change -- see its own row.

**Closing pass, `R14-9`/`R12-23` mirror-fidelity wave (2026-09-04).**
`R14-9` keeps its **FALSE** verdict on its central claim (`R12-18` is
not absent), but its own earlier correction is itself corrected in-cell,
the `R6-6`/`R12-14`/`MO-5` style: the surviving table-vs-prose format
point was never blocked on a missing `importance` value -- that prose
already exists, as each `critical_criteria` entry's own `description`
field; "Importance" is the published table's column label for it, not a
second datum to synthesize. With that premise corrected, the format
point itself is now closed by mirroring the corpus's own per-document
split: prose stays on the Research Overview document (MASH's own
analogue, unchanged), and a Criterion/Importance table now renders on
the Top Ranking Hypotheses document (the protein-assemblies ranking
report's own analogue), `docs/PARITY.md` `RANKING-CRITERIA-TABLE-001`.
`R12-23` also closes fully: its bundled `Research directions` half
splits into `Unexpected Research Directions` (BUILT --
`UNEXPECTED-RESEARCH-DIRECTIONS-001`, genuinely new content this repo
did not previously hold) and the five-main-directions restatement
(declined as an accepted divergence, citing `R12-13`'s own precedent
rather than doubling content already rendered in full). Separately,
`R12-17`/`R12-18`/`R12-23` gain the `docs/PARITY.md` rows their own
residual asked for -- `STRATIFICATION-ATTRIBUTES-001`,
`EVALUATION-CRITERIA-001`, `REVIEW-SUMMARY-001` -- all `verified`,
citing the same four app tests the residual named plus the fifth this
pass found (`test_report_review_summary.py`). None of the four rows
above changes verdict, so no BUILT/FALSE/DECISION count moves. **One
new row is added, honestly, not massaged away**: `R14-27` (**OPEN**),
the published ranking report's own `Main Research Directions` prose
section, found while scoping this wave and left unbuilt -- this repo
holds no data shaped as a synthesized cross-direction summary for that
document, only the per-direction array the Research Overview document
already consumes. The R14 per-region row moves 20 rows (17 BUILT / 0
OPEN / 1 DECISION / 2 FALSE) → 21 rows (17 BUILT / 1 OPEN / 1 DECISION /
2 FALSE); the Total row moves 83 → 84 rows, 0 → 1 OPEN, every other
bucket unchanged (79 BUILT / 1 DECISION / 3 FALSE). This is the
campaign's first OPEN row since the `R12-5` pass above drove every
region to 0 -- recorded because it is true, not reconciled away to keep
that streak.

**Closing pass, `R14-27` wave (2026-09-04).** `R14-27` moves **OPEN →
BUILT** -- see its own row for the implementation. The owner's design
call resolved the row's own open question (host the field on
`META_REVIEW_SCHEMA`, not `RESEARCH_OVERVIEW_SCHEMA`) rather than the
row's two originally-sketched options (a new `RESEARCH_OVERVIEW_SCHEMA`
field, or declining as an accepted divergence); the corrected reasoning
is recorded in the row itself, `R6-6`/`R12-14`/`MO-5`-style, not
papered over. This closes the mirror-fidelity campaign's last OPEN row:
the R14 per-region row moves 21 rows (17 BUILT / 1 OPEN / 1 DECISION / 2
FALSE) → 21 rows (18 BUILT / 0 OPEN / 1 DECISION / 2 FALSE); the Total
row moves 79 → 80 BUILT, 1 → 0 OPEN, every other bucket unchanged (84
rows total, 1 DECISION / 3 FALSE). Zero OPEN rows remain.

**Closing audit, published hypothesis documents (2026-09-04).** With
`references/` due for deletion, all 19 published per-hypothesis documents
under `.../ai-guided-discovery-of-atypical-protein-assemblies/
hypotheses/` (byte-identical to their mirror under
`research/extracted-artifacts/outputs/hypotheses/protein-assemblies/`,
confirmed by `cmp`, plus that tree's own `SOURCE-NOTE.md` — not
double-counted) were read as a set, past the five files that R14 rows
already cite by name (`physico-evolutionary-pe-sni-...`,
`development-sni-clt-...`, `development-seven-parameter-sni-...-af3`,
`development-seven-parameter-sni-...-candidates`,
`development-eight-parameter-sni-...-af3-homology`), into the 14 that were
not. **Conclusion: nothing new.** A crude heading-frequency count surfaced
seven section names with no literal-string hit in
`app/app/report_markdown*.py`/`engine/src/co_scientist/schemas/`/
`engine/src/co_scientist/prompts/templates/` — Motivation, Reviews
summary, Related Article Abstracts, Suggested Improvements, Detailed
Assumptions, Strength of Evidence, Assessment of Goal Requirements — but
reading each in context (2-3 of the 19 files apiece) and searching by
meaning rather than name found every one already settled by an existing
row, just under different words: `Reviews summary` is `R14-14` /
`docs/PARITY.md` `REVIEW-SUMMARY-STRUCTURE-001` (deliberately not built —
Google's own 8/19-eight-part/3/19-two-list/8/19-empty split recorded as
the reason not to impose a shape); `Related Article Abstracts`, `Suggested
Improvements`, `Strength of Evidence`, and `Assessment of Goal
Requirements` (published as "Goal Requirement(s) Assessment") are the four
unbuilt parts of `R14-17` / `REVIEW-AXIS-STRUCTURE-001`'s own Correctness
sub-schema list, measured at both a maximal and a minimal token cost and
declined at either — that row's evidence names "Related Article Abstracts"
specifically as unbuildable at any cost ("literally an echo of input the
prompt already supplies, the same trap `proximity_dedup` hit"); `Detailed
Assumptions` is already built at the review level —
`FULL_REVIEW_SCHEMA.assumptions[]` (`engine/src/co_scientist/schemas/
review.py`), rendered by `drain_reviews.py::_assumption_line` (MO-9) —
with only the per-axis duplication (a separate block under Correctness
*and* under Impact potential) covered by the same `R14-17` decline; and
the standalone `Motivation:`/`Coherence:`/`Deep verification:` tail
sections are `R14-22` (BUILT — `Deep verification` renders via
`simulation_review.failure_points`), `R14-23` (recorded: this codebase's
renderers omit an empty section's heading, Google's always print it), and
`R14-24` (corrected population-pattern reading) — their content
(why-this-hypothesis reasoning, missing-piece explanatory power,
counterarguments) substantially overlaps existing fields
(`literature_grounding`, rendered as **Mechanism**; assumptions;
`constructive_feedback`) and the residual is exactly `R14-26`'s
already-declined 14-section document assembly, not new missing content. A
second pass scanned the 14 uncited files' own headings for anything
outside the 15-name canonical set the campaign already measured
(`R14-17`'s prose); everything found was either a numbering variant of an
already-classified section, hypothesis-specific content (parameter names,
contact names, per-contact `Justification:` prose already covered by
`R14-16`), or one single-file garbled `Summary Table of Expertise` (broken
cell-wrapping, the same lossy export signature `R14-25` already named and
rejected as PDF/Docs-to-Markdown noise, not product formatting) — nothing
structurally new. No row added, no count moved: this audit closes the
question rather than reopening it, so a future reader does not need
`references/` to re-verify that these 19 documents were mined.

---

## R1 — SSR consolidation

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R1-12 | Elo-quality concordance should bucket by Elo in 50-point increments and compute accuracy per bucket | **BUILT** | `evaluations/elo_concordance_eval.py::elo_bucket_accuracy` (EVAL-METHODS wave) now implements Google's published method exactly: pools every candidate's final Elo across items, buckets in 50-point increments anchored the same way the paper's own boundaries are (1001-1050, 1051-1100, ...), and reports percent-correct per bucket. Kendall's tau-b stays alongside it, kept as an independent sanity check of the harness's own Elo math rather than a substitute for the published method — a deliberate keep-both decision, not an oversight. `docs/PARITY.md:207` (`EVAL-ELO-CALIB-001`, still `partial`) now correctly names only the remaining gap — licensed GPQA corpus, credentials, and the paper's Gemini-2.0 reference-accuracy baseline — not a method difference. Tests: `evaluations/tests/test_elo_concordance_eval.py` |
| R1-13 | Scaling should partition one run's hypotheses into ten equal temporal buckets, tracking best/top-10-average Elo across them | **BUILT** | `evaluations/scaling_eval.py::temporal_scaling_curve` (EVAL-METHODS wave) implements the published method: partitions ONE run's hypotheses into ten equal buckets, reporting best Elo and top-10-average Elo per bucket, never varying tier. Its ordering key (`_temporal_order_key`) is `generation` — the engine's own lineage ordinal, not raw `created_at` — after a real offline run showed `created_at` alone lands one generation call's whole batch of siblings within under a millisecond of each other (the engine's `Hypothesis` model carries no per-hypothesis timestamp), which is drain-order noise, not a temporal signal; `generation` is real and confirmed to vary in a real run (`test_offline_snapshot_carries_a_real_temporal_curve` asserts ≥2 distinct values). `scaling_budget_driver.py` wires it per arm (`snapshot["temporal_curve"]`), and — unlike the pre-existing cross-tier `scaling_curve()`, which stays harness-only offline (the deterministic backend answers identically at every tier) — this genuinely orders by cycle even offline, though at coarser resolution than the paper's continuous wall-clock partition (an express/standard arm only ever reaches generation 0 and 1). Degenerate cases handled: an empty run, a run with fewer than ten hypotheses (confirmed against a real offline express run, which produces 8), and hypotheses with no Elo yet. `docs/PARITY.md:208` (`EVAL-SCALING-001`, still `partial`) now describes both methods, the generation-vs-created_at distinction, and what each method does and does not tell us. Tests: `evaluations/tests/test_scaling_eval.py`, `evaluations/tests/test_scaling_budget_driver.py` |
| R1-18 | Three glossary terms — "novel repurposing candidate", "novel target", "novel mechanistic explanation" — as a controlled vocabulary | **BUILT** | Owner call: accept the divergence. Not implemented as a controlled vocabulary anywhere in engine or app code, and staying that way -- the goal-intake question this row shares with `R10-9`/`R14-2`/`MO-11` decides it: the interview already elicits this kind of structure conversationally and writes it into the run plan, which fits the product better than a fixed intake form or a load-bearing enum. See `R10-9`/`R14-2`/`MO-11` for the shared reasoning; not double-counted separately |

**R1: 3 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

## R6 — retrieval, grounding, and verification

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R6-5 | FINDINGS `G4`'s evidence line claims bioRxiv, Open Targets, and ClinicalTrials "no longer appear" in config; the row says all three are now registered with real backends | **BUILT** | Both `G4` occurrences are now corrected (`docs/fidelity-audit/FINDINGS.md:172,386`, commits `2299c25e`/`6b3c65d2`): the row's own gap line now states the accurate split inline -- bioRxiv (`preprint_search`), OpenTargets, and ClinicalTrials.gov are registered with real, tested MCP backends; arXiv, Semantic Scholar, Crossref, and Google Scholar remain genuinely absent (arXiv/Google Scholar appear only in illustrative `config/examples/*.yaml`, never a live tool). Both `G4` lines cite this row by name (`corpus R6-5`) |
| R6-6 | Crossref plays two distinct roles in the corpus — literature *search* (deliberately absent, per `G4`) and *retraction lookup* (would close `CITE-META-001`'s residual) — and a future reader must not collapse them | **BUILT** | `docs/PARITY.md:167`'s `CITE-META-001` residual now carries exactly the clarifying line the row asked for (commit `ef7a0bed`, cites `corpus R6-6`): search stays deliberately absent (`G4`), and retraction lookup is *not* absent -- `app/app/citation_resolver.py::resolve_one` already checks a DOI against `app/app/retraction_set.py`'s offline set, itself extracted from the Crossref/Retraction Watch dataset, on every real run (`settings.evidence_resolver == "live"`, the production default). The row's own original OPEN-verdict evidence claimed the opposite -- "no `crossref`/`api.crossref.org` reference in either" file -- and that claim does not survive a read: `retraction_set.py` names Crossref twice in its module docstring ("a paper retracted at Crossref can", "the Crossref/Retraction Watch dataset", lines 5 and 7), capitalized, which a case-sensitive grep for lowercase `crossref` missed. That correction also surfaced a narrower discard the row didn't originally ask about -- the live `RETRACTED` verdict reached `drain_evidence_resolution.py::_resolved_from_requests` and was collapsed into plain `available=False`, indistinguishable from an ordinary dead link. Now fixed in this same wave: `ResolvedArticle.retracted` carries the flag through to a new `evidence.retracted` column (`app/app/store/db_migrations.py`), rendered as a distinct "Retracted" pill (`run_detail_learning_references.tsx`), pinned by `app/tests/test_engine_drain_evidence_identity.py`. `CITE-META-001` stays `partial` regardless -- its remaining residual, that `claims_gate.assess_resolvability`'s swappable `Resolver` seam is itself never invoked outside `app/tests/test_claims.py`, is a distinct, still-open finding this row never asked to close |

**R6: 2 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none — the note previously recorded here (`CITE-META-001`'s "no live resolver is wired" reading as stronger than accurate) is now resolved and folded into R6-6's own verdict above; see also the "Residuals" section at the end of this document.

## R8 — the eight published prompts, re-checked

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R8-2 | The published-prompt→template mapping was recorded but never checked for content preservation; needs "a one-off semantic diff of all eight prompts against their templates" | **BUILT** | `docs/PROMPT-PRESERVATION.md` (dated 2026-09-01) is exactly that diff — all eight prompts, instruction-by-instruction, classified present/missing/adapted with line-cited evidence. Summary: 4 prompts fully preserved, 4 with residual gaps (1–2 missing instructions each). Supersedes this row |
| R8-4 | 14/19 sentences of `ranking-05` poorly covered; two things unsettled: the turn-count envelope (code vs. prompt) and "Pose clarifying questions to address any ambiguities" (0.0 coverage) | **BUILT** | The turn envelope is settled, as the row itself already concludes: enforced in code (`engine/src/co_scientist/agents/ranking/ranking.py:234`, `RANK-DEBATE-DEPTH-001` `verified`), correctly not restated in the prompt. **The clarifying-questions instruction is now built too, closing 2026-09-03.** An earlier wave weighed it against the ranking judge's already-measured ~23% `LLMThinkingOnlyError` rate on this exact prompt family (13/56 calls, live run) and deliberately did not add it -- see the owner-directed wave's decision list, item #12 -- but the owner's governing directive for this campaign (where Google published an exact prompt, mirror it) now settles the question the same way it settled decisions #2/#6/#9: added, without a live A/B first. The bullet renders verbatim, in the published position -- the lead sentence of every follow-up debate turn's guidance (`ranking_debate_turns.py::_append_debate_context`; turn 1 renders no debate context at all, so this is turn-2-onward only, matching ranking-05's own "Subsequent turns" framing). The judge still answers every turn against the unchanged schema (`winner` plus a `decision_summary` ending in the literal verdict line), so nothing downstream that parses the debate transcript is affected -- checked `ranking_debate.py`'s turn loop and `ranking_debate_turns.py::_parse_verdict_line`/`_resolve_turn_winner`/`_finalize_debate_response` directly: the verdict-line parser reads the same field regardless of what else the judge writes into it, malformed output already falls back to the position-balanced tiebreaker, and `ranking_results._extract_reasoning` reads `decision_summary` as freeform prose, never parsed for structure. `docs/PROMPT-PRESERVATION.md`'s own §7 correction footnote is now itself resolved with a follow-up note. Pinned by `engine/tests/test_ranking_debate.py::test_followup_turns_pose_clarifying_questions`, which reads the instruction directly out of `docs/CORPUS-EXTRACTION.md:1244` rather than restating it inline. `docs/PARITY.md`'s new `RANK-DEBATE-CLARIFY-001` row (`verified`) records this; the answerless-rate risk itself stays unmeasured offline (the deterministic offline backend never returns answerless regardless of prompt content), so a live A/B remains the only way to measure any before/after effect, now accepted as a known risk rather than a blocker. **That risk is bounded, checked directly rather than assumed (2026-09-04).** The judge call is `call_llm_json`, not bare `call_llm` (`ranking_debate.py:153-165`, `max_tokens=THINKING_MAX_TOKENS`, thinking on, docstring names this the run's highest-volume call). Its escalation ladder treats an `LLMThinkingOnlyError` specially: it jumps straight to the `NO_THINKING` rung instead of climbing one step at a time (`llm_json_escalation.py:91-95`), and that rung removes the precondition the error requires -- `reasoning_tokens > 0` (`llm_response.py:203-210`) -- so the expected cost per affected turn is exactly one extra call (answerless, then a normal answer with thinking off). The rung is not itself a hard stop, though: at `NO_THINKING` the loop keeps re-sending the thinking-off request up to `call_llm_json`'s own 5-attempt ceiling (`llm.py:365`) before it raises, so the true per-turn worst case is 4 extra calls, not 1. Only follow-up turns (2 through the `_RANKING_DEBATE_MAX_TURNS=10` envelope) carry the instruction, so per matchup that is up to 9 affected turns: 9 extra calls expected, up to 36 before a raise in the theoretical ceiling -- though the debate loop's own docstring says turns typically run 3-5 and stop early on consensus, so this ceiling is rarely approached. No verdict is silently lost either way. This row's own claim -- malformed-but-present output already falls back to the position-balanced tiebreaker -- is code-checked, not just quoted: `_parse_matchup_winner` returns the caller's `fallback` (`_balanced_invalid_fallback`, an identity-stable, matchup-alternating pick) whenever the `winner` field is missing or off-schema (`ranking_debate_turns.py:107-146`). Separately, a call that exhausts its full attempt budget raises uncaught -- neither `ranking_debate.py`'s debate-turn loop (`:234-317`) nor `ranking.py`'s tournament orchestration (`:222-338`) contains a single `except`, confirmed by inspection -- so the failure surfaces loudly as a failed ranking task and is retried at *task* granularity under the repo's own contract (only `UnsupportedTaskError` is a permanent task failure), not silently dropped or defaulted at the matchup level. The bound is on correctness and blast radius, not on frequency: the rate stays unmeasured offline (the deterministic backend never returns answerless), and the cost still lands on the run's O(n^2) highest-volume call, so frequency remains the thing a live A/B would need to settle for latency and spend |
| R8-6 | Published debate judge is framed as a plurality ("simulating a panel of domain experts", "The experts possess no pre-existing biases") — contradicts FINDINGS `E18`'s "the paper names a single evaluator"; needs a correction to `E18` and one framing line in `ranking.md` | **BUILT** | The `E18` half was already done (`docs/fidelity-audit/FINDINGS.md:138`, commit `c310a560`): states the paper frames the judge as a plurality, quotes the panel/bias-neutrality sentence verbatim, cites this row, and correctly preserves what stays true -- the paper never names distinct advocate/opponent *personas* for that panel. `ranking_debate.py::_run_debate_turns`'s docstring was already fixed too. The remaining deliverable now lands, this wave: `engine/src/co_scientist/prompts/templates/ranking.md`'s opening line now reads "You are a Tournament Judge Agent in the Co-Scientist framework, simulating a panel of domain experts engaged in a structured discussion," echoing the published framing. Deliberately not added: an assertion that "the experts possess no pre-existing biases" -- audited and classified adapted-and-stronger in `docs/PROMPT-PRESERVATION.md` §7 item 3, since this judge already enforces impartiality structurally (both A/B presentation orders via `_render_ordered_prompt(swapped=True)`, a position-balanced fallback on malformed output) rather than asserting a claim the model cannot verify about itself. Pinned by two new tests in `engine/tests/test_ranking_prompt.py` (`test_matchup_prompt_frames_the_judge_as_a_panel`, `test_panel_framing_does_not_dislodge_the_decisive_verdict_instruction` -- the latter confirms "Make a clear decision" and the literal `better idea: 1`/`2` verdict format still render unchanged). Token cost measured (`litellm.token_counter`, gpt-4o tokenizer, same method as `R8-4`): the added clause is 13 tokens versus the unchanged opening sentence, and unlike `R8-4`'s subsequent-turn-only guidance, this line sits in the base prompt every turn re-renders (`ranking_debate_turns.py::_render_ordered_prompt`) -- roughly 65 single-turn matchups x 1 render plus ~25 multi-turn matchups x 3.6 turns/match (`docs/PROMPT-PRESERVATION.md` §7) is ~155 renders/run, so ~2,000 tokens/run, negligible against the run's total spend |

**R8: 3 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

## R9 — build methodology and tech-stack findings

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R9-2 | Live open-source-project verdicts (Jataware FORK PRIMARY; LLNL/Sakana v2/FutureHouse Robin/OpenScientist-K-Dense/aimclub MINE; The-Swarm-Corporation INSPECT; mims-harvard REJECT) exist nowhere outside the corpus file; needs an ADR so the decisions survive `references/` deletion, per the `references/peripheral/` precedent | **BUILT** | `docs/decisions/2026-09-02-open-source-coscientist-landscape.md` (PRESERVE wave) records all eight verdicts in a table, cites this row by ID, and confirms directly (not assumed) that none of the eight is vendored or forked anywhere in this tree — Jataware and Sakana appear only in `README.md`'s Acknowledgements as prior-art citations. Two things found along the way, folded into the ADR rather than left for a future reader to rediscover: The-Swarm-Corporation's bare INSPECT verdict was already carried out in depth by `docs/decisions/2026-08-23-chat-interface-reference-drain.md`'s "namesake, head to head" comparison (read in full, this repo ahead on dedup/lineage/durability/safety); and "OpenScientist/K-Dense" (this row's MINE verdict) is not the same product as the tool-skills bundle at `vendor/science-skills/`, whose own attribution is itself inconsistent between `NOTICE` (Google DeepMind) and the 2026-08-23 ADR (K-Dense-AI) — flagged, not resolved |
| R9-3 | `tech-stack-findings.md`'s citation-disciplined uncertainty register (Google never names source languages, frontend/backend framework, storage, queue, or retrieval index) is worth preserving; needs folding into FINDINGS' "Evidence boundaries" table | **BUILT** | Folded into `docs/PARITY.md`'s "Notes on clone-defined vs Google-specified" section instead of FINDINGS' table — a deliberate re-scoping for the PRESERVE wave, not an oversight: this register is about Google's undisclosed *implementation stack*, which is exactly what that section's closing paragraph already discusses (the reference corpus's proposed-and-rejected stack), so the six categories now sit beside it as a corroborating fact rather than a new requirement, cited to this row (commit `f0be5657`). `docs/fidelity-audit/FINDINGS.md:520-548`'s "Evidence boundaries" table was left untouched — it already covers adjacent ground (queue/DB/retrieval-provider disclosure status) at a different granularity, and duplicating the same six categories into a second table was judged to add confusion, not clarity |
| R9-4 | Google's own sources confirm ChEMBL and UniProt as named integrations but not PubMed or arXiv, in tension with this repo where PubMed is the primary retrieval path; the row itself frames this as unsettled by any ledger row | **BUILT** | Recorded, as the row asked for -- no code change, no tool disabled. `docs/PARITY.md`'s `TOOLS-CONFIG-001` residual now states the tension by name (cites this row): PubMed's primacy as this system's retrieval backbone is an explicitly labelled local (CLONE) choice made through the `TOOLS_CONFIG` mechanism, not a disclosed Google integration -- Google's own sources confirm only ChEMBL and UniProt by name, never PubMed or arXiv. So a future reader of that row cannot mistake PubMed's primacy for a disclosed Google integration; it reads as this clone's own retrieval choice, exercised through the same mechanism that carries the two confirmed integrations |

**R9: 3 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

## R10 — `research/papers/`

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R10-1 | A 15-item Specific Aims evaluation rubric (5 significance/innovation + 10 rigor/feasibility axes, 5-point Likert) exists in the paper with no counterpart in this repo's 6-axis `expert_review.py` instrument | **BUILT** | `evaluations/datasets/specific_aims_rubric_v1.json` (commit `eb9291d7`, 2026-09-01) carries the 15 axes verbatim; `evaluations/specific_aims_review.py` (238 lines) adds a separate blinded export/import mode (`SPECIFIC_AIMS_AXES`, `AGREEMENT_SCALE`) kept deliberately unmerged with `RATING_AXES`. `docs/PARITY.md:217` `EVAL-SPECIFIC-AIMS-RUBRIC-001` (`verified`), pinned by `evaluations/tests/test_specific_aims_rubric.py` (148 lines) |
| R10-2 | The rubric is explicitly a non-validated pilot framework; this caveat must ride the same row/artifact as R10-1 | **BUILT** | Carried verbatim as `provenance_caveat` in `specific_aims_rubric_v1.json:8` ("PILOT framework... explicitly not a validated instrument... 'would require considerable further research'") and repeated in `specific_aims_review.py`'s module docstring |
| R10-3 | Figure A.23's expert-review selection gate implies the published co-scientist review score is on a **1–5** scale, not our 1–10 | **BUILT** | `docs/PARITY.md:220` `EVAL-REVIEW-SCALE-001` (`verified`, commit `6e387043`, corrected by the `REVIEW-SCALE` wave) records the named Figure A.23 gate score as 1-5, with no local counterpart, and distinguishes it from a *separate* published per-dimension review score that our 1-10 rubric (`engine/src/co_scientist/schemas/review.py` `REVIEW_SCORE_MINIMUM`/`MAXIMUM`) does match — see `R10-7`/`MO-5` — pinned by `engine/tests/test_review_batch_isolation.py::test_score_fields_are_bounded_to_the_rubric_range`. Recording only, as the row's own residual asked for — no scale change made or implied |
| R10-7 | A bare `Answer: N` closing on a review block; the scale is never stated in the source text, and 3/4 exemplars fit either a 1–5 or 1–10 scale | **BUILT** | **Resolved: the scale is 1-10, stated in Google's own prose — not settleable from the Appendix alone.** `research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md:91` — "each research goal was rated on a 1-10 quality score." `research/papers/accelerating-scientific-discovery-with-co-scientist.md:336` reports the Reflection agent's auto-evaluation scores as "novelty score of 6.14 (out of 10)... 2.38 (out of 10)" and "correctness score from 7.4 to 8.46 (out of 10)." The bare `Answer: N` closings are exactly those per-dimension scores: one published detailed-output file (`.../hypotheses/protein-assemblies/physico-evolutionary-pe-sni-high-throughput-identification-unconventional-nrc-nlrs.md`) carries four dimension blocks under `#### **All reviews:**` (line 181), each closing with a bare `Answer: N` — `#### **Correctness:**` (183) → `Answer: 9` (263); `#### **Novelty:**` (265) → `Answer: 8` (317); `#### **Feasibility:**` (319) → `Answer: 5` (376); `#### **Impact potential:**` (378) → `Answer: 8` (435). Two of those four names — Novelty and Correctness — are exactly the dimensions the "out of 10" sentence above reports averages for; same construct. The observed range independently rules out 1-5: 57 deduplicated `Answer: N` occurrences across the corpus (`grep -rhoE '^ *\*?\*?Answer:? ?[0-9]+'`) span 2-9, and a maximum of 9 is impossible on a 1-5 scale — 54 of them sit in the protein-assemblies hypotheses tree, counted once (`research/supplements/ai-guided-discovery-of-atypical-protein-assemblies/hypotheses/` and `research/extracted-artifacts/outputs/hypotheses/protein-assemblies/` are mirrors of each other — identical filenames, identical histogram: 2×2, 4×4, 11×5, 11×6, 7×7, 13×8, 6×9 — count once, not twice), plus three more: `.../outputs/validated-outputs/kira6-detailed-output-validated.md:220` (`**Answer: 3**`, a Novelty block), `.../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md:814` (`**Answer: 3**`), `research/papers/towards-an-ai-co-scientist.md:1893` (`Answer: 4`, under `#### Novelty review`). The earlier "3 or 4, six times total" reading is true — of `docs/CORPUS-EXTRACTION.md`'s Appendix specifically, which mirrors only a slice of these blocks, which is exactly why the Appendix alone looked consistent with 1-5; the raw corpus tree settles it. Our engine already implements the answer: `engine/src/co_scientist/prompts/templates/review.md:11` ("score 1-10 for each"), `:44` ("**Use the full 1-10 scale:**") with bands `1-2`/`3-4` matching `constants.py:160` `NOT_VIABLE_SCORE=2`/`:163` `NEEDS_REVISION_SCORE=4`; `schemas/review.py` `REVIEW_SCORE_MINIMUM=1`/`REVIEW_SCORE_MAXIMUM=10`. (Observation only, no new row: our rubric names 8 dimensions plus an overall verdict against Google's 4 — a superset, not a mismatch.) `docs/PARITY.md`'s `EVAL-REVIEW-SCALE-001` is corrected by this same pass from a labelled divergence to a match on this per-dimension score — the *named* "co-scientist review score" in Figure A.23's selection gate (`R10-3`) is a separate, still-correctly-1-5 score. Not double-counted against `MO-5`, which narrows the same question |
| R10-8 | The published detailed output ends in a **Critiques** block — "a summary of the negative critiques from the reviews" — a per-idea rollup distinct from the run-level meta-review critique | **BUILT** | Recorded, as the row's own residual asked for -- not built as a feature. `docs/PARITY.md`'s new `REVIEW-CRITIQUES-ROLLUP-001` row (`missing`, commit `85320235`, cites `corpus R10-8`) states the gap by name: a synthesized per-idea negative-critique rollup, distinct from both the existing per-review list (`ideas_detail_pane.tsx`'s `ReviewCritiquesContent`, still every review rendered verbatim) and the run-level meta-review critique. `docs/PARITY-VERIFICATION.md`'s snapshot moved 79->80 rows to carry it |
| R10-9 | Three glossary terms — "Novel repurposing candidate", "Novel target", "Novel mechanistic explanation" (source: A.1 Glossary) | **BUILT** | Same question as `R1-18` (source: SSR §11, same three terms) -- owner call: accept the divergence, since the interview already elicits this kind of structure conversationally into the run plan. See `R1-18` above for the full reasoning. Not double-counted as separate work — one decision closes both rows |
| R10-10 | The 15-axis rubric applied verbatim to two worked exemplars (lapatinib, selinexor) with filled-in Likert ratings; these are the dataset half of R10-1 | **BUILT** | Both exemplars are in `specific_aims_rubric_v1.json` with per-axis ratings (lapatinib 11 Strongly Agree/3 Agree/1 Neutral, selinexor 7/8), plus Givosiran's absent rating block preserved and explained rather than dropped — matching the row's own description exactly. Same evidence as R10-1 |
| R10-11 | The arXiv paper and the Nature SI disagree on at least three facts (Selinexor panel size/experience, OCT4 validation tool list, an inter-rater Spearman's rho statistic present in only one); nothing in `docs/` records the two sources are different documents | **BUILT** | `docs/PARITY-SOURCES.md` (71 lines, new, commit `6e387043`) records all three divergences by name, added to `docs/README.md`'s index, and cited from `docs/PARITY.md`'s Legend (`:76`, `:87`) plus the two rows that previously cited a bare "Nature paper" (`SCALE-TIER-001:129`, `REFLECT-DEEPVERIFY-ORDER-001:228`) |
| R10-12 | The rubric's 5-point scale is an **agreement** scale (not a quality score) and does not share a scale with the 1–5/1–10 review score; this caveat must ride the same row as R10-10 | **BUILT** | `specific_aims_rubric_v1.json` and `specific_aims_review.py` both state this explicitly and by name — `AGREEMENT_SCALE` is a distinct constant from `expert_review.py`'s `RATING_AXES` scale, and the module docstring calls out that it "shares no scale with `RATING_AXES`' 1-5 quality ints, nor with the paper's own 1-5 co-scientist review score... nor with this repo's 1-10 review score" |

**R10: 9 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

## R11 — `research/supplements/`

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R11-1 | All 19 hypotheses in Google's one complete published run carry near-identical titles on a narrow goal — the same symptom this repo treats as a defect (FINDINGS `K2`, the near-duplicate guard gotcha); needs a note on `evaluations/metrics.py::hypothesis_diversity` and/or FINDINGS | **BUILT** | `docs/fidelity-audit/FINDINGS.md:238`'s `K2` now carries the caveat (commit `21481ce1`, cites `corpus R11-1`): all 19 protein-assemblies hypotheses carry near-identical titles on their own narrow goal, so low title diversity alone is not proof of a local defect -- Google's own system produces it too. Explicitly framed as a caveat, not a correction (`K2`'s underlying gate fix stands), and leaves open whether this repo's near-duplicate guard is *stricter* than Google's. Satisfies the row's "and/or FINDINGS" option; `evaluations/metrics.py::hypothesis_diversity`'s own docstring is untouched |
| R11-3 | Published review vocabulary (Correctness/Novelty/Feasibility/Impact potential/Motivation/Coherence/Deep verification labels; an 8-part numbered `Reviews summary`; bolded `Verdict: No-Go`/`Verdict: Proceed with Testing` dispositions) overlaps but does not match ours; "Review schema vocabulary, if wanted" was left as an open decision | **BUILT** | The row explicitly hands off to the closer R14 pass ("a full document-shape read of all 22 files is R14"), which made and recorded exactly this decision, twice: `docs/PARITY.md:230` `REVIEW-SUMMARY-STRUCTURE-001` (from `R14-14`) measured both the 8-part and two-list published forms and deliberately did **not** impose either (Google's own output is inconsistent 8/3/8 across the sample — imposing one shape would be more rigid than the source), and `docs/PARITY.md:231` `REVIEW-AXIS-STRUCTURE-001` (from `R14-17`, commit `37c999a2`) adopted the Correctness→Novelty→Feasibility→Impact-potential **ordering** in `engine/src/co_scientist/schemas/review.py`'s `_SCORE_CRITERIA` without renaming axes, and measured (not assumed) that per-axis sub-schemas cost 41-67% more input / 62-205% more output tokens depending on shape, both flagged against the task's 2x bound. The disposition-vocabulary piece is independently already built: `schemas/review.py:440-458`'s `go_no_go_recommendation` field is rendered as bolded Go/No-Go framing by `app/app/report_markdown_hypothesis.py:219` (`_render_hypothesis_verdict`), functionally matching the published "Verdict: No-Go"/"Verdict: Proceed with Testing" pattern. The decision this row asked for has been made, with numbers, and recorded — not a full vocabulary rename, but a considered choice, not an open question any more |
| R11-4 | The published run's own "Top ranking hypotheses" list names 20 hypothesis IDs but only 19 have files on disk; anyone citing this run as a pool-size ground truth needs a 19-of-20 caveat wherever it is cited | **BUILT** | The one other place in `docs/` that discusses this run's contents, `docs/CORPUS-EXTRACTION.md`'s `R14` section intro (`:633`), already carries the caveat by name ("the missing 20th hypothesis"). No other file in `docs/` (`docs/PARITY.md`, `docs/fidelity-audit/*.md`) mentions "protein-assemblies" or cites this run's pool size at all — checked directly, zero hits — so there is currently no other citation site missing the note |
| R11-8 | Nature SI Note 3 / Supplementary Table 1 publishes fully quantified per-agent ablation numbers for Reflection's search tool, Evolution, and Meta-review, plus Ranking-prompt and Proximity findings named without numbers; `EVAL-ABLATION-001`'s residual says meta-review and debate-strategy have no toggle seam — exactly the arms Google published numbers for | **BUILT** | `evaluations/ablation_driver.py:93-141` (`PUBLISHED_BASELINES`, commit `0c54580e`) carries every number the row names verbatim — Reflection search-tool (novelty 6.14→2.38, correctness 7.4→8.46, GPQA AUC 0.643→0.651, with an explicit "not uniformly directional, do not smooth" note), Evolution (precision 70.9%→75.4%, quality 4.7→5.6), Meta-review (AUC 0.521→0.597 constructed, 0.629→0.634 GPQA) — as read-only reference data, never computed or gated on locally. Ranking-prompt and Proximity are recorded as `PUBLISHED_BASELINES_UNQUANTIFIED` rather than fabricated. `docs/PARITY.md:209` `EVAL-ABLATION-001` residual updated to match; pinned by `evaluations/tests/test_ablation_driver.py` |

**R11: 4 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

## R12 — `research/extracted-artifacts/outputs/`

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R12-1 | Published tiers are Express/Standard/Extended/Ultra, matching ours exactly — contradicts FINDINGS `B1` ("Four tiers replace Google's exactly-two"); needs a PARITY row plus a correction to `B1` | **BUILT** | Both deliverables landed together (commit `0c328e20`, cites `corpus R12-1`): `docs/fidelity-audit/FINDINGS.md:62` (`B1`) now reads `matched` and quotes the corrected tier-count finding in place (leaving the separate "conversational, no settings form" clause unadjudicated, by design); `docs/PARITY.md`'s new `RUN-TIER-001` row (`verified`) cites the same pin test the row already found existing. `B1` also dropped out of the "Closed as deliberate local choices" list, and `B3`'s stale two-tier cross-reference was fixed in the same commit |
| R12-2 | Published focus options are Prefer evidence/Balance/Prefer novelty/Breakthrough, matching ours — contradicts FINDINGS `B2` ("no Google basis"); same asks as R12-1 | **BUILT** | Same commit as R12-1 (`0c328e20`, cites `corpus R12-2`): `docs/fidelity-audit/FINDINGS.md:63` (`B2`) now reads `matched`, name-for-name and default-for-default against the published capture; `docs/PARITY.md`'s new `RUN-FOCUS-001` row (`verified`) cites `test_run_focus_values_are_the_ones_the_product_offers` |
| R12-4 | Published Criteria are three named settings with explicit values (`Idea correctness: Required`, etc.); ours are four free-prose strings, different in shape and content | **BUILT** | Commit `db6f994b`: `app/app/run_modes.py`'s `DEFAULT_CRITERIA` is now exactly those three name/value pairs. `clean_criteria_list`/`criteria_display_strings` (same file) accept and render both the legacy free-string shape and the new pair shape, so a run persisted before this change keeps rendering under "Research Goal Details" and keeps reaching the engine's `criteria` prompt text unchanged, while a new run's pairs render as one `"Name: Value"` line each. `docs/PARITY.md`'s new `RUN-CRITERIA-001` row (`verified`) cites `app/tests/test_published_plan_config_criteria.py::test_default_criteria_mirrors_the_published_plan_config`, which reads the three pairs directly out of this document's own `## Criteria` block (line 1949) rather than restating them. Scope: only the *default* moved to the pair shape — the three curated demo scenarios (`app/app/seed_planning.py`) and a direct API/CLI caller may still supply their own free-prose criteria, since the published pairs are goal-agnostic (unlike Attributes, `R12-5`, unaffected) and forcing per-goal prose into two fixed fields would lose content rather than mirror the plan |
| R12-5 | Published Attributes are a structured 1-5 scoring rubric (4 anchored scales + 1 categorical); ours is `list[str]` free text | **BUILT** | `app/app/run_modes_attributes.py` (new module, split from `run_modes.py` mirroring `run_modes_criteria.py`, R12-4's own pattern): `DEFAULT_ATTRIBUTES` is now three scaled 1-5 axes ("Mechanistic specificity", "Evidence grounding", "Experimental readiness"), each with anchor text at points 1, 3, and 5. The published block's one categorical axis (Target Area) is itself goal-*derived* — its three values are literally that run's own focus-area list — so no goal-agnostic categorical default exists to mirror; the shape is fully supported regardless (`clean_attributes_list`/`attribute_display_strings` accept and render both a scaled `{"name", "scale"}` axis and a categorical `{"name", "values"}` axis, plus the legacy free-prose string, so a run persisted before this change keeps rendering exactly as it always did). `docs/PARITY.md`'s new `RUN-ATTRIBUTES-001` row (`verified`) cites `app/tests/test_published_plan_config_attributes.py::test_our_attribute_shape_represents_every_published_item`, which parses the published block's own structure (4 scaled + 1 categorical, including Human Relevance's midpoint-omitting anchors) directly out of this document rather than restating it, and proves our shape can encode every published item intact. (Distinct from `config_synthesis.attributes`, the Supervisor-synthesized field R12-17 covers — this row is about the run's own *setup* attributes; the two stay separate rather than unified, since merging them would mean touching three already-BUILT surfaces — the Supervisor schema, `prompts/review.py`, and the R12-17 renderer — for a field already doing its job) |
| R12-12 | The published report's flat 3,259-entry `References` list has no analogue; whether ours (`Citation audit` + data sources, a different artifact) should also get a flat list is explicitly left to the owner | **BUILT** | Owner decided: add one. `app/app/report_markdown_bibliography.py` (new module) renders a `## References` section, wired onto the Research Overview document only — MASH's own span sits in `research-overviews/`, directly after the Open Questions/Clear Patterns/Unexpected Connections span this repo already sinks to `report_markdown_overview.py` (`R12-10`); the ranking document keeps its distinct per-hypothesis `#### References` subsections (`R14-21`) rather than gaining a second, colliding heading. Source of truth is `store.list_evidence`, the same rows `report_build.py` already gathers for both documents and the Learning tab's own reference list — no parallel store read. Deduplicates on a stable identity (DOI, then PMID, then URL, then a normalized title), first-persisted row winning a collision; `drain_hypotheses.py::_persist_engine_evidence` — the sole real-run evidence-insertion path — loops retrieved articles straight into `store.add_evidence` with no identity lookup against already-persisted rows, so a source found by two searches lands as two rows today and render-time dedup is what closes that gap for display. Each entry shows title, author/year and DOI/PMID when persisted, a `(retracted)` flag matching the Learning tab's own pill, and a link when a URL exists — never an invented venue/identifier the store doesn't hold. Ordered alphabetically by the entry's own rendered label (not retrieval order), so the list reads identically across re-renders of the same run. Fixed a pre-existing bug in the shared `_reference_label` helper along the way (a curated `"Kim et al."` authors value resolved its surname as the literal `"al."`); the three curated demos now wire each source's real PubMed id through from its own URL (`seed_evidence.py::_pmid_from_url`), and `DEMO_SEED_VERSION` moved 10→11 so production re-seeds with the section populated (6 real entries per demo). A report saved before this change is stored, frozen `reports.markdown_text` that nothing re-renders — only a report built after this change carries the section. `docs/PARITY.md`'s new `BIBLIOGRAPHY-001` row (`verified`) cites `app/tests/test_report_markdown_bibliography.py`, `app/tests/test_report_markdown_references.py`, and `app/tests/test_seed.py::test_seed_demo_runs_creates_three_runs_with_reports` |
| R12-13 | The published report's "Top ideas" heading appears twice (open and close); may be a transcription artifact | **BUILT** | Recorded as an accepted divergence, closing 2026-09-03 -- same pattern as `R12-14`'s "needs a ledger row recording the divergence, not a change." `## Top hypotheses` is still emitted exactly once (`app/app/report_markdown_documents.py:126`, corrected from this row's own earlier, now-stale citation to `report_markdown.py:345` -- that render moved when the R14-11 document split landed). Not built as duplication: doing so would read as a rendering bug in this product, and the row's own framing already treats the published duplication as probably a transcription artifact of the capture, not a shape to mirror. `docs/PARITY.md`'s new `REPORT-HEADING-DUPLICATION-001` row (`partial`) records this |
| R12-14 | Published score composition is printed as `score = novelty + details + usefulness + pairwise rank = 11`; ours is a mean of the review rubric's axes — needs a ledger row recording the divergence, not a change | **BUILT** | `docs/PARITY.md`'s new `SCORE-COMPOSITION-001` row (`partial`, commit `1928f03f`, cites `corpus R12-14`) records exactly this, recording only as the row asked. One correction along the way: `docs/CORPUS-EXTRACTION.md`'s own checklist row cites the formula as sourced from `kira6-detailed-output-validated.md`, "corroborated by" the drug-repurposing supplement -- but `kira6` carries only bare per-axis `Answer: N` closings (see `R10-7`/`MO-5`), zero occurrences of this formula. The formula actually appears in `hypotheses/liver-fibrosis-epigenetic-targets.md`'s two worked Generation-agent examples, which is what the new PARITY row cites instead |
| R12-15 | Published per-assumption wording is prose (`Plausible:`, `Plausible, but requires careful investigation:`, `Unknown:`); ours is the closed enum now unified as `supported`/`uncertain`/`likely_false` (`engine/src/co_scientist/schemas/review.py:20-25`, `ASSUMPTION_SUPPORT_VALUES`) — adopting the published wording is left to the owner | **BUILT** | Same fix as `MO-4` (audited below); not double-counted. Mirrored at the rendering boundary rather than the stored value (commit `980dda41`, cites this row by ID): `app/app/engine_adapter/drain_reviews.py::_assumption_line` now maps the value through `_ASSUMPTION_SUPPORT_LABELS` to Google's wording (`docs/CORPUS-EXTRACTION.md:4135-4141`) before it reaches a reader, while `review.py`'s `ASSUMPTION_SUPPORT_VALUES` stays exactly `supported`/`uncertain`/`likely_false` -- `mature_reviews._project_full_review`'s `assumptions_likely_false` filter keys off that literal string, so migrating stored data would break a programmatic reader for no reader-facing gain. Two of three values mirror the published word directly (`supported` to "Plausible", `uncertain` to "Plausible, but requires careful investigation") but the third deliberately does not: `likely_false` means the evidence points against the assumption, a genuine negative verdict Google's own exemplar never marks -- every published "Unknown:" there marks an assumption nothing has tested yet, not one contradicted -- so it renders as "Implausible" instead of a borrowed, understating "Unknown". `docs/PARITY.md`'s new `REVIEW-ASSUMPTION-WORDING-001` row (`verified`) records this two-of-three match and that the label is baked into the persisted `critique` text at drain time, so a run drained before this change keeps its old wording. Deep verification's `sub_assumptions[].status` carries the same enum but is never rendered to a reader anywhere in this codebase, so this fix does not reach it. Tests: `app/tests/test_review_assumption_wording.py` |
| R12-16 | The one research-contacts exemplar carries exactly two fields (name, free-text relevance paragraph); whether ours invents extra fields needs the same check `test_specific_aims_schema_adds_nothing_the_exemplars_lack` applies elsewhere | **BUILT** | `docs/PARITY.md`'s new `RESEARCH-CONTACTS-FIELDS-001` row (`partial`, commit `537041c7`, cites `corpus R12-16`) records this, and corrects the row's own premise along the way: a direct read of the exemplar (Figure A.22) shows **three** observable fields, not two -- it also carries a Research Direction heading, which this repo's schema already matches deliberately (`MO-7`). Of the schema's five fields, three map onto the exemplar (`name`, `justification`, `research_direction`); `candidate_id` is unrendered anti-hallucination provenance never shown to the reader; `expertise` is the one genuinely unattested addition. Recording only -- the pin test this row's own residual named as the next step (`test_published_artifact_shapes.py`-style) does not yet exist for this schema |
| R12-17 | The published run's Attributes are named 1-5 rating scales with worked anchors, not plain labels; the row found this "half-built and the built half invisible" — the Supervisor already synthesizes `config_synthesis.attributes` and injects it into review prompts, but nothing renders it | **BUILT** | `app/app/report_markdown_supervisor.py` (243 lines) — its own docstring names this row by ID and closes it: `_render_stratification_attributes_markdown` (`:48-76`) renders "## Stratification Attributes" from `config_synthesis.attributes`, deliberately titled to avoid conflating it with the run's plain-string setup attributes. Wired into `report_markdown.py:448` via `report_build.py:214` (`attributes=req.attributes`); pinned by `app/tests/test_report_stratification_attributes.py` and `app/tests/test_drain_stratification_attributes.py`. Only the row's second half ("decide whether reviewers score against them") stays open, and that decision is already effectively made — `prompts/review.py` already injects them into every reviewer prompt as "Stratification attributes (score each 1-5)", per the same docstring |
| R12-18 | The Supervisor synthesizes goal-specific evaluation criteria (`workflow_plan.review_phase.critical_criteria`) but nothing renders them — "we synthesize the second kind and then hide it" | **BUILT** | Same module, same docstring, names `R12-18` explicitly: `_render_evaluation_criteria_markdown` (`report_markdown_supervisor.py:127-169`) renders "## Evaluation Criteria" from `critical_criteria`, wired into `report_markdown.py:469` via `report_build.py:215`. Pinned by `app/tests/test_report_critical_criteria.py` and `app/tests/test_drain_critical_criteria.py`. The row's separate observation that the *interview* path never populates the plain-string `setup.criteria` field is unaffected — that is a distinct, still-true fact about a different field, not part of what this row asked to fix |
| R12-19 | An inline citation marker in body prose can carry its own verdict tag (e.g. `[17 (unsupported)]`); claims our nearest analogue is a separate bulleted block, and that `report_markdown.py` "never renders `literature_grounding` at all... so those keys are generated, paid for, and discarded" | **FALSE** | The discarding claim does not survive a read. `app/app/engine_adapter/drain_hypotheses.py:407` sets `mechanism=h.get("literature_grounding") or ""` — the app's `mechanism` field literally **is** `literature_grounding`'s content, `[C1]` markers included, rendered verbatim by `report_markdown_hypothesis.py:97-105` (`_render_hypothesis_mechanism`) under "**Mechanism:**". Those keys are then resolved to a References list by `app/app/report_markdown_references.py` (119 lines, its own module, wired at `report_markdown.py:343` via `references_by_hypothesis`), with its own test file `app/tests/test_report_markdown_references.py`. The row's grep evidently checked `report_markdown.py`'s own render function for a field literally named `literature_grounding` and found only `mechanism`/`expected_effect` — missing that `mechanism` *is* that field under its drain-layer name, and missing the sibling module entirely. What survives: our citation markers appear inline (not absent, as the row implies) but genuinely carry no verdict tag (`(unsupported)`-style) — `_render_claim_evidence` (`report_markdown_hypothesis.py:63-77`) still renders claim verdicts as a **separate** bulleted block after the prose, exactly as the row correctly describes for that narrower point. So: the "discarded" claim is false; the "no inline verdict tag" claim is true |
| R12-23 | Published `Review summary` restates the run's criteria as 16 yes/no reviewer questions grouped under 5 criteria — the reader-facing form of R12-18, and absent | **BUILT** | Same module again, names `R12-23` explicitly: `_render_review_summary_markdown` (`report_markdown_supervisor.py:212-243`) renders "## Review Summary" — each criterion with its named reviewer questions — wired into `report_markdown_documents.py:256` (corrected from this row's own earlier, now-stale citation to `report_markdown.py:469` -- that render moved when the R14-11 document split landed), shares `critical_criteria` with R12-18, same tests. **Closing pass (2026-09-04):** the row's other half is now fully resolved, split into its two genuinely different asks rather than left bundled. `Unexpected Research Directions` — genuinely novel content this repo did not previously hold — is now BUILT: `unexpected_research_directions` on `RESEARCH_OVERVIEW_SCHEMA` (`engine/src/co_scientist/schemas/synthesis.py`), rendered as "### Unexpected research directions" on the Research Overview document (`report_markdown_overview.py::_render_unexpected_directions_section`); see `docs/PARITY.md` `UNEXPECTED-RESEARCH-DIRECTIONS-001`. A second exemplar independently confirms this: the protein-assemblies run's own two-document split carries the equivalent section as `# **7. Unexpected Areas for Research**` on its `research-overview.md` (`references/core/google-co-scientist/research/extracted-artifacts/outputs/research-overviews/protein-assemblies/research-overview.md:120`, e.g. `- **Non-Pore-Forming "Decoy" NRCs:**...`, `- **Asymmetric Resistosomes:**...`) -- not on that run's `top-ranking-hypotheses.md`, confirming our placement choice (Research Overview document, not the ranking document) from a run that, like ours, produces two separate documents. Vocabulary diverges between the two exemplars -- MASH says "Unexpected Research **Directions**" (`mash-liver-fibrosis-reversal-therapeutic-hypothesis.md:418`), protein-assemblies says "Unexpected **Areas for** Research" -- recorded here per the same vocabulary-divergence convention `MO-12` documents in `engine/src/co_scientist/schemas/synthesis.py`, rather than papered over; we keep the field/heading we already ship (`unexpected_research_directions` / "Unexpected research directions"). The restatement of the five main directions is a deliberate accepted divergence, not built: that content already renders once, in full, under "## Research Overview" (`_render_directions_list`) with title/importance/sub_topics/recent_findings/suggested_experiments — a second render of the same content in the same document would read as a rendering bug in this product. This is the exact precedent `R12-13` already sets (the published report's own duplicate "Top hypotheses" heading recorded as a divergence rather than mirrored) |

**R12: 12 BUILT / 0 OPEN / 0 DECISION / 1 FALSE.**

Noticed in passing: none beyond `R12-23`'s partial resolution (noted inline above — its `Research directions` half stays open, folded into the row's own verdict rather than split into a new row).

## R13 — `media/`

Includes `R13-12`'s part (a) — the naive table-column split misreads this row
because its own text contains a literal `|` inside a quoted video title; part
(b) is `external` and out of scope.

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R13-1 | The two live-footage mp4s are gitignored, uncommitted, and unrecoverable once `references/` is deleted; needs an owner decision — archive outside the repo, or extract and commit the cited frames | **BUILT** | **Closed 2026-09-03.** Both mp4s were watched in full (180 sampled frames, in order) before deletion. 15 curated frames plus a provenance README are committed at `docs/assets/live-footage/` (commit `a2cf38eb`); `docs/CORPUS-EXTRACTION.md`'s `R13-1` row records the extraction. The raw mp4s remain unrecoverable once `references/` is deleted, but nothing depends on the raw files any more — the cited evidence survives independently |
| R13-2 | The 2026-06-21 ADR and the plan-config file read two different tier selectors (three options vs. four) from the same footage folder; needs a note on every row resting on either capture, naming which one | **BUILT** | The note this row asked for already existed (`docs/CORPUS-EXTRACTION.md`'s "Carry this caveat" paragraph). **Strengthened 2026-09-03**: a full frame-by-frame watch of both live-footage clips found the ADR's three-option reading nowhere on screen — every visible instance of the plan card's `Tier` section, in either video, shows exactly Express/Standard/Extended/Ultra (`docs/assets/live-footage/plan-card-focus-tier-start-t31.3s.jpg`, `plan-readonly-tier-extended-t54.0s.jpg`). The plan-config transcription is confirmed correct; the ADR's reading does not match the footage currently on disk (the ADR body itself is left uncorrected this wave — owner call) |
| R13-3 | `docs/UI-FIDELITY.md` cites an unrecoverable mp4 frame as evidence for the four-tab mapping; needs re-pointing at the tracked JPG that shows the same tab bar | **BUILT** | **Re-pointed 2026-09-03, at a better target than the row proposed.** The row's own suggested fix (point at the tracked ESN JPG) turned out to be the wrong fix — that JPG shows the *older* era's own, differently-labelled tab bar (`Ideas · Knowledge Base · Summary · Run Specification`, green underline), not the newer era's tabs this citation is actually about. Instead, the cited frame itself is no longer unrecoverable: extracted at exactly t=66.0s and committed as `docs/assets/live-footage/plan-report-four-tabs-t66.0s.jpg`, confirming `docs/UI-FIDELITY.md`'s claim exactly. `docs/UI-FIDELITY.md:36-52`,`:109-123` (commit `70b9f14b`) now cite that committed frame directly; the ESN JPG stays cited, correctly scoped, only for the older era's own tab bar |
| R13-13 | Native-resolution re-extraction of the composer's connectors menu finds the eighth connector reads "Geat", not "Gmail" as `docs/UI-FIDELITY.md`'s `D4` row had it — a genuine misreading of this exact footage | **BUILT** | Corrected in `docs/UI-FIDELITY.md`'s `D4` row (commit `70b9f14b`), citing `docs/assets/live-footage/setup-connectors-menu-native-crop-t17.5s.jpg`. "Geat" does not match any known Google Workspace product; its referent is unresolved and stated as such rather than guessed |
| R13-14 | The plan card's selected `Tier` radio differs between two timestamps in the same clip — Standard at 31.3s, Extended at 54.0s (after "Start research" is clicked and the conversation goes read-only) — and neither the session-started message nor the report page states which tier the run actually executed under | **BUILT** | No code or doc in the tree makes a claim this would contradict, so there was nothing to correct — recorded as a corpus-integrity note (`docs/CORPUS-EXTRACTION.md` `R13-14`) so a future reader does not treat either frame's "**Selected**" as proof of which tier a demo run executed under |
| R13-15 | The rendered Goal Details report page restates `Criteria` as one condensed prose sentence, a different shape from the plan card's `name: value` bullets that `run_modes_criteria.py` mirrors | **BUILT** | `app/app/run_modes_criteria.py`'s `DEFAULT_CRITERIA` and its display renderer mirror only the bulleted plan-card shape (`R12-4`); no renderer in the tree produces the condensed-prose report-page shape. Low severity — recorded (`docs/CORPUS-EXTRACTION.md` `R13-15`) rather than built, since the information is identical and only the presentation differs |
| R13-16 | The composer's connectors menu shows four separate, default-on scientific-source toggles (Google Search/PubMed/ArXiv/BioRxiv); `app/app/engine_adapter/tools.py`'s `_KNOWN_CONNECTORS` lists only `web_search`/`pubmed`/`indra` — no per-source ArXiv/BioRxiv toggle even though the engine calls both | **BUILT** | **Built 2026-09-03** (supersedes the fold-into-D4 evidence this row previously recorded, which tracked the gap rather than closing it): two new reference-server tools now exist — `search_arxiv` (arxiv.org's own export API, keyless, a real subject search) and `search_biorxiv` (Europe PMC restricted to `PUBLISHER:"bioRxiv"`, verified live that the filter is real — an unrecognized publisher value returns zero hits — since bioRxiv's own REST API lists by posting date only and cannot be queried by subject at all). Both are registered on the MCP server (`engine/mcp_server/server.py`), wired into `config/tools.yaml` as `arxiv_search`/`biorxiv_search` literature-review search sources and validation tools (search-path parameter vocabulary, `results_path: "records"`), and exposed as `arxiv`/`biorxiv` connectors in `_KNOWN_CONNECTORS`, gated on both MCP reachability and tools-config membership so an unreachable server does not advertise them as available. Coverage: `engine/mcp_server/tests/test_arxiv_search.py`, the `search_biorxiv` additions to `test_europepmc_search.py`, `engine/tests/test_tool_param_contract.py` (parameter-mapping correctness for both new sources), `engine/tests/test_arxiv_biorxiv_search_sources.py` (a real response envelope through both the literature-review and validation paths), and `app/tests/test_engine_adapter_tools.py` (connector availability, including MCP-down and not-configured cases). `docs/UI-FIDELITY.md`'s `D4` row is updated to match — Question Q2 partially resolved, master toggle and non-scientific connectors still open |
| R13-6 | 18 of 41 files in the Google Labs page capture are inert tooling with nothing to extract; the HTML itself carries product copy (R13-7) that must be pulled out before pruning to the HTML, 2 PNGs and 3 SVGs | **BUILT** | The row's ask was extract-then-prune; extraction is now done (see `R13-7`), and the prune step itself is deliberately not carried out here — the PRESERVE wave's own hard constraint forbids touching `references/` at all, so the actual file deletion stays the owner's action at `references/` deletion time, by design, not a gap. What was missing and is now recorded is the inventory itself, self-contained so a future reader does not need `references/` to trust it: of the capture's 41 `_files/`, 18 are inert tooling carrying nothing extractable — Google Tag Manager (×2), the YouTube player runtime (×2), a widget-API script plus an iframe loader, Lottie, a cookie-consent bar (×2), Fonts CSS (×2), a closure-library bootstrap, site CSS/JS (×2), and `www-player.css` (×2) — leaving the HTML, 2 PNGs, and 3 SVGs as the only files worth keeping. Source: `docs/CORPUS-EXTRACTION.md:389` (this row, verbatim) |
| R13-7 | Google's own Labs page copy for "Hypothesis Generation — Built with Co-Scientist" (tagline, four capability cards, "Express interest" waitlist framing) is nowhere quoted in `docs/`; needs a short quoted block in `docs/FIDELITY.md`, cited to this file | **BUILT** | `docs/FIDELITY.md`'s new "Google's own framing of this product" section (PRESERVE wave, commit `33379a06`) quotes the `og:title`, the "Express interest" waitlist framing (explicitly noted as a waitlist, not self-serve), the Hypothesis Generation tagline, and all four capability cards verbatim, cited to `docs/CORPUS-EXTRACTION.md:390`. Two existing claims in the same file that paralleled this framing without citing it now point at the new block instead — the "UI exposes hypotheses..." invariant row (also fixing a dangling "see the note below on retired tabs" pointer that resolved to nothing) and the Literature Insights/Computational Discovery out-of-scope note — and `docs/EXPLAINER.md`'s opening paragraph gets one pointer sentence rather than a duplicate quote. Nothing needed correcting on the self-serve point: neither file claimed or implied Google's product is self-serve before this pass |
| R13-10 | The tracked run-in-progress capture shows a **Time remaining** estimate tile alongside the Activity Log; whether this product estimates remaining time at all needs checking against the run view | **BUILT** | Recorded, as the row's own residual asked for -- not built as a feature. `docs/PARITY.md`'s new `RUN-VIEW-ETA-001` row (`missing`, this wave, cites `corpus R13-10`) states the answer by name: the Activity Log half is already built and shipped (`app/frontend/src/workbench/pages/run_detail_activity_log.tsx`, `ActivityLog` component, covered by `run_detail.test.tsx`); the Time-remaining/ETA half does not exist anywhere in `app/frontend/src/workbench/` or `app/app/*.py` -- zero hits. Estimating remaining run time is deliberately not built here; it is a product feature with its own accuracy problems and is left to the owner |
| R13-12 (a) | A tracked JPG's filename (`esn-poma-hub-hypothesis-full-detail-with-diagram.jpg`) does not match its content (a Computational Discovery splash screen); any future row citing the filename would cite the wrong image | **BUILT** | Not renamed or moved (it lives under `references/`, which this pass does not touch) -- flagged instead. `docs/fidelity-audit/FINDINGS.md`'s "Corpus-integrity corrections" section now carries a dedicated note (this wave, cites `corpus R13-12(a)`) naming the filename, stating what it actually shows, and warning against citing it for a hypothesis-detail-view claim -- placed there rather than in the section's own "Claimed as Google / Reality" table, since a mislabeled asset is a different failure than a clone-authored document mis-describing a requirement |

**R13: 11 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

**Closing pass, live-footage wave (2026-09-03).** Both live-footage mp4s
were watched in full before deletion. `R13-1` closes DECISION → BUILT (the
frames are committed); `R13-2`/`R13-3` stay BUILT with their evidence
strengthened by direct verification; four new rows (`R13-13`–`R13-16`)
record what watching the footage actually found — a transcription error in
an existing doc row, a tier-selection discrepancy across two timestamps,
a second Criteria rendering shape, and the connectors-menu ArXiv/BioRxiv
gap — all BUILT, since each landed as the record-only or correction ask
it raised.

Noticed in passing: `docs/CORPUS-EXTRACTION.md` row `R13-16`'s own text
claims "the engine already calls ArXiv and bioRxiv search tools
internally" — that does not survive a read. Before this wave,
`engine/mcp_server/` had `search_pubmed`, `europepmc_search`, and
`search_web` only; `europepmc_search`'s `search_preprints` sibling
indexes bioRxiv/medRxiv preprints through Europe PMC's corpus, which is
adjacent to but not the same claim, and there was no arXiv path of any
kind. Not corrected in that file (out of scope per this document's own
"What this document is not" note above); recorded here so the claim is
not read as still true.

## R14 — the protein-assemblies run, read in full

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R14-1 | The published report opens with an explicit `#### Table of contents:` section, six nav items; our report has no navigation aid | **BUILT** | `app/app/report_markdown_toc.py` (new module) renders "#### Table of contents:" naming the report's own top-level sections; wired into `report_markdown.py:483` right after the title/provenance line, cited by name in its own docstring and in `report_markdown_header.py:11,83` |
| R14-2 | A third, structurally distinct goal-intake shape (8 parts, `Ground Truth Dataset`/`Your Role` fields neither other exemplar has); needs a decision on which shape, if any, is canonical before `MO-11`'s sink is actionable | **BUILT** | Owner call: accept the divergence -- no shape is canonical; `app/app/runs_models.py:29` `research_goal: str` stays one free-text field. Same underlying question as `MO-11`/`R1-18`/`R10-9`; see `R1-18` for the full reasoning (the interview elicits structure conversationally into the run plan). Not double-counted separately |
| R14-3 | The same run's goal renders two different ways across its two report surfaces (raw-flattened vs. synthesized restatement); explicitly blocked on `R14-11` | **BUILT** | The owner's call: synthesize the second restatement. `app/app/report_goal_synthesis.py`'s `synthesize_goal_restatement` makes a new LLM call, once per run at report-build time (not per hypothesis), that produces a narrative restatement of the goal in different words; `report_markdown_documents.py`'s `_ranking_sections` (only) threads it into `_render_research_goal_details` (`report_markdown_header.py`) in place of the raw goal on the Top Ranking Hypotheses document's `**Goal:**` line, while the Research Overview document keeps rendering the raw goal unchanged -- the two documents' goal blocks now genuinely differ. Model resolution follows the run's own persisted offline/real backend (`store.run_offline_backed`, the same signal `engine_adapter/opts.py::_resolve_generator_models` reads), routing an offline-backed run (every curated demo, always) through the engine's deterministic offline router rather than a real provider; a real-backed run is additionally gated on `config.has_provider_credential` before ever calling, which is what keeps the hermetic app test suite from attempting a network call regardless of a bare test-created run row's backend flag. Any failure, timeout, or degenerate/empty answer falls back to the raw goal -- the same duplication this replaces -- so a cosmetic restatement failing never fails the report. Tests: `app/tests/test_report_goal_restatement.py` (unit, incl. the offline backend producing real distinct output with no mocking); `e2e/tests/03_create_run.spec.ts`'s `assertRankingGoalRestatementDiffersFromOverview` (a real offline run, fetching both frozen `.md` documents directly) |
| R14-4 | A second, longer "About" disclaimer exists on the research-overview report surface, textually distinct from the per-hypothesis one and from the provenance line; unclear whether this is a second required disclaimer or a variant of the same one | **BUILT** | `report_markdown_header.py`'s `_render_about_disclosure` renders it verbatim on the Research Overview document, right after the title/provider line and before the table of contents; byte-identical to the per-hypothesis instance (`R14-13`) by construction — `_ABOUT_DISCLOSURE` is now the one constant, re-exported into `report_markdown_hypothesis.py` as `_HYPOTHESIS_DISCLAIMER` so the two can never drift apart. Confirmed a variant of the same wording, not a second, differently-worded disclaimer; not added to the ranking document, since nothing in the corpus attests a copy there. Pinned by `app/tests/test_report_about_disclosure.py` |
| R14-6 | Published research contacts are grouped by research direction (4 groups), each with a shared rationale paragraph and up to two example hypothesis titles; `MO-7` only restored the flat per-contact tag | **BUILT** | `engine/src/co_scientist/schemas/synthesis.py:216-254` `research_contact_groups[]` (named by this row ID in its own code comment) carries `research_direction`, `rationale`, and `example_hypothesis_indices` (by 1-based position, never by echoing text — the AGENTS.md envelope-shape lesson applied on purpose); rendered via `_render_research_contacts_section` (`report_markdown_overview.py:311`); pinned by `app/tests/test_report_contact_groups.py` |
| R14-8 | "Best Next Steps" richer shape: time estimates, lettered sub-phases, a named winning-idea recommendation — beyond `R12-11`'s base finding | **BUILT** | `app/app/report_markdown_meta_review.py:30-88` (`_RecommendationFields`, `_normalize_recommendation`, `_render_recommendation`) adds `time_estimate`, `phase_label`, `recommended_idea` (by `hypothesis_index`, not text), each explicitly commented `# R14-8`; commit `a0c4a5ec` ("render the strategic roadmap's time estimate, phase, and idea (R14-8)") |
| R14-9 | The synthesized-criteria section has a table rendering (Criterion/Importance, 5 rows) distinct from MASH's prose paragraphs; decided-by claims "`R12-18` re-confirmed still fully absent" | **FALSE** | The central claim does not survive a read: `R12-18` is now **BUILT** (see the R12 section above) — `report_markdown_supervisor.py`'s `_render_evaluation_criteria_markdown` renders `critical_criteria` as bolded-name-plus-prose, tested by `app/tests/test_report_critical_criteria.py`. What the row's grep found (`runs_crud_resolve.py:83` never sets the interview-derived `setup.criteria` field) is true but is a different fact from "R12-18 is absent" — that row is about the Supervisor's *separately synthesized* `critical_criteria`, which does render. What survives as a genuine, narrower point: our rendering is prose (matching MASH), not the table format this row found in a second exemplar — that specific format choice remains unaddressed. **Re-checked now that `R14-11`'s split has landed**: this renders on the Research Overview document (`_overview_sections`, "Review guidelines"), and prose still matches that document's own analogue (MASH's single combined report). **Correction to this pass's own earlier reasoning:** the table format was never blocked on a missing `importance` value — `critical_criteria` already carries exactly that prose, as each entry's own `description` field (`engine/src/co_scientist/schemas/planning.py:127+`), the same field `_render_evaluation_criteria_markdown` already renders as prose. "Importance" is the published table's column *label* for that existing datum, not a second value the Supervisor would have to synthesize; inventing one was never the blocker this format needed cleared. **Closing pass (2026-09-04):** the surviving format point is now closed by mirroring the corpus's own per-document split (R14-11): the Research Overview document keeps the prose form (matching MASH's combined report, unchanged), and the Top Ranking Hypotheses document now renders the same `critical_criteria` as a Criterion/Importance table (`_render_evaluation_criteria_table_markdown`, `report_markdown_supervisor.py`, wired into `report_markdown_documents.py`'s `_ranking_sections` right before Candidate Ideas — matching the protein-assemblies ranking report's own section order), pinned by `app/tests/test_report_criteria_table.py`. See `docs/PARITY.md` `RANKING-CRITERIA-TABLE-001`. A genuine two-document run settles this directly: the protein-assemblies run's `research-overview.md` carries the criteria as numbered prose under `### **Review guidelines:**` (line 125), elaborated as `### **Review Guidelines for the Structural Novelty Index (SNI)**` (line 129) with seven numbered criteria at lines 131-160, and carries no `Criteria`/`Criterion` heading anywhere in that file -- a case-insensitive grep for either word over the published overview returns nothing, exactly how this section was nearly mis-read as absent; the published heading is "Review guidelines". Its companion `top-ranking-hypotheses.md` carries the Criterion/Importance table instead, at lines 13-22. That is the exact split this repo now ships -- prose on the overview document, a table on the ranking document -- a stronger, same-shape confirmation than MASH's single combined report |
| R14-10 | The published ranking-report file is a compound document (report + an embedded full proposal + an embedded full review); whether this composition is exemplar-specific or a general Google shape cannot be settled from one run | **DECISION** | Confirmed unresolvable, now checked directly against the raw tree rather than inferred: `find`/`grep` over all of `references/` for `Top ranking proposals` returns exactly two distinct files (each itself mirrored once) — `research/supplements/ai-guided-discovery-of-atypical-protein-assemblies/reports/top-ranking-hypotheses.md` (397 lines) and `.../top-ranking-hypotheses-existing-export.md` (384 lines). Both carry the identical H1 title ("Comparative Analysis of Structural Novelty Indices (SNI) for Unconventional NRC-NLR Identification"), the same Research Goal, and — checked heading-by-heading — the identical section composition (Research Goal, Evaluation Criteria, Main Research Directions, a 10-idea Candidate Ideas list, Idea Comparison Table, Comparison with Existing Solutions, Unexpected Connections, Research Contacts, Recommendation, References, and the same embedded `Top ranking proposals` compound document ending in an 8-part Reviews summary), differing only in markdown heading-level formatting (the first file renders most sections at H1, the second mostly at H3/H4) — two export formats of one run, not two runs, so they do not constitute a second exemplar. No other research goal in the corpus has a ranking report at all: `research/extracted-artifacts/outputs/research-overviews/` holds three other overviews directly in that directory (`als-research-overview-and-contact.md`, `cf-pici-research-overview.md`/`cf-pici-research-overview-directions-2-to-6.md`, `mash-liver-fibrosis-reversal-therapeutic-hypothesis.md`), none containing `Top ranking proposals`. Stays blocked on external evidence this repo cannot supply, not on an implementation choice |
| R14-11 | A single run produces two separately-purposed report documents (`research-overview.md`, meta-review-style; `top-ranking-hypotheses.md`, tournament-comparison-style); we emit one combined document | **BUILT** | The owner decided: split. `report_markdown_documents.py`'s `render_overview_document_markdown`/`render_ranking_document_markdown` replace the former single `render_report_markdown`, allocating sections per R14-11's own two lists (corroborated by R14-1's identical six-item table of contents for the overview document, and R14-7/R14-8 for the ranking document's three): overview gets Main Directions, Review guidelines, Open questions, Unexpected connections, Research contacts, and a titles-only Top ranking hypotheses list (R11-4); ranking gets the full per-idea Candidate Ideas write-up, the Idea Comparison Table, Comparison with Existing Solutions, and the Recommendation roadmap. Persisted as one more nullable column on the existing `reports` row (`markdown_text_ranking`) rather than a second table or a second row, since both documents share one payload/timestamp/lifecycle; NULL there is the back-compat discriminator (`store/reports.py`'s docstring) an old single-document report keeps reading and sharing by, unchanged. Surfaced as a fifth "Top Ranking Hypotheses" React tab, shown only when a report carries the second document. See `docs/PARITY.md` `REPORT-DOCUMENT-SPLIT-001`. `R14-4` is now separately BUILT on top of this; `R14-3` and `R14-9`'s table-vs-prose point were re-judged and stay open, now for narrower, specific reasons (see their own rows) rather than being blocked on this one |
| R14-12 | Every published title is `# **Co-scientist - <Title>**` — bold, H1, product-prefixed, an authored noun phrase, never a full sentence; needs a dedicated LLM-composed `title` field plus a prefix-convention decision | **BUILT** | **The content half now built on top of the prefix half.** A `title` field (`_TITLE_FIELD`, `schemas/generation.py`) rides the existing generation and evolution calls, shared by identity across `GENERATION_SCHEMA`, `HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA`, and `EVOLUTION_SCHEMA` — the same three call sites `_EXPERIMENT_FIELD` (R14-20) already backs — described as a compact noun phrase under 100 characters, no trailing period (commit `3d18b7cd`). `hypothesis_from_llm_output` and evolution's `_extract_evolution_fields` carry it onto `Hypothesis.title`; the app's `_authored_title` (`app/app/engine_adapter/drain_hypothesis_title.py`) is the single point where it is preferred over the pre-existing `first_sentence(text)`, which stays exactly as the sole fallback for a run predating this field or a `json_object` downgrade that omits/mistypes/empties it (commit `3fc45294`). `report_markdown_hypothesis.py:143-153`'s bold/product-prefixed rendering (commit `9521f16a`) now wraps an authored name rather than a truncated sentence -- exercised end-to-end through a real `HypothesisGenerator` run on the offline backend (generation and evolution both) and the drain/report path, e.g. the actually-rendered `### 1. **Co-Scientist - Autophagy as a rate-limiting constraint on disease (1)**` (the trailing `(1)` is the offline filler's own ordinal suffix, not a schema artifact). |
| R14-13 | Every hypothesis carries a byte-identical one-line "About" disclaimer under its title | **BUILT** | `app/app/report_markdown_hypothesis.py:20-27` `_HYPOTHESIS_DISCLAIMER`, word-for-word the published text, explicitly cited to `R14-13` in its own comment, unconditionally rendered for every entry (`:150`) |
| R14-14 | Where populated, published `Reviews summary` is an 8-part numbered structure or a simpler two-list form — a structured schema is needed, or the divergence should be accepted and recorded | **BUILT** | The decision this row asked for has been made and recorded: `docs/PARITY.md:230` `REVIEW-SUMMARY-STRUCTURE-001` (`missing`, citing this row by ID) measured Google's own inconsistency (8/19 eight-part, 3/19 two-list, 8/19 empty) and deliberately did not impose either shape, with reasoning — "mandating either shape... would make this system's output *more* rigid than the published one it is modeling." Recording, not code, was always this row's second acceptable outcome |
| R14-15 | Within the 8-part summary, a bolded free-text Go/No-Go `**Verdict:**` and a `**Time to Verdict:**` timeframe field | **BUILT** | `engine/src/co_scientist/schemas/review.py:440-458` — `go_no_go_recommendation` and `time_to_verdict`, matching the row's own example wording almost verbatim ("Go — pursue wet-lab validation" / "'Short', '2-4 weeks', or '2-3 months'"), both optional to match Google's own 8/19 partial coverage; rendered by `report_markdown_hypothesis.py:219` (`_render_hypothesis_verdict`) |
| R14-16 | `Justification:` is a consistent first field (14/14) in per-hypothesis research contacts; the evidence-citing second field's label varies freely; whether to pin two named fields or keep one free-text field is an owner call | **BUILT** | Pinned two named fields at the rendering boundary, no schema change (commit `7df19fa8`, cites this row by ID). `app/app/report_markdown_contact_groups.py::_render_contact_body` now labels the relevance paragraph `**Justification:**`, mirroring the published field directly. The second, evidence-citing field is pinned to a fixed name of this repo's own choosing, `Supporting article:`, rather than any one of Google's varying labels (`Supporting Articles:`/`Relevant Articles:`/`Supporting Excerpt:`/`Support:`/unlabeled) -- chosen because this schema's version of the field (`source_title`/`source_url`, resolved against a real known paper by `research_overview_contacts.py`'s anti-hallucination candidate matching, never model-authored prose) is always exactly one grounded citation, so a singular, source-accurate name fits better than a plural "Articles" label implying free citation text. Kept in step with the frontend's parallel `run_detail_overview.tsx` render of the same fields, and with the demo fixtures in `app/app/seed_overview.py`, unchanged since the schema itself did not move. `docs/PARITY.md`'s `RESEARCH-CONTACTS-FIELDS-001` row (still `partial`) records this; the row's separate `expertise`-field residual is unaffected and stays open. Tests: `app/tests/test_report_contact_field_labels.py`; `app/frontend/src/workbench/pages/run_detail_overview_sections.test.tsx` |
| R14-17 | The Appendix's `All reviews:` block is always Correctness→Novelty→Feasibility→Impact potential, each with its own fixed, differently-sized sub-schema; record as an accepted divergence or add sub-structure | **BUILT** | Same pattern as `R14-14`: `docs/PARITY.md:231` `REVIEW-AXIS-STRUCTURE-001` (`partial`, citing `R14-17` by name) both *acted* (axis ordering in `schemas/review.py`'s `_SCORE_CRITERIA` now matches Correctness-first) and *recorded* the sub-structure decision, with two measured cost scenarios (41-67% more input tokens, 62-205% more output tokens) rather than assuming one. Commit `37c999a2`; pinned by `engine/tests/test_schemas.py::test_review_score_axes_are_correctness_first` |
| R14-20 | `Steps to Test the Idea` is a numbered pilot-then-scale-up plan ending in an explicit `**Go:**`/`**No-Go:**` pass/fail threshold; ours is one free-text paragraph | **BUILT** | `engine/src/co_scientist/schemas/generation.py:84-121` `_EXPERIMENT_FIELD` now structures exactly this shape — numbered steps ending in a Go/No-Go step with explicit pass/fail thresholds — commit `9a4fd222` ("structure the experiment field as a Go/No-Go pilot plan"); rendered by `app/app/report_markdown_hypothesis.py:108-125` (`_render_hypothesis_experiment`, "#### Steps to test the idea"), commit `8bb19ade` |
| R14-21 | Two per-hypothesis bibliography forms exist; extends `R12-19` with per-hypothesis evidence that "neither the Generation-side nor Reflection-side citation list renders anywhere," backed by "`grep -rn 'citation_map' app/app/report_markdown*.py` — zero hits" | **FALSE** | The grep result the row states does not reproduce: running the identical command today returns a hit at `app/app/report_markdown_references.py:8` (its own module docstring, naming `citation_map` directly), and that module is a full working renderer — same finding as `R12-19` above, now doubly confirmed. `report_markdown_references.py` resolves each hypothesis's `citation_map` into a rendered References list, wired at `report_markdown.py:343`, pinned by `app/tests/test_report_markdown_references.py` |
| R14-22 | Where populated, `Deep verification:` is a numbered list of simulated-protocol flaws; original reading said nothing renders it, corrected in-row to say the real gap is that `simulation_review`'s `failure_points`/`decisive_step` (the field that actually matches this shape) has no renderer | **BUILT** | `app/app/report_markdown_hypothesis.py:182-216` (`_render_hypothesis_simulation_review`) renders `simulation_review.failure_points` as a numbered flaw list plus a `**Decisive step:**` line, wired at `:307`; commit `16ebdce2` ("tighten the ledger note and add an end-to-end render test") |
| R14-24 | Corrects an earlier reading: the 11-vs-8 Deep-verification-populated split is not truncation, verified section-by-section against three files; a footnote is needed wherever the wrong file-length framing might be cited | **BUILT** | The correction is the row itself, positioned exactly where a reader would encounter the original claim — its own "Decided by" column states the correction in full, with the three-file verification recorded inline, satisfying the row's own ask ("a footnote here correcting the file-length framing") |
| R14-26 | The canonical top-level section sequence of a published hypothesis document is fixed (14 sections in a stated order); we have no per-hypothesis document assembly matching it, conditional on the owner wanting a fuller per-idea artifact | **BUILT** | Owner call: keep the flat per-idea entry, no 14-section document. `_render_hypothesis_entry` (`report_markdown.py:285-321`) still renders one flat entry, not a 14-section document in this order -- deliberately: the Top Ranking Hypotheses document already carries mechanism, steps to test, verdict, simulation review, and claim evidence per idea (R14-11), so a separate per-hypothesis document would largely restate it |
| R14-27 | New finding, not in the original checklist (found while scoping this wave's Evaluation Criteria table, `R14-9`): the published ranking report carries its own `# **Main Research Directions**` section (`top-ranking-hypotheses.md:24-28`) -- two prose paragraphs summarising the strategic landscape across the run's ideas, distinct from the Research Overview document's five-item expanded directions list | **BUILT** | **Closing pass (2026-09-04).** Built on the owner's own design call: hosted on `META_REVIEW_SCHEMA`, not `RESEARCH_OVERVIEW_SCHEMA` -- every other synthesized section on this same document (Idea Comparison Table, Comparison with Existing Solutions, Recommendation, R14-7/R14-8) already comes from the meta-review payload, and `RESEARCH_OVERVIEW_MAX_TOKENS` (24000, equal to `BUDGET_ESCALATION_MAX_TOKENS`) was the wrong node to grow. `main_research_directions` (`engine/src/co_scientist/schemas/meta_review_schema.py`) is a required two-paragraph prose string, described in the run's own vocabulary (bolded direction names inline, why each matters, a closing cross-direction observation) rather than a restatement of `strategic_recommendations`; `meta_review.md`'s new item 7 asks for it in those terms. `meta_review_node`'s `_build_meta_review` maps it straight through unchanged. `report_markdown_meta_review.py::_render_main_research_directions_markdown` renders "## Main Research Directions" (this repo's plain `##`-heading convention, not the published bold-H1 style), wired into `_ranking_sections` (`report_markdown_documents.py`) right after the Evaluation Criteria table and before Candidate Ideas -- the exact published order this row and `R14-9` both cite. Skips cleanly (no bare heading) when the field is absent or blank -- a legacy run persisted before this field existed, or a `json_object`-mode provider response that omits it. Deliberately left required, not optional, in the schema: every run has directions worth naming, so the offline backend's generic single-leaf filler already populates it with no `_OPTIONAL_FIELD_HINTS` entry needed (confirmed by `test_optional_field_hints_matches_the_schemas_full_optional_set`, which would otherwise force one). The three curated demo runs each carry a scenario-specific two-paragraph narrative grounded in that scenario's own top-3 hypotheses, not a generic template (`app/app/seed_meta_review_directions.py`, following the `seed_overview_directions.py` per-scenario-module precedent); `DEMO_SEED_VERSION` bumped 12→13 so production re-seeds. See `docs/PARITY.md` `MAIN-RESEARCH-DIRECTIONS-001`. Tests: `engine/tests/test_meta_review.py::test_main_research_directions_maps_through`; `engine/tests/test_offline_llm.py::test_offline_meta_review_fills_main_research_directions`; `app/tests/test_report_main_research_directions.py`; `app/tests/test_seed.py::test_seed_demo_runs_render_main_research_directions` |

**R14: 18 BUILT / 0 OPEN / 1 DECISION / 2 FALSE.**

Noticed in passing: `R14-9` and `R14-21` (both FALSE above) both cite `R12-18`/`R12-19` respectively as still-open in their own "Decided by" text — both of those underlying rows are now BUILT, which is exactly why the two R14 rows read as false today; nothing further to flag beyond what's already recorded against each.

## MA — architecture (mirror-fidelity pass)

| Row | Table says (`work`) | Verdict | Evidence |
|---|---|---|---|
| MA-1 | 51 of the ledger's rows / 65 citations point at local consolidations (`SSR §n` etc.), none at the papers themselves, and the `PAPER —` prefix conflates the two; needs every row re-sourced against the papers, with what has no published basis dropped or relabelled | **BUILT** | Confirmed by direct count: `docs/PARITY.md` carries 77 requirement rows (matching `make parity`'s own "77 requirement rows" line), of which only 8 (`EVO-LINEAGE-001`, `CITE-CLAIM-001`, `CITE-META-001`, `CITE-GRAPH-001`, `SAFE-INTAKE-001`, `SAFE-FINAL-001`, `SAFE-ADVERSARIAL-SET-001`, `SAFE-GOOGLE-SET-001`) now cite a bare consolidation shorthand (`SSR`/`TE`/`ARCH`/`RGV §n`), down from the row's own count of 51 — and all 8 explicitly self-disclose as "local consolidation" / "local-consolidation... not paper text" in their own Source column, rather than carrying a false `PAPER —` prefix. The Legend (`docs/PARITY.md:57-76`) now states the rule explicitly: "Such a row does not carry the `PAPER —` prefix; see `docs/PARITY-SOURCES.md`." The remaining 69 rows cite arXiv/Nature SI/`App.` sections directly. This is exactly "drop or relabel" carried out at ledger scale |
| MA-2 | Nature SI's `DecideNextSteps` lets independent `IF`s stack several follow-up tasks (rank + evolve + meta-review + report) in one decision pass; ours is a strict single-winner chain — a real behavioural difference; needs a code change or a recorded divergence | **BUILT** | `docs/PARITY.md:125` `SUP-STACKING-001` (new row, same citation — "Nature SI Note 8, `DecideNextSteps` (L950-972)") records exactly this: `scheduling/policy.py`'s `_ordered_checks`/`required_transition` is confirmed still "a strict single-winner chain, one task per orchestrator cycle, never a stack," recorded `partial`, "Accepted divergence: a real behavioural difference in how fast a run makes progress per cycle" |
| MA-3 | The paper describes per-hypothesis independent task chaining; this repo's two execution paths (streaming LangGraph engine vs. durable app) diverge from each other on this point, not just from the paper; needs the divergence named and a canonical path decided | **BUILT** | `docs/PARITY.md:131` `EXEC-PATH-CHAIN-001` (new row) names both paths exactly as the row describes and resolves the "which is canonical" question: "The durable path is canonical — it is the only path production runs." Cites `app/AGENTS.md:48` |
| MA-4 | The paper describes one continuously-adaptive Supervisor; this repo splits it into a one-shot `supervisor_node` and a continuously-running `orchestrator_node`, a name pairing neither primary source uses; needs either mid-run plan revisitation or a recorded deliberate split | **BUILT** | `docs/PARITY.md:121` `SUP-SPLIT-001` (new row, cites "arXiv Figure 2 caption") records the exact split by file:line (`supervisor.py:33`, `orchestrator.py:153`) and its consequence ("the plan `supervisor_node` synthesizes once is never revisited mid-run"), status `partial`, "Accepted divergence" |
| MA-5 | The paper's research overview is periodic and feeds back into Generation; ours runs once, at termination, with no edge back into `generate`; needs a graph edge and periodicity, or a recorded divergence | **BUILT** | `docs/PARITY.md:233` `OVERVIEW-NIH-001`'s residual states the structural fact plainly: "the 'periodic' half is not [real]... It runs exactly once, at run termination, with no edge back into `generate`" (confirmed unchanged: `generator/graph.py:168` still only `workflow.add_edge("research_overview", END)`). More significant: `docs/fidelity-audit/FINDINGS.md:206` `I2` records that the *behavioral* gap this structural difference was meant to prevent is independently closed — `state["meta_review"]`'s `emerging_themes`/`potential_connections` now thread into every generation strategy, so generation does receive the overview-style synthesis content the paper describes, just not through the `research_overview` node itself. "Behavioral gap closed; the structural claim stands as an accepted divergence" |
| MA-6 | "Flexible compute scaling" is realized as four fixed tier presets chosen once at run creation, not continuous mid-run adaptation; needs a recorded divergence or an implementation | **BUILT** | `docs/PARITY.md:129` `SCALE-TIER-001` records exactly this as `partial`, "Accepted divergence: within a run, budget exhaustion/convergence still end it dynamically (`SUP-TERMINATE-001`), but the scale of compute funded is a one-time preset choice at run creation, not continuous mid-run adaptation" |

**MA: 6 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

## MC — pseudocode (mirror-fidelity pass)

| Row | Table says (`work`) | Verdict | Evidence |
|---|---|---|---|
| MC-4 | The blocking, never-revisited initial-review disposition gate has no counterpart in any published pseudocode listing (`engine/CLAUDE.md`'s own gotcha records it disqualifying 20 of 22 ideas in one production run); needs a ledger row naming it a local addition | **BUILT** | `docs/PARITY.md:229` `REVIEW-GATE-LOCAL-001` is exactly this row: "LOCAL ADDITION — no published counterpart," `verified`, citing `review_gate.py:136`'s `_apply_initial_review_gate`, `models.py:258`'s `is_rankable()`, and the monotonic-block mechanism in `mature_reviews.py:90-101` — and its residual quotes the same "20 of 22" figure from `engine/CLAUDE.md`'s gotcha verbatim |

**MC: 1 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

## MO — outputs (mirror-fidelity pass)

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| MO-2 | A 5-theme, 2-3-level-deep critique taxonomy; the state-shaping loss is closed, but `recurring_themes[]` remains a flat `{theme, description, frequency}` — the fix commit itself calls this "an accepted adaptation," which this row does not yet record as a formal decision | **BUILT** | Recorded, as the row's own residual asked for — no schema change made. `docs/PARITY.md`'s new `META-CRITIQUE-TAXONOMY-001` row (`partial`, cites `corpus MO-2`) states the flat shape and the acceptance by name, quoting the fix commit (`69d10874`, "an accepted adaptation") and the reason it stands: meta-review runs once per evolve iteration, so a nested 2-3-level taxonomy would multiply structured-output size on every one of those calls. `engine/src/co_scientist/agents/meta_review/meta_review.py:371` `_normalize_recurring_themes` is unchanged — confirmed still flat, per the wave's own instruction not to deepen it |
| MO-4 | Published per-assumption wording is prose (`Plausible:`, `Plausible, but requires careful investigation:`, `Unknown:`); the enum-disagreement half is closed (one shared `ASSUMPTION_SUPPORT_VALUES` enum), but adopting the published wording is deferred | **BUILT** | Same fix as `R12-15` (audited above); not double-counted. `engine/src/co_scientist/schemas/review.py:20-25` `ASSUMPTION_SUPPORT_VALUES` is still `supported`/`uncertain`/`likely_false` -- deliberately: adoption happens at the rendering boundary (`app/app/engine_adapter/drain_reviews.py::_ASSUMPTION_SUPPORT_LABELS`), not the stored value, since a programmatic reader downstream (`mature_reviews._project_full_review`) keys off the literal enum string. See `R12-15`'s evidence cell for the full account, including why the third value renders as "Implausible" rather than the published "Unknown" |
| MO-5 | Two appended reviews close with a bare `Answer: 4`/`Answer: 3`; whether the scale is 1-5, 1-10, or something else (a separate reading found values 2-9 for a different block) is unresolved | **BUILT** | Same resolution as `R10-7` (audited above), which this row explicitly narrows: the scale is 1-10, stated directly in Google's own prose (`research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md:91`, "1-10 quality score"; `research/papers/accelerating-scientific-discovery-with-co-scientist.md:336`, "out of 10" auto-eval scores), and the four-dimension `Answer: N` closings in the protein-assemblies detailed-output file confirm it — see `R10-7`'s evidence cell for the full citation set and the 57-occurrence, 2-9 range. **Correction to this row's own framing:** the wider 2-9 values do not belong to "a *different* per-dimension block" — they are the same construct as this row's own two cited closings. This row's `Answer: 3` is `.../outputs/validated-outputs/kira6-detailed-output-validated.md:220`, itself a Novelty block (preceding heading: "Reasoning about novelty and recommendation"), and its `Answer: 4` is `research/papers/towards-an-ai-co-scientist.md:1893`, under `#### Novelty review` — both members of the same per-dimension review-closing family the 2-9 range is drawn from, not a separate one. Not double-counted against `R10-7` |
| MO-11 | The research goal is intake as three named parts (`Title`, `Goal`, `Background`); ours is one free-text field | **BUILT** | Same underlying question as `R1-18`/`R10-9`/`R14-2` (audited above): `app/app/runs_models.py:29` `research_goal: str` stays one field -- owner call: accept the divergence, since the interview already elicits this kind of structure conversationally into the run plan, which fits the product better than a fixed intake form. Not double-counted — one decision (canonical goal-intake shape) closes all four rows |
| MO-12 | Two published overviews use different vocabularies for the same slot; the ALS third slot (`recent_findings`) is now closed, but both exemplars also use a **doubled structure** (a brief preview list, then full detail) that a single array still cannot express | **BUILT** | Achieved in the renderer alone, no new model output or schema change. `app/app/report_markdown_overview.py::_render_directions_preview` front-loads a named preview list (`- {title}` per direction, reusing the existing required `title` field) ahead of the unchanged full per-direction detail (`_render_directions_list`), mirroring both exemplars' cadence ("We will be focusing on these interrelated areas" / "Main Research Directions" before their per-direction sections). Gated to 2+ named directions -- a preview of one entry would duplicate it rather than orient the reader, per this wave's own caution against a preview that repeats rather than names. Malformed/untitled directions are dropped from the count the same way the existing per-direction renderer already tolerates them. Pinned by three new tests in `app/tests/test_report_markdown_overview.py`: `test_two_or_more_directions_get_a_preview_list` (preview text precedes the first `### {title}` detail heading), `test_a_single_direction_gets_no_preview_list`, `test_an_untitled_direction_is_dropped_from_the_preview_count` |

**MO: 5 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

## MP — prompts (mirror-fidelity pass)

| Row | Table says (`work`) | Verdict | Evidence |
|---|---|---|---|
| MP-6 | Published `ranking-04`/`ranking-05` hand the judge a `{preferences}` slot; we substitute `criteria`, leaving the judge blind to scientist input whenever only `preferences` was supplied | **BUILT** | Commit `245ced81` ("thread the scientist's preferences into the judge prompt") wires `preferences=state.get("preferences")` into `ranking.py:248`, `ranking_debate_turns.py:199-212`, and `ranking_prompt.py:35,241`; pinned by `test_judge_prompt_carries_scientist_preferences` (`engine/tests/test_ranking_debate.py:362`). Already noted as fixed by `docs/PROMPT-PRESERVATION.md`'s own standing rule, cross-checked directly here rather than taken on that document's word |
| MP-7 | Both published evolution prompts scaffold a four-step reasoning order (domain overview → recent-research synopsis → viability argument → core contribution); dropped entirely, not merely reformatted | **BUILT** | `engine/src/co_scientist/prompts/templates/evolution.md:43-50` ("## Reasoning Order") now carries all four steps near-verbatim, restored by commit `37ff7260` ("restore the published reasoning-order scaffold (MP-7)"). Notable timing: this fix landed *after* `docs/PROMPT-PRESERVATION.md`'s own evolution-06/07 audit was written (audit commit `c2ea5b17`, 22:55:08 on 2026-09-01; fix commit `37ff7260`, 22:58:59, four minutes later) — that document still lists this instruction "missing" for both prompts it audited, correctly as of its own write time, now stale on this one point. Not a defect in that document (a dated point-in-time record, not meant to be updated), but worth flagging here since a reader might otherwise trust its "missing" verdict as current |
| MP-8 | `OUT_OF_BOX` takes no partner hypotheses, while `INSPIRATION` is the operator that structurally matches published A.7; name and content are attached to different operators; needs a rename or a corrected mapping note | **BUILT** | `engine/src/co_scientist/agents/evolution/evolution_operators.py:15-24`'s module docstring names `MP-8` directly and states the resolution: the mismatch is real and deliberately not renamed (`EvolutionOperator.OUT_OF_BOX` is a persisted value in lineage records and telemetry, so renaming is "a data-migration decision for the owner, not a prompt-content fix") — the docstring itself is the corrected mapping note the row asked for as its other acceptable outcome |

**MP: 3 BUILT / 0 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: `docs/PROMPT-PRESERVATION.md`'s evolution-06/07 rows (its own summary table, "4 present / 1 missing / 0 adapted" for each) are now stale on the MP-7 point, for the timing reason above — not a defect in that document per its own "point-in-time record, not updated" convention (`docs/README.md`), but a reader treating its "1 missing" as current today would be looking for a gap that has since closed (both are now 5/0/0).

---

## Decisions for the owner (deduplicated)

Zero owner decisions remain open. The Summary table's one remaining
DECISION row, `R14-10` (item 10 below), was never an owner decision —
it is blocked on a second published exemplar this repo cannot supply.
Item 3 below, the bare `Answer: N` review-score scale (`R10-7`/`MO-5`,
2 rows, 1 question), is the last owner-facing item to close, resolved
by evidence rather than by an owner call:

1. ~~Goal-intake shape and the three glossary terms.~~ **Resolved: keep
   the single free-text field.** `R1-18`, `R10-9`, `R14-2`, `MO-11` (4
   rows, 1 question) are now **BUILT** — see the owner-accepted-divergence
   wave closing pass above. `app/app/runs_models.py:29` `research_goal:
   str` stays one free-text field; the corpus shows at least three
   different published shapes (SSR §11's flat glossary; A.1's
   `Title`/`Goal`/`Background` triple; the protein-assemblies run's 8-part
   form with `Ground Truth Dataset`/`Your Role`), but none is adopted as
   canonical and the three glossary terms stay descriptive prose, not a
   controlled vocabulary — the interview already elicits this kind of
   structure conversationally and writes it into the run plan, which fits
   the product better than a fixed intake form.
2. ~~Per-assumption wording.~~ **Resolved: mirror the published wording
   at the rendering boundary, stored enum unchanged.** `R12-15`, `MO-4`
   (2 rows) are now **BUILT** — see the owner-directed-wave closing pass
   above and `docs/PARITY.md` `REVIEW-ASSUMPTION-WORDING-001`. Two of
   the three values render as the published prose (`supported` to
   "Plausible", `uncertain` to "Plausible, but requires careful
   investigation"); the third, `likely_false`, keeps a non-published
   label ("Implausible") since Google's exemplar never marks a
   genuinely contradicted assumption, only an untested one, and reusing
   "Unknown" for it would understate the verdict.
3. ~~The bare `Answer: N` review-score scale.~~ **Resolved: 1-10, stated
   directly in Google's own text.** `R10-7`, `MO-5` (2 rows, 1 question)
   are now **BUILT** — see the `REVIEW-SCALE` wave closing pass above and
   each row's own evidence cell. Google states it in prose twice — "each
   research goal was rated on a 1-10 quality score" and Reflection-agent
   auto-eval scores reported "(out of 10)" — and the value range settles
   it independently: 57 deduplicated `Answer: N` occurrences across the
   corpus span 2-9, impossible on a 1-5 scale. The earlier "3 or 4, six
   times total" reading held only for `docs/CORPUS-EXTRACTION.md`'s
   Appendix, which mirrors a small slice of these blocks; the raw corpus
   tree resolves it. This is a different score from
   `EVAL-REVIEW-SCALE-001`'s named "co-scientist review score" (Figure
   A.23's selection gate, still correctly 1-5) — the two scores coexist
   in the published system, and `docs/PARITY.md`'s row is corrected to
   say so.
4. ~~Split the report into two documents.~~ **Resolved: split, and
   synthesize the ranking document's own goal restatement.** `R14-11`,
   `R14-4`, and now `R14-3` (all 3 of the original rows) are **BUILT** —
   see the `R14-11` closing pass and the `R14-3` closing pass above, and
   `docs/PARITY.md`
   `REPORT-DOCUMENT-SPLIT-001`/`REPORT-ABOUT-DISCLOSURE-001`. The Top
   Ranking Hypotheses document's `**Goal:**` line now carries a freshly
   synthesized narrative restatement (`app/app/report_goal_synthesis.py`)
   instead of the raw-flattened block the Research Overview document
   still renders — see `R14-3`'s own evidence cell. Fully resolved; no
   residual.
5. ~~A flat bibliography list.~~ **Resolved: added, on the Research
   Overview document.** `R12-12` is now **BUILT** — see its own row above
   and `docs/PARITY.md` `BIBLIOGRAPHY-001`. `app/app/report_markdown_bibliography.py`
   renders a deduplicated `## References` section from `store.list_evidence`
   (DOI, then PMID, then URL, then normalized title, as the dedup key),
   placed on the Research Overview document — MASH's own span sits in
   `research-overviews/`, not the ranking document, which keeps its
   distinct per-hypothesis `#### References` (`R14-21`). The three
   curated demos now carry real PMIDs wired through from their evidence
   URLs (`DEMO_SEED_VERSION` 10→11).
6. ~~Named `Justification:`-plus-evidence contact fields.~~ **Resolved:
   pin two named fields, no schema change.** `R14-16` is now **BUILT** —
   see the owner-directed-wave closing pass above and `docs/PARITY.md`
   `RESEARCH-CONTACTS-FIELDS-001`. The relevance paragraph renders under
   the published `Justification:` label; the second, variably-labeled
   evidence field renders under a fixed name of this repo's own choosing,
   `Supporting article:`, since this schema's version of it is always
   exactly one grounded citation, never free citation prose.
7. ~~A 14-section per-hypothesis document.~~ **Resolved: keep the flat
   per-idea entry.** `R14-26`, explicitly conditional ("if the owner
   wants a fuller per-idea artifact"), is now **BUILT** — see the
   owner-accepted-divergence wave closing pass above. The Top Ranking
   Hypotheses document already carries mechanism, steps to test,
   verdict, simulation review, and claim evidence per idea (R14-11), so
   a separate per-hypothesis document would largely restate it.
8. ~~Archive or extract the two gitignored mp4s.~~ **Resolved: extracted
   and committed.** `R13-1`. Both mp4s were watched in full before
   deletion; the frames they were cited for are committed at
   `docs/assets/live-footage/` (`docs/CORPUS-EXTRACTION.md` `R13-1`,
   commit `a2cf38eb`). The raw mp4s remain unrecoverable once
   `references/` is deleted, but nothing depends on them any more.
9. ~~PubMed's disclosure status.~~ **Resolved: recorded as a labelled
   local (CLONE) choice.** `R9-4` is now **BUILT** — see the
   owner-directed-wave closing pass above and `docs/PARITY.md`
   `TOOLS-CONFIG-001`'s residual, which now states by name that Google
   confirms only ChEMBL and UniProt, never PubMed or arXiv, so a future
   reader cannot mistake PubMed's primacy in this system for a disclosed
   Google integration.
10. **Not an owner decision — blocked on unavailable evidence.** `R14-10`.
    Whether the published ranking-report's compound structure (report +
    embedded full proposal + embedded full review) is exemplar-specific or
    a general shape cannot be settled without a second published exemplar,
    which does not exist in the corpus. Nothing inside this repo closes
    it.
11. ~~Cosmetic, only if the owner wants it.~~ **Resolved: accepted as a
    divergence, recorded rather than built.** `R12-13` is now **BUILT** —
    see the `R8-4`/`R12-13` closing pass above and `docs/PARITY.md`
    `REPORT-HEADING-DUPLICATION-001`. `## Top hypotheses` stays emitted
    exactly once; doubling it to match the published capture would read
    as a rendering bug in this product, and the row itself already
    flagged the published duplication as probably a transcription
    artifact rather than a shape to mirror.
12. ~~A paid live A/B for ranking-05's missing "Pose clarifying
    questions" instruction.~~ **Resolved: added, without a live A/B.**
    `R8-4` is now **BUILT** — see the `R8-4`/`R12-13` closing pass above
    and `docs/PARITY.md` `RANK-DEBATE-CLARIFY-001`. The owner's governing
    directive for this campaign (where Google published an exact prompt,
    mirror it) settles the question the same way it settled decisions
    #2/#6/#9: the instruction now renders verbatim, in the published
    position, on every follow-up debate turn
    (`ranking_debate_turns.py::_append_debate_context`); the
    answerless-rate risk an earlier wave weighed stays unmeasured
    offline and is accepted as a known risk rather than a blocker.

---

## Residuals inside BUILT/FALSE rows

Four points are folded into a BUILT or FALSE verdict above rather than
carrying their own row; listed here so a future pass does not have to
re-read every evidence cell to find them.

- **`R12-17` / `R12-18` / `R12-23` had no `docs/PARITY.md` row — now
  resolved.** Was: all three genuinely BUILT — `app/app/report_markdown_
  supervisor.py`, pinned by four app tests — but nothing in
  `docs/PARITY.md` cited that module (zero hits for "stratification",
  "evaluation criteria", "review summary", or `critical_criteria`,
  checked directly). Three ledger rows now cite it:
  `STRATIFICATION-ATTRIBUTES-001`, `EVALUATION-CRITERIA-001`,
  `REVIEW-SUMMARY-001` (closing-pass wave, 2026-09-04).
- **`R12-23`'s `Research directions` half was still open — now resolved.**
  Was: the row bundled two asks; only `Review summary` was built. Now
  split into its two genuinely different asks: `Unexpected Research
  Directions` — genuinely novel content this repo did not previously
  hold — is BUILT (`docs/PARITY.md` `UNEXPECTED-RESEARCH-DIRECTIONS-001`);
  the restated-five-main-directions half is an accepted divergence, not
  built, citing `R12-13`'s own precedent (same closing-pass wave; see
  `R12-23`'s own evidence cell above).
- **`R14-9`'s table-vs-prose format point survived its FALSE verdict —
  now resolved.** Was: the row's central claim ("`R12-18` still absent")
  is false, but its narrower observation — a second published exemplar
  renders synthesized criteria as a table, this product always rendered
  prose — was real and unresolved. Now closed by mirroring the corpus's
  own per-document split: prose stays on the Research Overview document
  (matching MASH), and the Top Ranking Hypotheses document now renders
  the same data as a table (matching the protein-assemblies ranking
  report), citing `docs/PARITY.md` `RANKING-CRITERIA-TABLE-001` (same
  closing-pass wave; see `R14-9`'s own evidence cell above). Along the
  way this pass also found `R14-9`'s own earlier "would fabricate data"
  reasoning was itself wrong — corrected in-cell, the `R6-6`/`R12-14`/
  `MO-5` style — and a genuinely new gap: the ranking document's own
  `Main Research Directions` prose section has no analogue here, now
  tracked as its own new row, `R14-27` (**OPEN**), not folded into this
  residual.
- **`R6-6`'s `CITE-META-001` / `assess_resolvability` orphan is resolved.**
  Was: `claims_gate.assess_resolvability` never called from production, and
  a *different* live resolver (`citation_resolver.resolve_many`) is wired
  for a related-but-distinct availability check, with `CITE-META-001`'s
  residual overstating the gap. Both the clarifying correction (commit
  `ef7a0bed`) and the narrower discard it surfaced
  (`_resolved_from_requests` collapsing the live `RETRACTED` verdict into
  plain `available=False`, since fixed) are now folded into R6-6's own
  BUILT verdict above. `CITE-META-001`'s `assess_resolvability`/`Resolver`
  orphan itself remains genuinely open and outside this document's scope
  (that ledger row stays `partial`, not `work`).

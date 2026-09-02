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

## R6 — retrieval, grounding, and verification

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R6-5 | FINDINGS `G4`'s evidence line claims bioRxiv, Open Targets, and ClinicalTrials "no longer appear" in config; the row says all three are now registered with real backends | **OPEN** | The row's claim is confirmed live, not just declared: `engine/src/co_scientist/config/tools.yaml` registers `preprint_search` (bioRxiv/medRxiv, `enabled: true`), `open_targets`, and `clinical_trials`, each backed by a real MCP tool — `engine/mcp_server/tools/lit_review/europepmc_search.py:134` (`search_preprints`), `engine/mcp_server/tools/systems_biology.py:188` (`search_open_targets`), `engine/mcp_server/tools/clinical_trials.py:63` (`search_clinical_trials`), each with its own test file. `docs/fidelity-audit/FINDINGS.md:172` and `:384` still say these three "no longer appear" / have "no runnable backend" — both lines are now stale and need the one-line correction the row asks for |
| R6-6 | Crossref plays two distinct roles in the corpus — literature *search* (deliberately absent, per `G4`) and *retraction lookup* (would close `CITE-META-001`'s residual) — and a future reader must not collapse them | **OPEN** | Confirmed still two different facts, and still not clarified anywhere: Crossref is absent from `tools.yaml` (search role, correctly rejected) **and** absent from `app/app/citation_resolver.py` and `app/app/retraction_set.py` (no `crossref`/`api.crossref.org` reference in either — the retraction-resolver role is not implemented either, so there is nothing to accidentally collapse yet, but the clarifying line the row asks for on `G16`/`CITE-META-001` is still missing). Tracing `CITE-META-001` further while here: its `partial` residual ("no live resolver is wired") is itself now imprecise — `app/app/engine_adapter/drain_evidence_resolution.py:87` *does* wire `citation_resolver.resolve_many` live (`settings.evidence_resolver == "live"`, the production default) into the drain's evidence-availability check, but that path feeds `ResolvedArticle.available` in `drain_hypotheses.py`, not `claims_gate.assess_resolvability`'s `Resolvability` (RESOLVABLE/UNRESOLVABLE/RETRACTED) — `assess_resolvability` is never called from any production module (`app/app/citations.py::classify_citation`, the actual citation-classification path, does not call it either), only from `app/tests/test_claims.py`. This is a distinct, deeper finding than the row asked for; flagging it here rather than expanding `R6-6`'s scope, since it belongs to `CITE-META-001`/`G16`, not to the search-vs-resolver naming point the row makes |

**R6: 0 BUILT / 2 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: `CITE-META-001` (`docs/PARITY.md:167`, `partial`) and FINDINGS `G16` describe the resolvability seam as unwired to any live resolver. That is true for `assess_resolvability` specifically, but a live resolver *is* wired for a related-but-distinct availability check (`drain_evidence_resolution.py`, see above) — the residual's "no live resolver is wired" reads as a stronger claim than is now accurate and would benefit from distinguishing the two paths. Not re-classified here (out of the R6-5/R6-6 scope; the ledger rows themselves are `partial`/open, not `work`, so they are outside this document's audit set) — recorded so a future pass does not re-discover it from zero.

## R8 — the eight published prompts, re-checked

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R8-2 | The published-prompt→template mapping was recorded but never checked for content preservation; needs "a one-off semantic diff of all eight prompts against their templates" | **BUILT** | `docs/PROMPT-PRESERVATION.md` (dated 2026-09-01) is exactly that diff — all eight prompts, instruction-by-instruction, classified present/missing/adapted with line-cited evidence. Summary: 4 prompts fully preserved, 4 with residual gaps (1–2 missing instructions each). Supersedes this row |
| R8-4 | 14/19 sentences of `ranking-05` poorly covered; two things unsettled: the turn-count envelope (code vs. prompt) and "Pose clarifying questions to address any ambiguities" (0.0 coverage) | **OPEN** | The turn envelope is settled, as the row itself already concludes: enforced in code (`engine/src/co_scientist/agents/ranking/ranking.py:234`, `RANK-DEBATE-DEPTH-001` `verified`), correctly not restated in the prompt. The clarifying-questions instruction is confirmed still genuinely missing: it is in the verbatim Appendix (`docs/CORPUS-EXTRACTION.md:1231`, "Pose clarifying questions to address any ambiguities or uncertainties") and appears nowhere in `engine/src/co_scientist/prompts/templates/ranking.md` or `agents/ranking/ranking_debate*.py` (zero grep hits). Worth noting: `docs/PROMPT-PRESERVATION.md`'s own 9-item instruction table for this same prompt (§7) does not list this instruction either — its audit missed it too, so this finding survives a second, more careful pass and is not an artifact of the first one being incomplete |
| R8-6 | Published debate judge is framed as a plurality ("simulating a panel of domain experts", "The experts possess no pre-existing biases") — contradicts FINDINGS `E18`'s "the paper names a single evaluator"; needs a correction to `E18` and one framing line in `ranking.md` | **OPEN** | Confirmed neither deliverable exists: `engine/src/co_scientist/prompts/templates/ranking.md` has zero occurrences of "panel", "domain expert", "pre-existing", or "bias"; `docs/fidelity-audit/FINDINGS.md:138` (`E18`) still reads "the paper's tournament prompts name a single evaluator", uncorrected. Note the tension with `docs/PROMPT-PRESERVATION.md` §7 item 1, which marks the same published sentence "present" — but on looser grounds ("the multi-turn matchup loop itself" functions like a panel), not the literal textual framing this row specifically asked for. The row's concrete ask (textual framing + `E18` correction) is unmet either way |

**R8: 1 BUILT / 2 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

## R9 — build methodology and tech-stack findings

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R9-2 | Live open-source-project verdicts (Jataware FORK PRIMARY; LLNL/Sakana v2/FutureHouse Robin/OpenScientist-K-Dense/aimclub MINE; The-Swarm-Corporation INSPECT; mims-harvard REJECT) exist nowhere outside the corpus file; needs an ADR so the decisions survive `references/` deletion, per the `references/peripheral/` precedent | **OPEN** | No ADR under `docs/decisions/` (12 files, none of them) mentions any of these projects. The only repo-wide hit outside `references/` is `README.md:201`'s Acknowledgements list, which names Jataware and Sakana as citations, not as recorded FORK/MINE/INSPECT/REJECT decisions — it does not carry the verdicts or the reasoning behind them |
| R9-3 | `tech-stack-findings.md`'s citation-disciplined uncertainty register (Google never names source languages, frontend/backend framework, storage, queue, or retrieval index) is worth preserving; needs folding into FINDINGS' "Evidence boundaries" table | **OPEN** | `docs/fidelity-audit/FINDINGS.md:520-548` ("Evidence boundaries — unknowable from public sources") has 22 rows and does not include this register — no row for source language, frontend/backend framework, or retrieval-index disclosure status. Not yet folded in |
| R9-4 | Google's own sources confirm ChEMBL and UniProt as named integrations but not PubMed or arXiv, in tension with this repo where PubMed is the primary retrieval path; the row itself frames this as unsettled by any ledger row | **DECISION** | `docs/PARITY.md:235` (`TOOLS-CONFIG-001`) documents the YAML mechanism as a local product implementation but says nothing about PubMed's confirmed-vs-inferred status, and does not mention ChEMBL/UniProt at all — the tension is still unresolved in the ledger. The actual question for the owner: should `TOOLS-CONFIG-001` (or a new row) record PubMed's primacy as a labelled CLONE choice, or leave it as an implicit PRODUCT claim? Nothing in the corpus or code settles which |

**R9: 0 BUILT / 2 OPEN / 1 DECISION / 0 FALSE.**

Noticed in passing: none.

## R10 — `research/papers/`

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R10-1 | A 15-item Specific Aims evaluation rubric (5 significance/innovation + 10 rigor/feasibility axes, 5-point Likert) exists in the paper with no counterpart in this repo's 6-axis `expert_review.py` instrument | **BUILT** | `evaluations/datasets/specific_aims_rubric_v1.json` (commit `eb9291d7`, 2026-09-01) carries the 15 axes verbatim; `evaluations/specific_aims_review.py` (238 lines) adds a separate blinded export/import mode (`SPECIFIC_AIMS_AXES`, `AGREEMENT_SCALE`) kept deliberately unmerged with `RATING_AXES`. `docs/PARITY.md:217` `EVAL-SPECIFIC-AIMS-RUBRIC-001` (`verified`), pinned by `evaluations/tests/test_specific_aims_rubric.py` (148 lines) |
| R10-2 | The rubric is explicitly a non-validated pilot framework; this caveat must ride the same row/artifact as R10-1 | **BUILT** | Carried verbatim as `provenance_caveat` in `specific_aims_rubric_v1.json:8` ("PILOT framework... explicitly not a validated instrument... 'would require considerable further research'") and repeated in `specific_aims_review.py`'s module docstring |
| R10-3 | Figure A.23's expert-review selection gate implies the published co-scientist review score is on a **1–5** scale, not our 1–10 | **BUILT** | `docs/PARITY.md:218` `EVAL-REVIEW-SCALE-001` (`verified`, commit `6e387043`) records the divergence as a labelled reconstruction — 1-10 (`engine/src/co_scientist/schemas/review.py` `REVIEW_SCORE_MINIMUM`/`MAXIMUM`) vs. the published 1-5 gate — pinned by `engine/tests/test_review_batch_isolation.py::test_score_fields_are_bounded_to_the_rubric_range`. Recording only, as the row's own residual asked for — no scale change made or implied |
| R10-7 | A bare `Answer: N` closing on a review block; the scale is never stated in the source text, and 3/4 exemplars fit either a 1–5 or 1–10 scale | **DECISION** | Every `Answer: N` occurrence in the verbatim Appendix (`docs/CORPUS-EXTRACTION.md:1650+`) is 3 or 4 (checked directly: `grep -oE 'Answer: ?[0-9]+'` over the whole file returns only values 3 and 4, six times total) — consistent with, but not proof of, either scale. `MO-5` (audited below) cites a "separate reading" finding values 2–9 for a *different* per-dimension block, which would rule out 1–5, but that reading is not itself mirrored anywhere in the Appendix available here, so it cannot be independently verified from this repo's sources. `EVAL-REVIEW-SCALE-001` (R10-3, now `verified`) settles the *named* "co-scientist review score" at 1–5 but is about Figure A.23's selection gate, a different score than this row's bare `Answer: N` closings — it does not resolve this row. Still genuinely unresolved; see `MO-5` for the fuller three-way scale tension |
| R10-8 | The published detailed output ends in a **Critiques** block — "a summary of the negative critiques from the reviews" — a per-idea rollup distinct from the run-level meta-review critique | **OPEN** | Confirmed still absent: the idea-detail UI's "Review critiques" section (`app/frontend/src/workbench/components/tabs/ideas_detail_pane.tsx:177-204`, `ReviewCritiquesContent`) renders every individual review row verbatim, not a synthesized single-paragraph negative-critique summary; no equivalent section exists in `app/app/report_markdown.py` or its siblings. Needs: a synthesized per-idea negative-critique rollup, separate from both the existing per-review list and the run-level meta-review critique |
| R10-9 | Three glossary terms — "Novel repurposing candidate", "Novel target", "Novel mechanistic explanation" (source: A.1 Glossary) | **DECISION** | Same question as `R1-18` (source: SSR §11, same three terms). Not implemented as a controlled vocabulary; see `R1-18` above for the one coincidental match and the unresolved decision. Not double-counted as separate work — one decision closes both rows |
| R10-10 | The 15-axis rubric applied verbatim to two worked exemplars (lapatinib, selinexor) with filled-in Likert ratings; these are the dataset half of R10-1 | **BUILT** | Both exemplars are in `specific_aims_rubric_v1.json` with per-axis ratings (lapatinib 11 Strongly Agree/3 Agree/1 Neutral, selinexor 7/8), plus Givosiran's absent rating block preserved and explained rather than dropped — matching the row's own description exactly. Same evidence as R10-1 |
| R10-11 | The arXiv paper and the Nature SI disagree on at least three facts (Selinexor panel size/experience, OCT4 validation tool list, an inter-rater Spearman's rho statistic present in only one); nothing in `docs/` records the two sources are different documents | **BUILT** | `docs/PARITY-SOURCES.md` (71 lines, new, commit `6e387043`) records all three divergences by name, added to `docs/README.md`'s index, and cited from `docs/PARITY.md`'s Legend (`:76`, `:87`) plus the two rows that previously cited a bare "Nature paper" (`SCALE-TIER-001:129`, `REFLECT-DEEPVERIFY-ORDER-001:228`) |
| R10-12 | The rubric's 5-point scale is an **agreement** scale (not a quality score) and does not share a scale with the 1–5/1–10 review score; this caveat must ride the same row as R10-10 | **BUILT** | `specific_aims_rubric_v1.json` and `specific_aims_review.py` both state this explicitly and by name — `AGREEMENT_SCALE` is a distinct constant from `expert_review.py`'s `RATING_AXES` scale, and the module docstring calls out that it "shares no scale with `RATING_AXES`' 1-5 quality ints, nor with the paper's own 1-5 co-scientist review score... nor with this repo's 1-10 review score" |

**R10: 6 BUILT / 1 OPEN / 2 DECISION / 0 FALSE.**

Noticed in passing: none.

## R11 — `research/supplements/`

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R11-1 | All 19 hypotheses in Google's one complete published run carry near-identical titles on a narrow goal — the same symptom this repo treats as a defect (FINDINGS `K2`, the near-duplicate guard gotcha); needs a note on `evaluations/metrics.py::hypothesis_diversity` and/or FINDINGS | **OPEN** | Confirmed still missing: `evaluations/metrics.py:35-54`'s `hypothesis_diversity` docstring has no such caveat, and neither `K2` (`docs/fidelity-audit/FINDINGS.md:238`) nor `K3` (`:239`) mentions Google's own run as a counter-example to "low title diversity = defect." Needs: one caveat sentence, either place, noting the published run shows the same near-zero title diversity on a narrow goal |
| R11-3 | Published review vocabulary (Correctness/Novelty/Feasibility/Impact potential/Motivation/Coherence/Deep verification labels; an 8-part numbered `Reviews summary`; bolded `Verdict: No-Go`/`Verdict: Proceed with Testing` dispositions) overlaps but does not match ours; "Review schema vocabulary, if wanted" was left as an open decision | **BUILT** | The row explicitly hands off to the closer R14 pass ("a full document-shape read of all 22 files is R14"), which made and recorded exactly this decision, twice: `docs/PARITY.md:230` `REVIEW-SUMMARY-STRUCTURE-001` (from `R14-14`) measured both the 8-part and two-list published forms and deliberately did **not** impose either (Google's own output is inconsistent 8/3/8 across the sample — imposing one shape would be more rigid than the source), and `docs/PARITY.md:231` `REVIEW-AXIS-STRUCTURE-001` (from `R14-17`, commit `37c999a2`) adopted the Correctness→Novelty→Feasibility→Impact-potential **ordering** in `engine/src/co_scientist/schemas/review.py`'s `_SCORE_CRITERIA` without renaming axes, and measured (not assumed) that per-axis sub-schemas cost 41-67% more input / 62-205% more output tokens depending on shape, both flagged against the task's 2x bound. The disposition-vocabulary piece is independently already built: `schemas/review.py:440-458`'s `go_no_go_recommendation` field is rendered as bolded Go/No-Go framing by `app/app/report_markdown_hypothesis.py:219` (`_render_hypothesis_verdict`), functionally matching the published "Verdict: No-Go"/"Verdict: Proceed with Testing" pattern. The decision this row asked for has been made, with numbers, and recorded — not a full vocabulary rename, but a considered choice, not an open question any more |
| R11-4 | The published run's own "Top ranking hypotheses" list names 20 hypothesis IDs but only 19 have files on disk; anyone citing this run as a pool-size ground truth needs a 19-of-20 caveat wherever it is cited | **BUILT** | The one other place in `docs/` that discusses this run's contents, `docs/CORPUS-EXTRACTION.md`'s `R14` section intro (`:633`), already carries the caveat by name ("the missing 20th hypothesis"). No other file in `docs/` (`docs/PARITY.md`, `docs/fidelity-audit/*.md`) mentions "protein-assemblies" or cites this run's pool size at all — checked directly, zero hits — so there is currently no other citation site missing the note |
| R11-8 | Nature SI Note 3 / Supplementary Table 1 publishes fully quantified per-agent ablation numbers for Reflection's search tool, Evolution, and Meta-review, plus Ranking-prompt and Proximity findings named without numbers; `EVAL-ABLATION-001`'s residual says meta-review and debate-strategy have no toggle seam — exactly the arms Google published numbers for | **BUILT** | `evaluations/ablation_driver.py:93-141` (`PUBLISHED_BASELINES`, commit `0c54580e`) carries every number the row names verbatim — Reflection search-tool (novelty 6.14→2.38, correctness 7.4→8.46, GPQA AUC 0.643→0.651, with an explicit "not uniformly directional, do not smooth" note), Evolution (precision 70.9%→75.4%, quality 4.7→5.6), Meta-review (AUC 0.521→0.597 constructed, 0.629→0.634 GPQA) — as read-only reference data, never computed or gated on locally. Ranking-prompt and Proximity are recorded as `PUBLISHED_BASELINES_UNQUANTIFIED` rather than fabricated. `docs/PARITY.md:209` `EVAL-ABLATION-001` residual updated to match; pinned by `evaluations/tests/test_ablation_driver.py` |

**R11: 3 BUILT / 1 OPEN / 0 DECISION / 0 FALSE.**

Noticed in passing: none.

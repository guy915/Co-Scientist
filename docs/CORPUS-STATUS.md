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
| R1 | 3 | 2 | 0 | 1 | 0 |
| R6 | 2 | 2 | 0 | 0 | 0 |
| R8 | 3 | 2 | 0 | 1 | 0 |
| R9 | 3 | 2 | 0 | 1 | 0 |
| R10 | 9 | 7 | 0 | 2 | 0 |
| R11 | 4 | 4 | 0 | 0 | 0 |
| R12 | 13 | 7 | 2 | 3 | 1 |
| R13 | 7 | 6 | 0 | 1 | 0 |
| R14 | 20 | 11 | 0 | 7 | 2 |
| MA | 6 | 6 | 0 | 0 | 0 |
| MC | 1 | 1 | 0 | 0 | 0 |
| MO | 5 | 2 | 0 | 3 | 0 |
| MP | 3 | 3 | 0 | 0 | 0 |
| **Total** | **79** | **55** | **2** | **19** | **3** |

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

R13's row count is 7, not the 6-row naive parse: it includes `R13-12`'s
part (a), which a naive table-column split misreads because the row's own
text contains a literal `|` inside a quoted video title (part (b) is
`external`, out of scope). 79 rows classified in total.

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

---

## R1 — SSR consolidation

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R1-12 | Elo-quality concordance should bucket by Elo in 50-point increments and compute accuracy per bucket | **BUILT** | `evaluations/elo_concordance_eval.py::elo_bucket_accuracy` (EVAL-METHODS wave) now implements Google's published method exactly: pools every candidate's final Elo across items, buckets in 50-point increments anchored the same way the paper's own boundaries are (1001-1050, 1051-1100, ...), and reports percent-correct per bucket. Kendall's tau-b stays alongside it, kept as an independent sanity check of the harness's own Elo math rather than a substitute for the published method — a deliberate keep-both decision, not an oversight. `docs/PARITY.md:207` (`EVAL-ELO-CALIB-001`, still `partial`) now correctly names only the remaining gap — licensed GPQA corpus, credentials, and the paper's Gemini-2.0 reference-accuracy baseline — not a method difference. Tests: `evaluations/tests/test_elo_concordance_eval.py` |
| R1-13 | Scaling should partition one run's hypotheses into ten equal temporal buckets, tracking best/top-10-average Elo across them | **BUILT** | `evaluations/scaling_eval.py::temporal_scaling_curve` (EVAL-METHODS wave) implements the published method: partitions ONE run's hypotheses into ten equal buckets, reporting best Elo and top-10-average Elo per bucket, never varying tier. Its ordering key (`_temporal_order_key`) is `generation` — the engine's own lineage ordinal, not raw `created_at` — after a real offline run showed `created_at` alone lands one generation call's whole batch of siblings within under a millisecond of each other (the engine's `Hypothesis` model carries no per-hypothesis timestamp), which is drain-order noise, not a temporal signal; `generation` is real and confirmed to vary in a real run (`test_offline_snapshot_carries_a_real_temporal_curve` asserts ≥2 distinct values). `scaling_budget_driver.py` wires it per arm (`snapshot["temporal_curve"]`), and — unlike the pre-existing cross-tier `scaling_curve()`, which stays harness-only offline (the deterministic backend answers identically at every tier) — this genuinely orders by cycle even offline, though at coarser resolution than the paper's continuous wall-clock partition (an express/standard arm only ever reaches generation 0 and 1). Degenerate cases handled: an empty run, a run with fewer than ten hypotheses (confirmed against a real offline express run, which produces 8), and hypotheses with no Elo yet. `docs/PARITY.md:208` (`EVAL-SCALING-001`, still `partial`) now describes both methods, the generation-vs-created_at distinction, and what each method does and does not tell us. Tests: `evaluations/tests/test_scaling_eval.py`, `evaluations/tests/test_scaling_budget_driver.py` |
| R1-18 | Three glossary terms — "novel repurposing candidate", "novel target", "novel mechanistic explanation" — as a controlled vocabulary | **DECISION** | Not implemented as a controlled vocabulary anywhere in engine or app code. One coincidental match: `engine/src/co_scientist/config/examples/indra_ibd.yaml:39` defines "novel mechanistic explanation" as a domain-specific term for one example config (IBD), unrelated to the SSR's system-wide glossary. The open question is unchanged from the row: whether these three terms should be load-bearing (e.g. as an enum somewhere) or are merely descriptive prose the schema doesn't need |

**R1: 2 BUILT / 0 OPEN / 1 DECISION / 0 FALSE.**

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
| R8-4 | 14/19 sentences of `ranking-05` poorly covered; two things unsettled: the turn-count envelope (code vs. prompt) and "Pose clarifying questions to address any ambiguities" (0.0 coverage) | **DECISION** | The turn envelope is settled, as the row itself already concludes: enforced in code (`engine/src/co_scientist/agents/ranking/ranking.py:234`, `RANK-DEBATE-DEPTH-001` `verified`), correctly not restated in the prompt. The clarifying-questions instruction is confirmed still genuinely missing -- verbatim Appendix (`docs/CORPUS-EXTRACTION.md:1231`), zero grep hits in `ranking.md`/`ranking_debate*.py`, and Google places it as the first bullet under ranking-05's "Subsequent turns:" guidance (multi-turn debate turns after the first), not in the verdict step. `docs/PROMPT-PRESERVATION.md`'s own §7 instruction table missed it too, now corrected with a footnote. **Weighed and not built, this wave.** Ranking's judge is the run's most expensive call site (~46% of tokens by an earlier measurement) and already carries a measured ~23% `LLMThinkingOnlyError` rate on this exact prompt family (13/56 calls, live run) -- reasoning spent, then a stop with no answer -- where a fix that works elsewhere "underperforms badly." "Pose clarifying questions" invites more open-ended deliberation before commitment, which is the shape of that exact failure mode; a sibling instruction already ships safely in this codebase's generation-02 debate templates (`generation_after_debate.md:43`), but that is not transferable safety evidence here, since the same live measurement says this specific prompt family behaves worse than others on the underlying failure. The token cost itself is not the concern and was measured offline (`litellm.token_counter`, gpt-4o tokenizer): the one bullet line is ~13 tokens; at ~2.6 subsequent-turn renders per multi-turn matchup (3.6 turns/match measured) across ~25 multi-turn matchups in a full run (`docs/PROMPT-PRESERVATION.md` §7), that is roughly 850 tokens/run -- negligible. What cannot be measured offline is the answerless-rate effect: the deterministic offline backend fills the schema from `(model, prompt, schema)` and never returns answerless regardless of prompt content, so nothing in this repo's offline evals or hermetic CI is sensitive to this change, and a live A/B would cost real money against a cost-sensitive stealth-model deployment. Recorded at the code site (`ranking_debate_turns.py::_append_debate_context` docstring) so a future pass does not re-derive this. The owner's question: accept a paid live A/B measuring the judge's answerless rate before/after, or accept the fidelity gap |
| R8-6 | Published debate judge is framed as a plurality ("simulating a panel of domain experts", "The experts possess no pre-existing biases") — contradicts FINDINGS `E18`'s "the paper names a single evaluator"; needs a correction to `E18` and one framing line in `ranking.md` | **BUILT** | The `E18` half was already done (`docs/fidelity-audit/FINDINGS.md:138`, commit `c310a560`): states the paper frames the judge as a plurality, quotes the panel/bias-neutrality sentence verbatim, cites this row, and correctly preserves what stays true -- the paper never names distinct advocate/opponent *personas* for that panel. `ranking_debate.py::_run_debate_turns`'s docstring was already fixed too. The remaining deliverable now lands, this wave: `engine/src/co_scientist/prompts/templates/ranking.md`'s opening line now reads "You are a Tournament Judge Agent in the Co-Scientist framework, simulating a panel of domain experts engaged in a structured discussion," echoing the published framing. Deliberately not added: an assertion that "the experts possess no pre-existing biases" -- audited and classified adapted-and-stronger in `docs/PROMPT-PRESERVATION.md` §7 item 3, since this judge already enforces impartiality structurally (both A/B presentation orders via `_render_ordered_prompt(swapped=True)`, a position-balanced fallback on malformed output) rather than asserting a claim the model cannot verify about itself. Pinned by two new tests in `engine/tests/test_ranking_prompt.py` (`test_matchup_prompt_frames_the_judge_as_a_panel`, `test_panel_framing_does_not_dislodge_the_decisive_verdict_instruction` -- the latter confirms "Make a clear decision" and the literal `better idea: 1`/`2` verdict format still render unchanged). Token cost measured (`litellm.token_counter`, gpt-4o tokenizer, same method as `R8-4`): the added clause is 13 tokens versus the unchanged opening sentence, and unlike `R8-4`'s subsequent-turn-only guidance, this line sits in the base prompt every turn re-renders (`ranking_debate_turns.py::_render_ordered_prompt`) -- roughly 65 single-turn matchups x 1 render plus ~25 multi-turn matchups x 3.6 turns/match (`docs/PROMPT-PRESERVATION.md` §7) is ~155 renders/run, so ~2,000 tokens/run, negligible against the run's total spend |

**R8: 2 BUILT / 0 OPEN / 1 DECISION / 0 FALSE.**

Noticed in passing: none.

## R9 — build methodology and tech-stack findings

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R9-2 | Live open-source-project verdicts (Jataware FORK PRIMARY; LLNL/Sakana v2/FutureHouse Robin/OpenScientist-K-Dense/aimclub MINE; The-Swarm-Corporation INSPECT; mims-harvard REJECT) exist nowhere outside the corpus file; needs an ADR so the decisions survive `references/` deletion, per the `references/peripheral/` precedent | **BUILT** | `docs/decisions/2026-09-02-open-source-coscientist-landscape.md` (PRESERVE wave) records all eight verdicts in a table, cites this row by ID, and confirms directly (not assumed) that none of the eight is vendored or forked anywhere in this tree — Jataware and Sakana appear only in `README.md`'s Acknowledgements as prior-art citations. Two things found along the way, folded into the ADR rather than left for a future reader to rediscover: The-Swarm-Corporation's bare INSPECT verdict was already carried out in depth by `docs/decisions/2026-08-23-chat-interface-reference-drain.md`'s "namesake, head to head" comparison (read in full, this repo ahead on dedup/lineage/durability/safety); and "OpenScientist/K-Dense" (this row's MINE verdict) is not the same product as the tool-skills bundle at `vendor/science-skills/`, whose own attribution is itself inconsistent between `NOTICE` (Google DeepMind) and the 2026-08-23 ADR (K-Dense-AI) — flagged, not resolved |
| R9-3 | `tech-stack-findings.md`'s citation-disciplined uncertainty register (Google never names source languages, frontend/backend framework, storage, queue, or retrieval index) is worth preserving; needs folding into FINDINGS' "Evidence boundaries" table | **BUILT** | Folded into `docs/PARITY.md`'s "Notes on clone-defined vs Google-specified" section instead of FINDINGS' table — a deliberate re-scoping for the PRESERVE wave, not an oversight: this register is about Google's undisclosed *implementation stack*, which is exactly what that section's closing paragraph already discusses (the reference corpus's proposed-and-rejected stack), so the six categories now sit beside it as a corroborating fact rather than a new requirement, cited to this row (commit `f0be5657`). `docs/fidelity-audit/FINDINGS.md:520-548`'s "Evidence boundaries" table was left untouched — it already covers adjacent ground (queue/DB/retrieval-provider disclosure status) at a different granularity, and duplicating the same six categories into a second table was judged to add confusion, not clarity |
| R9-4 | Google's own sources confirm ChEMBL and UniProt as named integrations but not PubMed or arXiv, in tension with this repo where PubMed is the primary retrieval path; the row itself frames this as unsettled by any ledger row | **DECISION** | `docs/PARITY.md:235` (`TOOLS-CONFIG-001`) documents the YAML mechanism as a local product implementation but says nothing about PubMed's confirmed-vs-inferred status, and does not mention ChEMBL/UniProt at all — the tension is still unresolved in the ledger. The actual question for the owner: should `TOOLS-CONFIG-001` (or a new row) record PubMed's primacy as a labelled CLONE choice, or leave it as an implicit PRODUCT claim? Nothing in the corpus or code settles which |

**R9: 2 BUILT / 0 OPEN / 1 DECISION / 0 FALSE.**

Noticed in passing: none.

## R10 — `research/papers/`

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R10-1 | A 15-item Specific Aims evaluation rubric (5 significance/innovation + 10 rigor/feasibility axes, 5-point Likert) exists in the paper with no counterpart in this repo's 6-axis `expert_review.py` instrument | **BUILT** | `evaluations/datasets/specific_aims_rubric_v1.json` (commit `eb9291d7`, 2026-09-01) carries the 15 axes verbatim; `evaluations/specific_aims_review.py` (238 lines) adds a separate blinded export/import mode (`SPECIFIC_AIMS_AXES`, `AGREEMENT_SCALE`) kept deliberately unmerged with `RATING_AXES`. `docs/PARITY.md:217` `EVAL-SPECIFIC-AIMS-RUBRIC-001` (`verified`), pinned by `evaluations/tests/test_specific_aims_rubric.py` (148 lines) |
| R10-2 | The rubric is explicitly a non-validated pilot framework; this caveat must ride the same row/artifact as R10-1 | **BUILT** | Carried verbatim as `provenance_caveat` in `specific_aims_rubric_v1.json:8` ("PILOT framework... explicitly not a validated instrument... 'would require considerable further research'") and repeated in `specific_aims_review.py`'s module docstring |
| R10-3 | Figure A.23's expert-review selection gate implies the published co-scientist review score is on a **1–5** scale, not our 1–10 | **BUILT** | `docs/PARITY.md:218` `EVAL-REVIEW-SCALE-001` (`verified`, commit `6e387043`) records the divergence as a labelled reconstruction — 1-10 (`engine/src/co_scientist/schemas/review.py` `REVIEW_SCORE_MINIMUM`/`MAXIMUM`) vs. the published 1-5 gate — pinned by `engine/tests/test_review_batch_isolation.py::test_score_fields_are_bounded_to_the_rubric_range`. Recording only, as the row's own residual asked for — no scale change made or implied |
| R10-7 | A bare `Answer: N` closing on a review block; the scale is never stated in the source text, and 3/4 exemplars fit either a 1–5 or 1–10 scale | **DECISION** | Every `Answer: N` occurrence in the verbatim Appendix (`docs/CORPUS-EXTRACTION.md:1650+`) is 3 or 4 (checked directly: `grep -oE 'Answer: ?[0-9]+'` over the whole file returns only values 3 and 4, six times total) — consistent with, but not proof of, either scale. `MO-5` (audited below) cites a "separate reading" finding values 2–9 for a *different* per-dimension block, which would rule out 1–5, but that reading is not itself mirrored anywhere in the Appendix available here, so it cannot be independently verified from this repo's sources. `EVAL-REVIEW-SCALE-001` (R10-3, now `verified`) settles the *named* "co-scientist review score" at 1–5 but is about Figure A.23's selection gate, a different score than this row's bare `Answer: N` closings — it does not resolve this row. Still genuinely unresolved; see `MO-5` for the fuller three-way scale tension |
| R10-8 | The published detailed output ends in a **Critiques** block — "a summary of the negative critiques from the reviews" — a per-idea rollup distinct from the run-level meta-review critique | **BUILT** | Recorded, as the row's own residual asked for -- not built as a feature. `docs/PARITY.md`'s new `REVIEW-CRITIQUES-ROLLUP-001` row (`missing`, commit `85320235`, cites `corpus R10-8`) states the gap by name: a synthesized per-idea negative-critique rollup, distinct from both the existing per-review list (`ideas_detail_pane.tsx`'s `ReviewCritiquesContent`, still every review rendered verbatim) and the run-level meta-review critique. `docs/PARITY-VERIFICATION.md`'s snapshot moved 79->80 rows to carry it |
| R10-9 | Three glossary terms — "Novel repurposing candidate", "Novel target", "Novel mechanistic explanation" (source: A.1 Glossary) | **DECISION** | Same question as `R1-18` (source: SSR §11, same three terms). Not implemented as a controlled vocabulary; see `R1-18` above for the one coincidental match and the unresolved decision. Not double-counted as separate work — one decision closes both rows |
| R10-10 | The 15-axis rubric applied verbatim to two worked exemplars (lapatinib, selinexor) with filled-in Likert ratings; these are the dataset half of R10-1 | **BUILT** | Both exemplars are in `specific_aims_rubric_v1.json` with per-axis ratings (lapatinib 11 Strongly Agree/3 Agree/1 Neutral, selinexor 7/8), plus Givosiran's absent rating block preserved and explained rather than dropped — matching the row's own description exactly. Same evidence as R10-1 |
| R10-11 | The arXiv paper and the Nature SI disagree on at least three facts (Selinexor panel size/experience, OCT4 validation tool list, an inter-rater Spearman's rho statistic present in only one); nothing in `docs/` records the two sources are different documents | **BUILT** | `docs/PARITY-SOURCES.md` (71 lines, new, commit `6e387043`) records all three divergences by name, added to `docs/README.md`'s index, and cited from `docs/PARITY.md`'s Legend (`:76`, `:87`) plus the two rows that previously cited a bare "Nature paper" (`SCALE-TIER-001:129`, `REFLECT-DEEPVERIFY-ORDER-001:228`) |
| R10-12 | The rubric's 5-point scale is an **agreement** scale (not a quality score) and does not share a scale with the 1–5/1–10 review score; this caveat must ride the same row as R10-10 | **BUILT** | `specific_aims_rubric_v1.json` and `specific_aims_review.py` both state this explicitly and by name — `AGREEMENT_SCALE` is a distinct constant from `expert_review.py`'s `RATING_AXES` scale, and the module docstring calls out that it "shares no scale with `RATING_AXES`' 1-5 quality ints, nor with the paper's own 1-5 co-scientist review score... nor with this repo's 1-10 review score" |

**R10: 7 BUILT / 0 OPEN / 2 DECISION / 0 FALSE.**

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
| R12-4 | Published Criteria are three named settings with explicit values (`Idea correctness: Required`, etc.); ours are four free-prose strings, different in shape and content | **OPEN** | Confirmed unchanged: `app/app/run_modes.py:39-44` `DEFAULT_CRITERIA` is still 4 free-prose sentences ("Scientific soundness", "Novelty over known mechanisms", "Discriminating experimental design", "Translational feasibility") — no named-setting-with-value shape, no PARITY row |
| R12-5 | Published Attributes are a structured 1-5 scoring rubric (4 anchored scales + 1 categorical); ours is `list[str]` free text | **OPEN** | Confirmed unchanged: `app/app/run_modes.py:34-38` `DEFAULT_ATTRIBUTES` is still three free strings ("Mechanistically specific", "Evidence-grounded", "Experiment-ready"), no scale, no anchors, no categorical field. (Distinct from `config_synthesis.attributes`, the Supervisor-synthesized field R12-17 covers below — this row is about the run's own *setup* attributes) |
| R12-12 | The published report's flat 3,259-entry `References` list has no analogue; whether ours (`Citation audit` + data sources, a different artifact) should also get a flat list is explicitly left to the owner | **DECISION** | Confirmed unchanged: no bibliography/reference-list renderer exists anywhere in `app/app/report_markdown*.py` (zero hits for "bibliography"/"reference_list"); `report_markdown_sources.py` still emits only search counts and served questions, not a source list. The row's own framing stands — this needs the owner's call, not more code investigation |
| R12-13 | The published report's "Top ideas" heading appears twice (open and close); may be a transcription artifact | **DECISION** | Confirmed unchanged: `## Top hypotheses` is still emitted exactly once (`app/app/report_markdown.py:345`). Unresolved by design — the row itself says "none unless the owner wants it" |
| R12-14 | Published score composition is printed as `score = novelty + details + usefulness + pairwise rank = 11`; ours is a mean of the review rubric's axes — needs a ledger row recording the divergence, not a change | **BUILT** | `docs/PARITY.md`'s new `SCORE-COMPOSITION-001` row (`partial`, commit `1928f03f`, cites `corpus R12-14`) records exactly this, recording only as the row asked. One correction along the way: `docs/CORPUS-EXTRACTION.md`'s own checklist row cites the formula as sourced from `kira6-detailed-output-validated.md`, "corroborated by" the drug-repurposing supplement -- but `kira6` carries only bare per-axis `Answer: N` closings (see `R10-7`/`MO-5`), zero occurrences of this formula. The formula actually appears in `hypotheses/liver-fibrosis-epigenetic-targets.md`'s two worked Generation-agent examples, which is what the new PARITY row cites instead |
| R12-15 | Published per-assumption wording is prose (`Plausible:`, `Plausible, but requires careful investigation:`, `Unknown:`); ours is the closed enum now unified as `supported`/`uncertain`/`likely_false` (`engine/src/co_scientist/schemas/review.py:20-25`, `ASSUMPTION_SUPPORT_VALUES`) — adopting the published wording is left to the owner | **DECISION** | Same open question as `MO-4` (audited below), which already frames it precisely: the enum-disagreement half is closed (one shared enum across both schemas that used to drift), but "neither enum prints `Plausible:`/`Unknown:` — that adoption decision is still deferred." Not double-counted as separate work — one decision closes both rows |
| R12-16 | The one research-contacts exemplar carries exactly two fields (name, free-text relevance paragraph); whether ours invents extra fields needs the same check `test_specific_aims_schema_adds_nothing_the_exemplars_lack` applies elsewhere | **BUILT** | `docs/PARITY.md`'s new `RESEARCH-CONTACTS-FIELDS-001` row (`partial`, commit `537041c7`, cites `corpus R12-16`) records this, and corrects the row's own premise along the way: a direct read of the exemplar (Figure A.22) shows **three** observable fields, not two -- it also carries a Research Direction heading, which this repo's schema already matches deliberately (`MO-7`). Of the schema's five fields, three map onto the exemplar (`name`, `justification`, `research_direction`); `candidate_id` is unrendered anti-hallucination provenance never shown to the reader; `expertise` is the one genuinely unattested addition. Recording only -- the pin test this row's own residual named as the next step (`test_published_artifact_shapes.py`-style) does not yet exist for this schema |
| R12-17 | The published run's Attributes are named 1-5 rating scales with worked anchors, not plain labels; the row found this "half-built and the built half invisible" — the Supervisor already synthesizes `config_synthesis.attributes` and injects it into review prompts, but nothing renders it | **BUILT** | `app/app/report_markdown_supervisor.py` (243 lines) — its own docstring names this row by ID and closes it: `_render_stratification_attributes_markdown` (`:48-76`) renders "## Stratification Attributes" from `config_synthesis.attributes`, deliberately titled to avoid conflating it with the run's plain-string setup attributes. Wired into `report_markdown.py:448` via `report_build.py:214` (`attributes=req.attributes`); pinned by `app/tests/test_report_stratification_attributes.py` and `app/tests/test_drain_stratification_attributes.py`. Only the row's second half ("decide whether reviewers score against them") stays open, and that decision is already effectively made — `prompts/review.py` already injects them into every reviewer prompt as "Stratification attributes (score each 1-5)", per the same docstring |
| R12-18 | The Supervisor synthesizes goal-specific evaluation criteria (`workflow_plan.review_phase.critical_criteria`) but nothing renders them — "we synthesize the second kind and then hide it" | **BUILT** | Same module, same docstring, names `R12-18` explicitly: `_render_evaluation_criteria_markdown` (`report_markdown_supervisor.py:127-169`) renders "## Evaluation Criteria" from `critical_criteria`, wired into `report_markdown.py:469` via `report_build.py:215`. Pinned by `app/tests/test_report_critical_criteria.py` and `app/tests/test_drain_critical_criteria.py`. The row's separate observation that the *interview* path never populates the plain-string `setup.criteria` field is unaffected — that is a distinct, still-true fact about a different field, not part of what this row asked to fix |
| R12-19 | An inline citation marker in body prose can carry its own verdict tag (e.g. `[17 (unsupported)]`); claims our nearest analogue is a separate bulleted block, and that `report_markdown.py` "never renders `literature_grounding` at all... so those keys are generated, paid for, and discarded" | **FALSE** | The discarding claim does not survive a read. `app/app/engine_adapter/drain_hypotheses.py:407` sets `mechanism=h.get("literature_grounding") or ""` — the app's `mechanism` field literally **is** `literature_grounding`'s content, `[C1]` markers included, rendered verbatim by `report_markdown_hypothesis.py:97-105` (`_render_hypothesis_mechanism`) under "**Mechanism:**". Those keys are then resolved to a References list by `app/app/report_markdown_references.py` (119 lines, its own module, wired at `report_markdown.py:343` via `references_by_hypothesis`), with its own test file `app/tests/test_report_markdown_references.py`. The row's grep evidently checked `report_markdown.py`'s own render function for a field literally named `literature_grounding` and found only `mechanism`/`expected_effect` — missing that `mechanism` *is* that field under its drain-layer name, and missing the sibling module entirely. What survives: our citation markers appear inline (not absent, as the row implies) but genuinely carry no verdict tag (`(unsupported)`-style) — `_render_claim_evidence` (`report_markdown_hypothesis.py:63-77`) still renders claim verdicts as a **separate** bulleted block after the prose, exactly as the row correctly describes for that narrower point. So: the "discarded" claim is false; the "no inline verdict tag" claim is true |
| R12-23 | Published `Review summary` restates the run's criteria as 16 yes/no reviewer questions grouped under 5 criteria — the reader-facing form of R12-18, and absent | **BUILT** | Same module again, names `R12-23` explicitly: `_render_review_summary_markdown` (`report_markdown_supervisor.py:212-243`) renders "## Review Summary" — each criterion with its named reviewer questions — wired into `report_markdown.py:469` (shares `critical_criteria` with R12-18), same tests. The row's other half, `Research directions` restating the five main directions with an `Unexpected Research Directions` block, is unaddressed by this module and not otherwise found — the row bundles two asks; only the `Review summary` half is built |

**R12: 7 BUILT / 2 OPEN / 3 DECISION / 1 FALSE.**

Noticed in passing: none beyond `R12-23`'s partial resolution (noted inline above — its `Research directions` half stays open, folded into the row's own verdict rather than split into a new row).

## R13 — `media/`

Includes `R13-12`'s part (a) — the naive table-column split misreads this row
because its own text contains a literal `|` inside a quoted video title; part
(b) is `external` and out of scope.

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R13-1 | The two live-footage mp4s are gitignored, uncommitted, and unrecoverable once `references/` is deleted; needs an owner decision — archive outside the repo, or extract and commit the cited frames | **DECISION** | Confirmed unchanged: `git check-ignore -v` still matches both mp4s against `.gitignore:46`. No archival or frame-extraction has happened. This is inherently the owner's call, not resolvable from the tree |
| R13-2 | The 2026-06-21 ADR and the plan-config file read two different tier selectors (three options vs. four) from the same footage folder; needs a note on every row resting on either capture, naming which one | **BUILT** | The note already exists exactly where it is needed: `docs/CORPUS-EXTRACTION.md`'s "Carry this caveat" paragraph, immediately after the R12-1/R12-2 table, names both rows explicitly ("R12-1 and R12-2 rest on the plan-config capture... see R13-2. Any row written from this must name which capture it rests on") |
| R13-3 | `docs/UI-FIDELITY.md` cites an unrecoverable mp4 frame as evidence for the four-tab mapping; needs re-pointing at the tracked JPG that shows the same tab bar | **BUILT** | `docs/UI-FIDELITY.md:109-111` (the "Evidence for the mapping" note) already re-points to `media/hypothesis-generation/esn-knowledge-base-analytical-pipelines.jpg` ("tracked in git... shows *Ideas · Knowledge Base · Summary · Run Specification*"), explicitly stating the mp4 frame "is unrecoverable" and naming the tracked JPG as "the surviving evidence" |
| R13-6 | 18 of 41 files in the Google Labs page capture are inert tooling with nothing to extract; the HTML itself carries product copy (R13-7) that must be pulled out before pruning to the HTML, 2 PNGs and 3 SVGs | **BUILT** | The row's ask was extract-then-prune; extraction is now done (see `R13-7`), and the prune step itself is deliberately not carried out here — the PRESERVE wave's own hard constraint forbids touching `references/` at all, so the actual file deletion stays the owner's action at `references/` deletion time, by design, not a gap. What was missing and is now recorded is the inventory itself, self-contained so a future reader does not need `references/` to trust it: of the capture's 41 `_files/`, 18 are inert tooling carrying nothing extractable — Google Tag Manager (×2), the YouTube player runtime (×2), a widget-API script plus an iframe loader, Lottie, a cookie-consent bar (×2), Fonts CSS (×2), a closure-library bootstrap, site CSS/JS (×2), and `www-player.css` (×2) — leaving the HTML, 2 PNGs, and 3 SVGs as the only files worth keeping. Source: `docs/CORPUS-EXTRACTION.md:389` (this row, verbatim) |
| R13-7 | Google's own Labs page copy for "Hypothesis Generation — Built with Co-Scientist" (tagline, four capability cards, "Express interest" waitlist framing) is nowhere quoted in `docs/`; needs a short quoted block in `docs/FIDELITY.md`, cited to this file | **BUILT** | `docs/FIDELITY.md`'s new "Google's own framing of this product" section (PRESERVE wave, commit `33379a06`) quotes the `og:title`, the "Express interest" waitlist framing (explicitly noted as a waitlist, not self-serve), the Hypothesis Generation tagline, and all four capability cards verbatim, cited to `docs/CORPUS-EXTRACTION.md:390`. Two existing claims in the same file that paralleled this framing without citing it now point at the new block instead — the "UI exposes hypotheses..." invariant row (also fixing a dangling "see the note below on retired tabs" pointer that resolved to nothing) and the Literature Insights/Computational Discovery out-of-scope note — and `docs/EXPLAINER.md`'s opening paragraph gets one pointer sentence rather than a duplicate quote. Nothing needed correcting on the self-serve point: neither file claimed or implied Google's product is self-serve before this pass |
| R13-10 | The tracked run-in-progress capture shows a **Time remaining** estimate tile alongside the Activity Log; whether this product estimates remaining time at all needs checking against the run view | **BUILT** | Recorded, as the row's own residual asked for -- not built as a feature. `docs/PARITY.md`'s new `RUN-VIEW-ETA-001` row (`missing`, this wave, cites `corpus R13-10`) states the answer by name: the Activity Log half is already built and shipped (`app/frontend/src/workbench/pages/run_detail_activity_log.tsx`, `ActivityLog` component, covered by `run_detail.test.tsx`); the Time-remaining/ETA half does not exist anywhere in `app/frontend/src/workbench/` or `app/app/*.py` -- zero hits. Estimating remaining run time is deliberately not built here; it is a product feature with its own accuracy problems and is left to the owner |
| R13-12 (a) | A tracked JPG's filename (`esn-poma-hub-hypothesis-full-detail-with-diagram.jpg`) does not match its content (a Computational Discovery splash screen); any future row citing the filename would cite the wrong image | **BUILT** | Not renamed or moved (it lives under `references/`, which this pass does not touch) -- flagged instead. `docs/fidelity-audit/FINDINGS.md`'s "Corpus-integrity corrections" section now carries a dedicated note (this wave, cites `corpus R13-12(a)`) naming the filename, stating what it actually shows, and warning against citing it for a hypothesis-detail-view claim -- placed there rather than in the section's own "Claimed as Google / Reality" table, since a mislabeled asset is a different failure than a clone-authored document mis-describing a requirement |

**R13: 6 BUILT / 0 OPEN / 1 DECISION / 0 FALSE.**

Noticed in passing: none.

## R14 — the protein-assemblies run, read in full

| Row | Table says (`work`/`unclear`) | Verdict | Evidence |
|---|---|---|---|
| R14-1 | The published report opens with an explicit `#### Table of contents:` section, six nav items; our report has no navigation aid | **BUILT** | `app/app/report_markdown_toc.py` (new module) renders "#### Table of contents:" naming the report's own top-level sections; wired into `report_markdown.py:483` right after the title/provenance line, cited by name in its own docstring and in `report_markdown_header.py:11,83` |
| R14-2 | A third, structurally distinct goal-intake shape (8 parts, `Ground Truth Dataset`/`Your Role` fields neither other exemplar has); needs a decision on which shape, if any, is canonical before `MO-11`'s sink is actionable | **DECISION** | Confirmed unchanged: `app/app/runs_models.py:29` `research_goal: str` remains one free-text field, matching none of the three published shapes structurally. Same underlying question as `MO-11`/`R1-18`/`R10-9` — not double-counted separately |
| R14-3 | The same run's goal renders two different ways across its two report surfaces (raw-flattened vs. synthesized restatement); explicitly blocked on `R14-11` | **DECISION** | Confirmed unchanged: `report_markdown_header.py:34-54` (`_render_research_goal_details`) still renders exactly one `**Goal:** {research_goal}` line — neither published behavior. The row's own residual already names the blocker (`R14-11`, DECISION below); not resolvable independently |
| R14-4 | A second, longer "About" disclaimer exists on the research-overview report surface, textually distinct from the per-hypothesis one and from the provenance line; unclear whether this is a second required disclaimer or a variant of the same one | **DECISION** | The per-hypothesis half of this same wording is now built (see `R14-13`), but confirmed that text does not also appear anywhere at the *report* level: `grep -rn "experimental system for generating" app/app/*.py` returns only `report_markdown_hypothesis.py:25` (the per-hypothesis instance). Whether a report-level instance is separately needed stays contingent on `R14-11` (whether the two published report surfaces are ever built as two documents), same as `R14-3` |
| R14-6 | Published research contacts are grouped by research direction (4 groups), each with a shared rationale paragraph and up to two example hypothesis titles; `MO-7` only restored the flat per-contact tag | **BUILT** | `engine/src/co_scientist/schemas/synthesis.py:216-254` `research_contact_groups[]` (named by this row ID in its own code comment) carries `research_direction`, `rationale`, and `example_hypothesis_indices` (by 1-based position, never by echoing text — the AGENTS.md envelope-shape lesson applied on purpose); rendered via `_render_research_contacts_section` (`report_markdown_overview.py:311`); pinned by `app/tests/test_report_contact_groups.py` |
| R14-8 | "Best Next Steps" richer shape: time estimates, lettered sub-phases, a named winning-idea recommendation — beyond `R12-11`'s base finding | **BUILT** | `app/app/report_markdown_meta_review.py:30-88` (`_RecommendationFields`, `_normalize_recommendation`, `_render_recommendation`) adds `time_estimate`, `phase_label`, `recommended_idea` (by `hypothesis_index`, not text), each explicitly commented `# R14-8`; commit `a0c4a5ec` ("render the strategic roadmap's time estimate, phase, and idea (R14-8)") |
| R14-9 | The synthesized-criteria section has a table rendering (Criterion/Importance, 5 rows) distinct from MASH's prose paragraphs; decided-by claims "`R12-18` re-confirmed still fully absent" | **FALSE** | The central claim does not survive a read: `R12-18` is now **BUILT** (see the R12 section above) — `report_markdown_supervisor.py`'s `_render_evaluation_criteria_markdown` renders `critical_criteria` as bolded-name-plus-prose, tested by `app/tests/test_report_critical_criteria.py`. What the row's grep found (`runs_crud_resolve.py:83` never sets the interview-derived `setup.criteria` field) is true but is a different fact from "R12-18 is absent" — that row is about the Supervisor's *separately synthesized* `critical_criteria`, which does render. What survives as a genuine, narrower point: our rendering is prose (matching MASH), not the table format this row found in a second exemplar — that specific format choice remains unaddressed, worth a line on `REVIEW-SUMMARY`-adjacent format decisions rather than a full row of its own |
| R14-10 | The published ranking-report file is a compound document (report + an embedded full proposal + an embedded full review); whether this composition is exemplar-specific or a general Google shape cannot be settled from one run | **DECISION** | Confirmed unresolvable from this repo's evidence: the row's own residual is "`none` pending a second exemplar of a Google ranking report" — no second exemplar exists in the corpus, so this stays blocked on external evidence this repo cannot supply, not on an implementation choice |
| R14-11 | A single run produces two separately-purposed report documents (`research-overview.md`, meta-review-style; `top-ranking-hypotheses.md`, tournament-comparison-style); we emit one combined document | **DECISION** | Confirmed unchanged: `report_markdown.py:424-455` (`render_report_markdown`) still emits exactly one combined document. The row's own residual is explicit: "Needs a decision before any sink: split the report, or confirm one combined document is the intended local adaptation." Several other R14 rows (`R14-3`, `R14-4`, `R14-9`'s table-vs-prose point) are downstream of this same unresolved question |
| R14-12 | Every published title is `# **Co-scientist - <Title>**` — bold, H1, product-prefixed, an authored noun phrase, never a full sentence; needs a dedicated LLM-composed `title` field plus a prefix-convention decision | **BUILT** | **The content half now built on top of the prefix half.** A `title` field (`_TITLE_FIELD`, `schemas/generation.py`) rides the existing generation and evolution calls, shared by identity across `GENERATION_SCHEMA`, `HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA`, and `EVOLUTION_SCHEMA` — the same three call sites `_EXPERIMENT_FIELD` (R14-20) already backs — described as a compact noun phrase under 100 characters, no trailing period (commit `3d18b7cd`). `hypothesis_from_llm_output` and evolution's `_extract_evolution_fields` carry it onto `Hypothesis.title`; the app's `_authored_title` (`app/app/engine_adapter/drain_hypothesis_title.py`) is the single point where it is preferred over the pre-existing `first_sentence(text)`, which stays exactly as the sole fallback for a run predating this field or a `json_object` downgrade that omits/mistypes/empties it (commit `3fc45294`). `report_markdown_hypothesis.py:143-153`'s bold/product-prefixed rendering (commit `9521f16a`) now wraps an authored name rather than a truncated sentence -- exercised end-to-end through a real `HypothesisGenerator` run on the offline backend (generation and evolution both) and the drain/report path, e.g. the actually-rendered `### 1. **Co-Scientist - Autophagy as a rate-limiting constraint on disease (1)**` (the trailing `(1)` is the offline filler's own ordinal suffix, not a schema artifact). |
| R14-13 | Every hypothesis carries a byte-identical one-line "About" disclaimer under its title | **BUILT** | `app/app/report_markdown_hypothesis.py:20-27` `_HYPOTHESIS_DISCLAIMER`, word-for-word the published text, explicitly cited to `R14-13` in its own comment, unconditionally rendered for every entry (`:150`) |
| R14-14 | Where populated, published `Reviews summary` is an 8-part numbered structure or a simpler two-list form — a structured schema is needed, or the divergence should be accepted and recorded | **BUILT** | The decision this row asked for has been made and recorded: `docs/PARITY.md:230` `REVIEW-SUMMARY-STRUCTURE-001` (`missing`, citing this row by ID) measured Google's own inconsistency (8/19 eight-part, 3/19 two-list, 8/19 empty) and deliberately did not impose either shape, with reasoning — "mandating either shape... would make this system's output *more* rigid than the published one it is modeling." Recording, not code, was always this row's second acceptable outcome |
| R14-15 | Within the 8-part summary, a bolded free-text Go/No-Go `**Verdict:**` and a `**Time to Verdict:**` timeframe field | **BUILT** | `engine/src/co_scientist/schemas/review.py:440-458` — `go_no_go_recommendation` and `time_to_verdict`, matching the row's own example wording almost verbatim ("Go — pursue wet-lab validation" / "'Short', '2-4 weeks', or '2-3 months'"), both optional to match Google's own 8/19 partial coverage; rendered by `report_markdown_hypothesis.py:219` (`_render_hypothesis_verdict`) |
| R14-16 | `Justification:` is a consistent first field (14/14) in per-hypothesis research contacts; the evidence-citing second field's label varies freely; whether to pin two named fields or keep one free-text field is an owner call | **DECISION** | Confirmed unchanged: `report_markdown_overview.py:319-336` still renders `### {contact name}` plus one evidence line. The row explicitly frames its own residual as "Owner call" — unresolved by design, not by omission |
| R14-17 | The Appendix's `All reviews:` block is always Correctness→Novelty→Feasibility→Impact potential, each with its own fixed, differently-sized sub-schema; record as an accepted divergence or add sub-structure | **BUILT** | Same pattern as `R14-14`: `docs/PARITY.md:231` `REVIEW-AXIS-STRUCTURE-001` (`partial`, citing `R14-17` by name) both *acted* (axis ordering in `schemas/review.py`'s `_SCORE_CRITERIA` now matches Correctness-first) and *recorded* the sub-structure decision, with two measured cost scenarios (41-67% more input tokens, 62-205% more output tokens) rather than assuming one. Commit `37c999a2`; pinned by `engine/tests/test_schemas.py::test_review_score_axes_are_correctness_first` |
| R14-20 | `Steps to Test the Idea` is a numbered pilot-then-scale-up plan ending in an explicit `**Go:**`/`**No-Go:**` pass/fail threshold; ours is one free-text paragraph | **BUILT** | `engine/src/co_scientist/schemas/generation.py:84-121` `_EXPERIMENT_FIELD` now structures exactly this shape — numbered steps ending in a Go/No-Go step with explicit pass/fail thresholds — commit `9a4fd222` ("structure the experiment field as a Go/No-Go pilot plan"); rendered by `app/app/report_markdown_hypothesis.py:108-125` (`_render_hypothesis_experiment`, "#### Steps to test the idea"), commit `8bb19ade` |
| R14-21 | Two per-hypothesis bibliography forms exist; extends `R12-19` with per-hypothesis evidence that "neither the Generation-side nor Reflection-side citation list renders anywhere," backed by "`grep -rn 'citation_map' app/app/report_markdown*.py` — zero hits" | **FALSE** | The grep result the row states does not reproduce: running the identical command today returns a hit at `app/app/report_markdown_references.py:8` (its own module docstring, naming `citation_map` directly), and that module is a full working renderer — same finding as `R12-19` above, now doubly confirmed. `report_markdown_references.py` resolves each hypothesis's `citation_map` into a rendered References list, wired at `report_markdown.py:343`, pinned by `app/tests/test_report_markdown_references.py` |
| R14-22 | Where populated, `Deep verification:` is a numbered list of simulated-protocol flaws; original reading said nothing renders it, corrected in-row to say the real gap is that `simulation_review`'s `failure_points`/`decisive_step` (the field that actually matches this shape) has no renderer | **BUILT** | `app/app/report_markdown_hypothesis.py:182-216` (`_render_hypothesis_simulation_review`) renders `simulation_review.failure_points` as a numbered flaw list plus a `**Decisive step:**` line, wired at `:307`; commit `16ebdce2` ("tighten the ledger note and add an end-to-end render test") |
| R14-24 | Corrects an earlier reading: the 11-vs-8 Deep-verification-populated split is not truncation, verified section-by-section against three files; a footnote is needed wherever the wrong file-length framing might be cited | **BUILT** | The correction is the row itself, positioned exactly where a reader would encounter the original claim — its own "Decided by" column states the correction in full, with the three-file verification recorded inline, satisfying the row's own ask ("a footnote here correcting the file-length framing") |
| R14-26 | The canonical top-level section sequence of a published hypothesis document is fixed (14 sections in a stated order); we have no per-hypothesis document assembly matching it, conditional on the owner wanting a fuller per-idea artifact | **DECISION** | Confirmed unchanged: `_render_hypothesis_entry` (`report_markdown.py:285-321`) still renders one flat entry, not a 14-section document in this order. The row's own framing is conditional ("if the owner wants a fuller per-idea artifact") — a build-or-not decision, not a pure implementation gap |

**R14: 11 BUILT / 0 OPEN / 7 DECISION / 2 FALSE.**

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
| MO-4 | Published per-assumption wording is prose (`Plausible:`, `Plausible, but requires careful investigation:`, `Unknown:`); the enum-disagreement half is closed (one shared `ASSUMPTION_SUPPORT_VALUES` enum), but adopting the published wording is deferred | **DECISION** | Confirmed unchanged: `engine/src/co_scientist/schemas/review.py:20-25` `ASSUMPTION_SUPPORT_VALUES = (supported, uncertain, likely_false)`, still not the published prose labels. Same question as `R12-15` (audited above) — not double-counted |
| MO-5 | Two appended reviews close with a bare `Answer: 4`/`Answer: 3`; whether the scale is 1-5, 1-10, or something else (a separate reading found values 2-9 for a different block) is unresolved | **DECISION** | Same open scale question as `R10-7` (audited above), which this row explicitly narrows. Re-confirmed: every `Answer: N` value in the verbatim Appendix is 3 or 4 (consistent with either scale, not dispositive); the wider 2-9 range this row cites cannot be independently verified — it is not mirrored anywhere in `docs/CORPUS-EXTRACTION.md`'s Appendix, and this document cannot read `references/` directly. Not double-counted against `R10-7` |
| MO-11 | The research goal is intake as three named parts (`Title`, `Goal`, `Background`); ours is one free-text field | **DECISION** | Same underlying question as `R1-18`/`R10-9`/`R14-2` (audited above): `app/app/runs_models.py:29` `research_goal: str` remains one field. Not double-counted — one decision (canonical goal-intake shape) closes all four rows |
| MO-12 | Two published overviews use different vocabularies for the same slot; the ALS third slot (`recent_findings`) is now closed, but both exemplars also use a **doubled structure** (a brief preview list, then full detail) that a single array still cannot express | **BUILT** | Achieved in the renderer alone, no new model output or schema change. `app/app/report_markdown_overview.py::_render_directions_preview` front-loads a named preview list (`- {title}` per direction, reusing the existing required `title` field) ahead of the unchanged full per-direction detail (`_render_directions_list`), mirroring both exemplars' cadence ("We will be focusing on these interrelated areas" / "Main Research Directions" before their per-direction sections). Gated to 2+ named directions -- a preview of one entry would duplicate it rather than orient the reader, per this wave's own caution against a preview that repeats rather than names. Malformed/untitled directions are dropped from the count the same way the existing per-direction renderer already tolerates them. Pinned by three new tests in `app/tests/test_report_markdown_overview.py`: `test_two_or_more_directions_get_a_preview_list` (preview text precedes the first `### {title}` detail heading), `test_a_single_direction_gets_no_preview_list`, `test_an_untitled_direction_is_dropped_from_the_preview_count` |

**MO: 2 BUILT / 0 OPEN / 3 DECISION / 0 FALSE.**

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

The 18 DECISION verdicts above collapse to fewer questions once rows
asking the same thing are merged:

1. **Goal-intake shape and the three glossary terms.** `R1-18`, `R10-9`,
   `R14-2`, `MO-11` (4 rows, 1 question). `app/app/runs_models.py:29`
   `research_goal: str` is one free-text field; the corpus shows at least
   three different published shapes (SSR §11's flat glossary; A.1's
   `Title`/`Goal`/`Background` triple; the protein-assemblies run's 8-part
   form with `Ground Truth Dataset`/`Your Role`). Is any one canonical, and
   should "novel repurposing candidate" / "novel target" / "novel
   mechanistic explanation" be a controlled vocabulary anywhere in the
   schema?
2. **Per-assumption wording.** `R12-15`, `MO-4` (2 rows, 1 question). One
   shared `ASSUMPTION_SUPPORT_VALUES` enum already replaced two drifting
   enums; should its values render as the published prose (`Plausible:` /
   `Plausible, but requires careful investigation:` / `Unknown:`) instead
   of `supported`/`uncertain`/`likely_false`?
3. **The bare `Answer: N` review-score scale.** `R10-7`, `MO-5` (2 rows, 1
   question). Every occurrence in the verbatim Appendix is 3 or 4,
   consistent with either a 1-5 or 1-10 scale; a separately-cited reading
   of a different block finds values 2-9, not itself in this repo's
   Appendix and unverifiable from here. Distinct from
   `EVAL-REVIEW-SCALE-001` (Figure A.23's named "co-scientist review
   score," already settled at 1-5) — this is a different, still-open
   score.
4. **Split the report into two documents.** `R14-11`, with `R14-3` and
   `R14-4` explicitly blocked on it (3 rows, 1 question). Google's one
   fully-read run produces `research-overview.md` and
   `top-ranking-hypotheses.md` as separate documents, with separately-
   shaped goal rendering and disclaimers on each; this product emits one
   combined document. Keep one document (accept the divergence), or build
   two?
5. **A flat bibliography list.** `R12-12`. The published report's
   3,259-entry `References` list has no analogue; `Citation audit` and the
   data-sources view are a different artifact. Add one, or accept the
   divergence?
6. **Named `Justification:`-plus-evidence contact fields.** `R14-16`. The
   `Justification:` label is consistent across all 14 published research
   contacts; the second, evidence-citing field's label varies freely. Pin
   two named fields, or keep the current single free-text field?
7. **A 14-section per-hypothesis document.** `R14-26`, explicitly
   conditional ("if the owner wants a fuller per-idea artifact"). Build it,
   or treat the flat entry as the intended local shape?
8. **Archive or extract the two gitignored mp4s.** `R13-1`. Unrecoverable
   once `references/` is deleted; archive outside the repo, or extract and
   commit the cited frames first?
9. **PubMed's disclosure status.** `R9-4`. Google names ChEMBL and UniProt
   as confirmed integrations but never confirms PubMed or arXiv, though
   PubMed is this repo's primary retrieval path. Record that as a labelled
   local (CLONE) choice on `TOOLS-CONFIG-001`, or leave it as an implicit
   claim?
10. **Not an owner decision — blocked on unavailable evidence.** `R14-10`.
    Whether the published ranking-report's compound structure (report +
    embedded full proposal + embedded full review) is exemplar-specific or
    a general shape cannot be settled without a second published exemplar,
    which does not exist in the corpus. Nothing inside this repo closes
    it.
11. **Cosmetic, only if the owner wants it.** `R12-13`. The published
    report's "Top ideas" heading appears twice; may be a transcription
    artifact. The row's own framing: "none unless the owner wants it."

---

## Residuals inside BUILT/FALSE rows

Four points are folded into a BUILT or FALSE verdict above rather than
carrying their own row; listed here so a future pass does not have to
re-read every evidence cell to find them.

- **`R12-17` / `R12-18` / `R12-23` have no `docs/PARITY.md` row.** All
  three are genuinely BUILT — `app/app/report_markdown_supervisor.py`,
  pinned by four app tests — but nothing in `docs/PARITY.md` cites that
  module (zero hits for "stratification", "evaluation criteria", "review
  summary", or `critical_criteria`, checked directly). Needs one or three
  ledger rows, not more code.
- **`R12-23`'s `Research directions` half is still open.** The row bundled
  two asks; only `Review summary` was built. A restated-directions-plus-
  `Unexpected Research Directions` block is unaddressed.
- **`R14-9`'s table-vs-prose format point survives its FALSE verdict.**
  The row's central claim ("`R12-18` still absent") is false, but its
  narrower observation — a second published exemplar renders synthesized
  criteria as a table, this product always renders prose — is real and
  unresolved.
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

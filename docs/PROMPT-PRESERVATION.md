# Prompt Preservation Audit

Wave `R8-2` of the fidelity campaign (branch `fix/published-prompt-fidelity`,
starting at HEAD `02278d2f`). Report date: 2026-09-01.
**Rows updated 2026-09-06** to the state after the verbatim rewrite; see the
standard note immediately below.

**The standard changed on 2026-09-06.** This audit was run against a "reworded
is fine — a mirror need not be byte-identical" standard. That standard is
retired: each of the eight published prompts now renders **word for word, in
published order**, through the real builders, and a paraphrase of published
text is a defect rather than a pass. The rows below have been updated to the
post-rewrite state; where a row's original judgment was overtaken by that
rewrite, the row says so rather than being deleted, because the reasoning is
what makes the later decision legible. The machine check is
`engine/tests/test_published_prompt_fidelity.py`; the per-template account of
what remains ours, and why, is
`engine/src/co_scientist/prompts/templates/README.md`.

**What this document is not.** `docs/CORPUS-EXTRACTION.md`'s `MP-*` rows
record *whether we mapped* each published prompt to a template and whether a
handful of specific findings (missing goal, missing preferences, the reversed
scores instruction) were fixed. Nobody checked that the mapping itself
*preserved the content* — every substantive instruction in the published
text, not just the ones a prior pass happened to notice. This document is
that check, run once against each of the eight published prompts in
`docs/CORPUS-EXTRACTION.md` Appendix A (line 952 on), in the order they
appear there.

**Method.** For each published prompt: identify the corresponding template
from `engine/src/co_scientist/prompts/templates/README.md`, enumerate every
substantive instruction in the published text (a rule the model must follow,
a constraint, a stated output requirement, reasoning scaffolding, an explicit
prohibition — not placeholder syntax or pure formatting), and classify each
as **present** (reworded is fine — a mirror need not be byte-identical),
**missing**, or **deliberately adapted** (a documented, justified departure).
Evidence cites the current template line and/or the Python builder that
renders it.

**Standing rule.** `MP-1` through `MP-5` in `docs/CORPUS-EXTRACTION.md` are
closed and not re-litigated here. `MP-6` is recorded there as `work` but is
in fact already fixed on this branch (commit `245ced81`, pinned by
`test_judge_prompt_carries_scientist_preferences` in
`engine/tests/test_ranking_debate.py`) — noted below where it's relevant,
not re-opened. `MP-7` was open at the time of this audit and was audited on
the same footing as every other instruction in this pass; it is now closed,
the published four imperatives rendering verbatim on `evolution_feasibility.md`
and `evolution_out_of_box.md`.

**`MP-8` was closed the other way round on 2026-09-06.** This audit worked
from the earlier decision that `INSPIRATION` was A.7's structural match and
the enum named `OUT_OF_BOX` a different, clone-authored strategy. The
resolution moved the content to the name instead: `OUT_OF_BOX` now joins
`_PARTNER_OPERATORS` (`evolve.py`), so it receives the top-ranked peers that
are A.7's published `{hypotheses}` input, and it renders
`evolution_out_of_box.md`. `INSPIRATION` keeps the paper's separately
disclosed "inspiration from existing hypotheses" strategy on `evolution.md`
and is **no longer claimed as a counterpart to any published prompt**. No enum
value moved, so every persisted `"out_of_box"` lineage record stays valid.
Pinned by `test_out_of_box_task_draws_partners_from_the_ranked_pool` in
`engine/tests/test_evolution_operators.py`.

---

## Summary (filled in as each prompt is audited; final tally at the end)

| # | Published prompt | Template(s) | Present | Missing | Adapted |
|---|---|---|---|---|---|
| 1 | `evolution-06-feasibility-improvement.md` | `evolution_feasibility.md` (`COHERENCE_FEASIBILITY` operator) | 5 | 0 | 0 |
| 2 | `evolution-07-out-of-the-box-thinking.md` | `evolution_out_of_box.md` (`OUT_OF_BOX` operator, MP-8) | 6 | 0 | 0 |
| 3 | `generation-01-hypothesis-after-literature-review.md` | `generation_draft_with_tools.md` (primary); `generation_debate_and_literature.md` (literature block) | 9 | 0 | 0 |
| 4 | `generation-02-hypothesis-after-scientific-debate.md` | `generation_debate_and_literature.md`, `generation_after_debate.md` | 14 | 0 | 0 |
| 5 | `meta-review-08-meta-review-generation.md` | `meta_review.md` | 7 | 0 | 0 |
| 6 | `ranking-04-pairwise-comparison.md` | `ranking_pairwise.md` | 8 | 0 | 0 |
| 7 | `ranking-05-comparison-via-scientific-debate.md` | `ranking_debate.md` + `agents/ranking/ranking_debate*.py` | 9 | 0 | 0 |
| 8 | `reflection-03-generate-observations.md` | `reflection_observations.md` | 8 | 0 | 1 |

---

## 1. `evolution-06-feasibility-improvement.md`

**Template:** `evolution_feasibility.md`, the whole published prompt, rendered
for the `COHERENCE_FEASIBILITY` operator only
(`evolution_operators.py::operator_template`). Before 2026-09-06 this operator
rendered the shared `evolution.md` with a paraphrased operator instruction; the
paraphrase is deleted, and `test_every_operator_is_briefed_exactly_once` now
forbids an operator carrying both a published template and an `_INSTRUCTIONS`
entry.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Refine the provided conceptual idea, enhancing its practical implementability by leveraging contemporary technological capabilities" | present, verbatim | the template's role sentence |
| 2 | "Ensure the revised concept retains its novelty, logical coherence, and specific articulation" | present, verbatim | same sentence |
| 3 | `Goal: {goal}` | present (MP-2, `done`) | `evolve_prompt.py` sets `research_goal` unconditionally; the published `Goal:` label |
| 4 | `Evaluation Criteria: {preferences}` | present (MP-3, `done`) | `evolve_prompt.py` sets `preferences`; the published `Evaluation Criteria:` label |
| 5 | **Reasoning scaffold**: (1) introductory overview of the relevant scientific domain, (2) concise synopsis of recent pertinent research and successful precedents, (3) reasoned argument for how current technological advances enable the concept, (4) CORE CONTRIBUTION — a detailed, innovative, technologically viable alternative, emphasizing simplicity and practicality | present, verbatim (`MP-7` closed) | the published `Guidelines:` block, carried as the four imperatives rather than the paraphrase the "Recommendation" below proposed. Pinned by `test_feasibility_prompt_carries_the_published_guidelines` in `engine/tests/test_evolution_operators.py` |

**5 present / 0 missing / 0 adapted.**

## 2. `evolution-07-out-of-the-box-thinking.md`

**Template:** `evolution_out_of_box.md`, the whole published prompt, rendered
for the `OUT_OF_BOX` operator. This reverses the mapping this audit worked
from: per the 2026-09-06 `MP-8` resolution (see "Standing rule" above),
`OUT_OF_BOX` now receives A.7's `{hypotheses}` input and renders A.7's prompt,
and `INSPIRATION` is no longer claimed as a counterpart to any published
prompt.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Generate a novel, singular hypothesis inspired by analogous elements from provided concepts" | present, verbatim | the template's role sentence |
| 2 | `Goal: {goal}` | present (MP-2, `done`) | the published `Goal:` label |
| 3 | `Criteria for a robust hypothesis: {preferences}` | present (MP-3, `done`) | the published label; `evolve_prompt.py` sets `preferences` for every operator |
| 4 | "Inspiration may be drawn from the following concepts (utilize analogy and inspiration, not direct replication): `{hypotheses}`" | present, verbatim | the published sentence over `{{partner_context}}`, whose `## Provided Concepts` header also carries the empty-pool fallback. The input itself is real since MP-8: `test_out_of_box_task_draws_partners_from_the_ranked_pool` drives `evolve._build_single_evolution_task`, the seam where an operator is granted or denied partners |
| 5 | "This should not be a mere aggregation of existing methods or entities. Think out-of-the-box." | present, verbatim (MP-5, `done`) | inside the published CORE HYPOTHESIS imperative, where the paper puts it; `evolution.md` keeps its own template-wide copy for the five clone-authored operators |
| 6 | **Reasoning scaffold**: (1) concise introduction to the relevant scientific domain, (2) summary of recent findings and successful approaches, (3) identify promising avenues for exploration, (4) CORE HYPOTHESIS — a detailed, original, specific hypothesis leveraging analogous principles | present, verbatim (`MP-7` closed) | the published `Instructions:` block. Pinned by `test_out_of_box_prompt_is_the_published_analogy_prompt` in `engine/tests/test_evolution_operators.py` |

**6 present / 0 missing / 0 adapted.**

### Judgment on the shared loss (both evolution-06 and evolution-07)

**Overtaken 2026-09-06 — the loss is restored, and not the way this section
recommended.** Both prompts now render whole on their own templates, so the
scaffold is the published four imperatives rather than a generic "reason in
this order" instruction, and it reaches the two operators the paper named
rather than all seven. The reasoning below is kept because it is why the
scaffold was judged restorable at all.

**What was dropped.** Both published prompts scaffold the model's reasoning
before it writes the answer: ground the domain, summarize what's recently
been tried, argue why now, *then* commit to the specific proposal. Our
`evolution.md` goes straight to "Refinement Approach" (six unordered
improvement axes: clarity, soundness, novelty, testability, safety,
simplification) and a four-field JSON schema (Hypothesis / Explanation /
Experiment / Refinement Summary) with no field that captures this
progression. The scaffold was reformatted into neither the prose nor the
schema — it was dropped.

**Call-site multiplicity.** One evolve call per parent hypothesis per
evolution round (`evolve.py`; operators are assigned one-per-parent by
`select_operators`, no per-candidate fan-out). Restoring the scaffold adds
text to an *existing* call's prompt — it does not add a new call, and does
not multiply by pool size beyond what evolution already costs today.

**Recommendation.** Genuine, restorable, low-risk: add an explicit
"reason in this order" instruction ahead of the output schema, applying to
every operator (the template is shared) rather than gating it to the two
operators the published prompts name — the domain-overview →
recent-findings → reasoned-argument → core-contribution order is generic
scaffolding, not specific to feasibility/inspiration content. Estimated
prompt-text delta: a short instruction block (roughly 350-450 characters,
~90-110 tokens), added once per evolve call. See Phase 2 below for what was
actually restored.

---

## 3. `generation-01-hypothesis-after-literature-review.md`

**Templates:** `generation_draft_with_tools.md` is the primary counterpart —
it is the node that drafts after a literature review, and since 2026-09-06 it
carries A.1's text verbatim rather than being a reconstruction of it.
`generation_debate_and_literature.md` also carries A.1's literature block,
under A.1's own published label.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "You are an expert tasked with formulating a novel and robust hypothesis to address the following objective." | present, verbatim | the opening line of `generation_draft_with_tools.md`; the invented "Hypothesis Drafting Agent - Phase 1" preamble that used to displace it is deleted |
| 2 | "Describe the proposed hypothesis in detail, including specific entities, mechanisms, and anticipated outcomes." | present, verbatim | published sentence 2, no longer only paraphrased into the JSON `hypothesis` field description |
| 3 | "This description is intended for an audience of domain experts." | present, verbatim | published sentence 3. The technical/lay field split is unchanged and is additive: the published sentence is now stated as well as implemented |
| 4 | "You have conducted a thorough review of relevant literature and developed a logical framework...The articles consulted, along with your analytical reasoning, are provided below" | present, verbatim | the published literature-framing pair, replacing the "The literature review node already analyzed papers…" paraphrase |
| 5 | `Goal: {goal}` | present | the published `Goal:` label over `{{goal}}` |
| 6 | `Criteria for a strong hypothesis: {preferences}` | present, verbatim label | replaces the invented `## Criteria for Strong Hypotheses` heading |
| 7 | "Existing hypothesis (if applicable): `{source_hypothesis}`" | present, verbatim label | over `{{user_hypotheses}}`; replaces `## User-Provided Starting Hypotheses` |
| 8 | `{instructions}` | present | `{{instructions}}`, both templates |
| 9 | "Literature review and analytical rationale (chronologically ordered, beginning with the most recent analysis):" | present, verbatim label | the label is carried whole, including the ordering promise the old `## Literature Review Context` heading dropped. `articles_with_reasoning` is a single synthesis (`literature_review/synthesis.py::_phase4_synthesize`) overwritten by each later review, i.e. always the run's most recent analysis, so the promise holds trivially for a list of one. **If this block is ever changed to accumulate analyses across cycles, they must be emitted most-recent-first or the published label becomes false.** |

**9 present / 0 missing / 0 adapted.** What remains ours on this template — the
agentic tool loop, the `[C*]` citation mechanic, the pool-sized draft request,
the novelty hedging, and the terminal output-format block — is listed with its
justification in `engine/src/co_scientist/prompts/templates/README.md`.

## 4. `generation-02-hypothesis-after-scientific-debate.md`

**Templates:** `generation_debate_and_literature.md` (with literature) and
`generation_after_debate.md` (without) — both README-derived from A.2 and
structurally near-identical to each other.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Expert participating in a collaborative discourse...simulated discussion with other experts" | present | Line 1 of both templates |
| 2 | `Goal: {goal}` | present | `{{goal}}` |
| 3 | `Criteria for a high-quality hypothesis: {preferences}` | present | `{{preferences}}` |
| 4 | `Instructions: {instructions}` | present | `{{supervisor_guidance}}` / `{{instructions}}` slots |
| 5 | `Review Overview: {reviews_overview}` | present, verbatim slot (2026-09-06) | The published label and a `{{reviews_overview}}` slot now render in both debate templates, filled by `prompts/generation_debate.py::_format_reviews_overview` from the run's meta-review synthesis of the previous cycle's reviews (`_common._format_meta_review_context`, unchanged). Iteration 1 says it has no reviews yet rather than leaving the published label over nothing. Same mechanism as before, under its published name — `docs/PARITY.md` `META-CRITIQUE-APPEND-001` |
| 6 | Initial contribution: "Propose three distinct hypotheses" | present, verbatim | the inserted word "novel" is deleted; `{{attributes}}` fills the published `{idea_attributes}` slot |
| 7 | Subsequent contributions: pose clarifying questions | present | both templates, Procedure section |
| 8 | Critically evaluate on: adherence to attributes, utility/practicality, level of detail/specificity | present | both templates, same three bullets verbatim in structure |
| 9 | Identify weaknesses/limitations | present | both templates |
| 10 | Propose concrete improvements | present | both templates |
| 11 | Conclude each turn with a refined iteration of the hypothesis | present | both templates |
| 12 | General guidelines: boldness/creativity, collaborative, prioritize quality | present | both templates, "General guidelines" section |
| 13 | Termination: "typically 3-5 turns, maximum of 10", conclude by writing "HYPOTHESIS" (caps) then a self-contained exposition | present | turn constants `_DEBATE_TYPICAL_MIN_TURNS=3` / `_DEBATE_TYPICAL_MAX_TURNS=5` / `_DEBATE_MAX_DISCUSSION_TURNS=10` (`prompts/generation_debate.py:279-303`), rendered into both templates' Termination condition section verbatim on the numbers |
| 14 | `#BEGIN TRANSCRIPT# {transcript} #END TRANSCRIPT#` | present | both templates, verbatim markers |

**14 present / 0 missing / 0 adapted** (item 5 counted once, applies to both).

**One deletion this audit did not ask for, made 2026-09-06.** Both templates
carried, inside the published `Procedure` list, "Out of the initial 3
hypotheses, filter out the worse 2 as the debate progresses…", and
`generation_after_debate.md` compounded it with "a refined iteration of **the
one final, best,** hypothesis" against the published "…of the hypothesis". The
published procedure converges on one finalized idea at *termination*; stating
the narrowing as a per-turn instruction turns a diversity mechanism into a
within-turn elimination — the failure family the root `CLAUDE.md` records under
"an early gate that never reverses decides the whole run". Pinned absent by
`test_debate_does_not_order_the_panel_to_discard_two_ideas`.

---

## 5. `meta-review-08-meta-review-generation.md`

**Template:** `meta_review.md`, rendered by `get_meta_review_prompt`
(`engine/src/co_scientist/prompts/planning.py:27-42`).

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Expert in scientific research and meta-analysis" | present, verbatim | the template's opening sentence; the `, ie insights,` and `of the research hypotheses,` insertions are deleted and "research goal" restored |
| 2 | "Synthesize a comprehensive meta-review of provided reviews pertaining to the research goal" | present, verbatim | same sentence |
| 3 | `Goal / Preferences / Additional instructions / Provided reviews` slots | present, verbatim labels | `{{research_goal}}`, `{{preferences}}` (MP-4, `done` — `planning.py`), `{{instructions}}`, `{{all_reviews}}`. `Provided reviews for meta-analysis:` replaces the invented `**Complete Review Histories and Ranking Debate Transcripts:**`, and each bolded local label is replaced by its published one |
| 4 | "Generate a structured meta-analysis report of the provided reviews" | present, verbatim | the published `Instructions:` block, now a real section rather than a substring of `Additional instructions:` |
| 5 | "Focus on identifying recurring critique points and common issues raised by reviewers" | present, verbatim | published bullet 2 |
| 6 | "Provide actionable insights for researchers developing future proposals" | present, verbatim | published bullet 3; the "Actionable Insights!" flourish is deleted |
| 7 | "Refrain from evaluating individual proposals or reviews; focus on producing a synthesized meta-analysis" | present, verbatim, and **last** | published bullet 4, immediately before `Response:`; it previously sat before every input |

**7 present / 0 missing / 0 adapted.** The template follows the published shape
end to end. The seven clone-authored `### N.` sections are gone as sections:
each is folded in as a sub-bullet under whichever published bullet it serves,
so every added instruction now names a schema field the model must fill rather
than competing with the published four.

**The one contradiction, reconciled rather than deleted.** Old section 6
(`### 6. Compare the candidate ideas against each other and against existing
solutions`) ordered exactly the per-proposal evaluation the published
`Refrain…` directive forbids. It has independent provenance in published
*outputs* (`docs/PARITY.md` `RANKING-CRITERIA-TABLE-001`,
`MAIN-RESEARCH-DIRECTIONS-001`), so both comparison objects are now sub-bullets
*under* the `Refrain…` bullet, introduced by a sentence framing them as
set-level synthesis: they position the reviewed pool on shared axes and carry
no verdict on any single proposal. Pinned by
`test_meta_review_does_not_order_per_proposal_evaluation`.

**One wrong slot corrected.** `{{domain_evolution_guidance}}` was a copy-paste
from `evolution.md` — visible in a real render as "Refinements should stay
implementable in an academic laboratory." on a node that reviews reviews. It is
re-wired to `{{domain_review_guidance}}`, the slot
`loading.py::_get_domain_variables` already exposes for this kind of node.

## 6. `ranking-04-pairwise-comparison.md`

**Template:** `ranking_pairwise.md`, rendered by `get_ranking_prompt`
(`engine/src/co_scientist/prompts/ranking.py`) for a lower-ranked, single-turn
comparison. Until 2026-09-06 A.4 and A.5 shared one `ranking.md`, which
conflated both published prompts; that file is deleted and each published
prompt now has its own template, selected by the matchup's turn budget in
`ranking_debate.py::judge_matchup`.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Expert evaluator...compare two hypotheses...determine which is superior based on the specified attributes" | present, verbatim | the template's opening sentence, replacing the invented "Tournament Judge Agent in the Co-Scientist framework" role. The paper's `{idea_attributes}` resolves onto the criteria block ("…based on the specified evaluation criteria below"), since nothing at the ranking seam carries a separate attributes list. Pinned by `test_single_shot_matchup_renders_the_published_single_evaluator` |
| 2 | "Concise rationale...concluding with the phrase 'better idea: <1 or 2>'" (the source's own noted inconsistency with "better hypothesis") | present, verbatim | published sentence 2; `_VERDICT_LINE_RE` in `agents/ranking/ranking_debate_turns.py` accepts both phrasings, resolving the source's own inconsistency rather than picking one arbitrarily |
| 3 | `Goal: {goal}` | present | the published `Goal:` label over `{{research_goal}}` |
| 4 | `Evaluation criteria: {preferences}` | present (MP-6, fixed on this branch though `docs/CORPUS-EXTRACTION.md` still shows `work` — see "Standing rule" above) | the published label carries two blocks: `_format_ranking_preferences` (always) then `_format_ranking_evaluation_criteria` (the scientist's criteria list, under a governing sub-label, when supplied). Pinned by `test_judge_prompt_carries_scientist_preferences` and `test_judge_prompt_carries_scientist_criteria` |
| 5 | "Considerations: `{notes}`" (a slot distinct from both `{preferences}` and the per-hypothesis `{review N}`) | present (2026-09-06) | the published label over the new `prompts/ranking.py::_format_ranking_notes`: domain context, domain review guidance, supervisor guidance, meta-review context and run setup/focus guidance, joined; a `_NO_NOTES` line when every block is empty, so the published label always has something under it |
| 6 | "Each hypothesis includes an independent review. These reviews may contain numerical scores. Disregard these scores...not directly comparable across reviews" | present, verbatim (MP-1, `done`) | now static template text rather than builder output, so it renders even when neither side has a review. Pinned by `test_ranking_does_not_tell_the_judge_to_consider_the_scores` |
| 7 | `Hypothesis 1 / Hypothesis 2 / Review of hypothesis 1 / Review of hypothesis 2` | present, verbatim labels | each hypothesis gets its own review slot, as the published prompt does, filled by `prompts/ranking_sides.py::format_side_review`; the shared two-sided `## Review Scores Context` block is gone |
| 8 | "Reasoning and conclusion (end with 'better hypothesis: <1 or 2>')" | present | the published answer cue, see item 2 |

**8 present / 0 missing / 0 adapted.**

**The "Considerations: `{notes}`" slot, reconsidered.** This audit recorded it
as a real gap but recommended against restoring it, on the reasoning that the
paper gives the slot no content of its own and three overlapping channels
(`evaluation_criteria`, `preferences`, `supervisor_guidance`) already reached
the judge. The 2026-09-06 rewrite restored it anyway, and the reasoning
inverts cleanly: those three channels were already rendering, under invented
headings of our own. Relabelling them onto the published slot is not padding —
it is the published prompt's one slot for "everything else" being used for
exactly that, and it removed three invented headings rather than adding a
field.

**Deleted from this prompt in the same pass**, with no published counterpart:
the pasted paper prose describing the Elo tournament (architecture-section
text, citation marker included, sent to the judge as if it were an
instruction); the invented `## Comparison Criteria` items 1-7; and the
`## Your Task` / `## Input` / `## Reflection Notes` wrapper headings around
inputs the published prompt labels itself.

---

## 7. `ranking-05-comparison-via-scientific-debate.md`

**Template:** `ranking_debate.md`, A.5's own template since 2026-09-06,
rendered on **every** turn of a multi-turn matchup — turn 1 included — plus the
debate machinery in `agents/ranking/ranking_debate.py` /
`ranking_debate_turns.py`. Previously A.5 shared `ranking.md` with A.4, which
meant A.5's panel framing reached single-shot comparisons that are not debates,
and A.5's debate procedure reached no turn at all.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Panel of domain experts...structured discussion to evaluate two competing hypotheses" | present, verbatim | the template's opening sentences, on every turn of a debate matchup. Pinned by `test_matchup_prompt_frames_the_judge_as_a_panel` |
| 2 | "Rigorously determine which hypothesis is superior based on a predefined set of attributes and criteria" | present, verbatim | published sentence 2 |
| 3 | "The experts possess no pre-existing biases toward either hypothesis" | present, verbatim, **and** structurally enforced | the published sentence now renders. The structural countermeasure is unchanged and remains the stronger half: every matchup is judged in both A/B presentation orders (`_render_ordered_prompt` with `swapped=True`) and a position-balanced fallback (`_balanced_invalid_fallback`) resolves malformed output |
| 4 | `Goal / Criteria for hypothesis superiority ({preferences}) / Hypothesis 1,2 / Initial review of hypothesis 1,2` | present, verbatim labels | `{{research_goal}}`, the two-block criteria slot (MP-6), the two hypothesis slots, and a per-side review slot each (`ranking_sides.py::format_side_review`) |
| 5 | Debate procedure: "typically ranging from 3 to 5, with a maximum of 10" turns | present, verbatim | the template states the envelope the loop enforces; `test_ranking_prompt.py::test_debate_template_states_the_envelope_the_loop_enforces` asserts both published sentences against `_RANKING_DEBATE_TYPICAL_MIN_TURNS` / `_TYPICAL_MAX_TURNS` / `_MAX_TURNS`, so prose and behaviour cannot drift. `_append_debate_context` still restates it on turn ≥ 2, aimed at the transcript above it |
| 6 | "Turn 1: begin with a concise summary of both hypotheses and their respective initial reviews" | present, verbatim (2026-09-06) | the published `Turn 1:` bullet, which now reaches turn 1 because the debate template renders from turn 1 |
| 7 | Subsequent turns: evaluate on correctness/validity, utility/practicality, sufficiency of detail, novelty/originality, desirability for implementation; identify weaknesses/limitations/flaws | present, verbatim | the published five aspects, which also replaced the seven invented comparison criteria in `RANKING_SCHEMA` — `correctness_comparison`, `utility_comparison`, `detail_comparison`, `novelty_comparison`, `desirability_comparison` |
| 8 | "Additional notes: `{notes}`" | present (2026-09-06) | the published label over `_format_ranking_notes`; see ranking-04 item 5 |
| 9 | Termination: "provide a conclusive judgment...state the rationale...write 'better idea: ' followed by '1' or '2'" | present, verbatim | the published termination bullet; `_VERDICT_LINE_RE` parses the line, `_append_debate_context`'s "confirm that verdict decisively" carries it into follow-up turns |

**9 present / 0 missing / 0 adapted.** The "Turn 1 begins with a summary" gap
this audit judged not worth restoring was restored anyway, as a consequence of
the template split rather than as a separate decision: once A.5 has its own
template, its whole procedure renders, and omitting one bullet of it would be
the exception needing an argument.

**What the split added that the published prompt does not have.** One sentence
requiring a complete JSON verdict on every turn, turn 1 included ("an earlier
turn's verdict is provisional; the last turn's is the conclusive judgment"):
published A.5 is one conversation judged at termination, ours is one call per
turn, each parsed. Without it a turn-1 answer that obeys the published text
literally — summary only, no judgment — yields no verdict line and no `winner`,
and resolves through the position-balanced fallback flagged
`invalid_output_fallback`. Pinned, together with the decisive-verdict
instruction, by
`test_panel_framing_does_not_dislodge_the_decisive_verdict_instruction`. A.4's
scores caveat is also carried here, because our review blocks contain numerical
scores A.5's own prompt never anticipated.

**Correction (corpus R8-4, docs/CORPUS-STATUS.md):** item 7's "present"
classification bundles the five evaluation dimensions and the
weakness-identification instruction, but does not cover the "Subsequent
turns" guidance's own first bullet — "Pose clarifying questions to
address any ambiguities or uncertainties" — which this table missed and
which was then genuinely absent from `ranking.md`/`ranking_debate*.py`.
Deliberately not restored: `_append_debate_context`
(`ranking_debate_turns.py`) records the reasoning and the measured risk
at the code site.

**Resolved 2026-09-03:** the owner's governing directive for this
campaign — where Google published an exact prompt, mirror it — now
settles the question `_append_debate_context`'s docstring recorded.
The bullet is added verbatim as the lead sentence of that function's
per-turn guidance, pinned by `engine/tests/test_ranking_debate.py::test_followup_turns_pose_clarifying_questions`
(corpus R8-4, `docs/CORPUS-STATUS.md`; `docs/PARITY.md`
`RANK-DEBATE-CLARIFY-001`). Item 7 above is now fully present, not
bundled-and-incomplete. **Since 2026-09-06 the bullet also renders on turn 1**,
as part of A.5's own `Subsequent turns:` block inside `ranking_debate.md`;
`_append_debate_context` still leads its per-turn paragraph with it on turn ≥ 2,
aimed at the transcript above it, which is the position `RANK-DEBATE-CLARIFY-001`
pins.

## 8. `reflection-03-generate-observations.md`

**Template:** `reflection_observations.md`.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Determine if the hypothesis provides a novel causal explanation for the observations, or if they contradict it" | present | `reflection_observations.md:5` |
| 2 | Step 1, Observation extraction: list relevant observations from the article | present | `reflection_observations.md:9` |
| 3 | Step 2, Causal analysis (individual): state established cause, assess whether the hypothesis is a causal factor, prefix "would we see this observation if the hypothesis was true:", say "not a missing piece" where a better explanation exists | present, verbatim (**reverted 2026-09-06**) | The rewording this row justified — "specifically and uniquely explains this observation beyond established mechanisms", and a prefix carrying ", and not otherwise:" — is deleted, along with the "established mechanisms" rewordings of steps 2a, 2b and 2d. The published wording stands. Pinned by `test_observation_start_phrase_is_not_narrowed` |
| 4 | Step 3, Causal analysis (summary): novel explanation for a subset of observations, prefix "would we see some of the observations if the hypothesis was true:" | present, verbatim (**reverted 2026-09-06**) | Our replacement literal, "taken as a whole, does the hypothesis explain observations that known mechanisms cannot:", is deleted. Pinned by `test_summary_start_phrase_is_not_replaced` |
| 5 | Step 4, Disproof analysis: prefix "does some observations disprove the hypothesis:" | present, verbatim prefix | unchanged |
| 6 | Step 5/6, Conclusion: `"hypothesis: <already explained, other explanations more likely, missing piece, neutral, or disproved>"` | present, verbatim vocabulary | the published `Conclusion:` step, and the `Response:` line. The published step list is exactly five steps again: our invented `Positive observations:` step, which renumbered the published conclusion step to 6, moved into the output block |
| 7 | Scoring vocabulary: the five categories with their definitions | present, verbatim (**reverted 2026-09-06**) | the five expanded 1-3 sentence definitions and the expanded "neutral vs missing piece" paragraph are deleted; the published definitions stand |
| 8 | "If observations are expected regardless of the hypothesis, and don't disprove it, it's neutral" | present, verbatim | the published `Important:` sentence, with one calibration sentence appended after it (not replacing it): "Reserve 'missing piece' for a concrete explanatory gap that the established mechanisms in the literature leave open; theoretical consistency alone is not one." That sentence is the surviving trace of the evidence-gap fix items 3, 4 and 7 used to carry |
| 9 | `Article: {article}` — the published prompt runs **once per article** | **adapted (structural)** | Ours runs once per hypothesis over the whole retrieved corpus. One call per article multiplies provider calls by corpus size, per hypothesis, per cycle — the per-item-LLM-pass failure the root `CLAUDE.md` records, against a free chain capped near 100 requests/day per model. The published `Article:` label is kept verbatim and the fan-out stated in the same line: "each analysis below is one article from the literature review… Run steps 1 and 2 for every article in turn, then steps 3 to 5 once across all of them." The published singular is kept because the fidelity contract admits no paraphrase; the batching line is what disambiguates it |

**8 present / 0 missing / 1 adapted.** The tightening this audit classified as
"a deliberate strengthening, not a loss" was the campaign's clearest case of a
paraphrase drifting into a different instruction: two of the three altered
literals are *mandated start phrases* the model is told to write, and the
altered version asked a different question. Both are reverted; the production
fix they carried survives as the single calibration sentence in item 8. The one
structural addition — "Positive observations" (list confirmed strengths), a
live feature owned by `agents/reflection/observation_feedback.py` — is kept,
moved out of the numbered steps and into the output block.

---

## Overall summary

| # | Published prompt | Template(s) | Present | Missing | Adapted |
|---|---|---|---|---|---|
| 1 | `evolution-06-feasibility-improvement.md` | `evolution_feasibility.md` (`COHERENCE_FEASIBILITY`) | 5 | 0 | 0 |
| 2 | `evolution-07-out-of-the-box-thinking.md` | `evolution_out_of_box.md` (`OUT_OF_BOX`) | 6 | 0 | 0 |
| 3 | `generation-01-hypothesis-after-literature-review.md` | `generation_draft_with_tools.md`, `generation_debate_and_literature.md` | 9 | 0 | 0 |
| 4 | `generation-02-hypothesis-after-scientific-debate.md` | `generation_debate_and_literature.md`, `generation_after_debate.md` | 14 | 0 | 0 |
| 5 | `meta-review-08-meta-review-generation.md` | `meta_review.md` | 7 | 0 | 0 |
| 6 | `ranking-04-pairwise-comparison.md` | `ranking_pairwise.md` | 8 | 0 | 0 |
| 7 | `ranking-05-comparison-via-scientific-debate.md` | `ranking_debate.md` + debate machinery | 9 | 0 | 0 |
| 8 | `reflection-03-generate-observations.md` | `reflection_observations.md` | 8 | 0 | 1 |
| | **Total** | | **66** | **0** | **1** |

**Bottom line, restated after the 2026-09-06 rewrite.** All 67 identified
substantive instructions are present, 66 of them **verbatim and in published
order**, with one structural adaptation: A.3 is batched over the run's corpus
instead of called once per article, for the cost reason recorded in its own
row.

The original bottom line — "54 of 65 present, mostly reworded; only 5 genuine
gaps" — was true against the standard of the day and is the reason this
document exists, but it undercounted the problem twice over. A prompt measured
against the *template file* rather than the rendered prompt cannot see text that
lives in a builder or a slot that renders nothing; and "reworded is fine" scored
as present two mandated start phrases whose rewording asked the model a
different question. Re-measured against the rendered prompt with paraphrase
disallowed, the eight opened at **93 absent fragments, 3 contradicted, 3
reordered**, and now stand at **0 / 0 / 0**
(`engine/tests/test_published_prompt_fidelity.py`; before/after counts recorded
in `docs/CORPUS-EXTRACTION.md`'s R8 section).

---

## Phase 2 — fixes

**Superseded 2026-09-06.** All three items below are now closed, and the
`MP-7` restoration took a different shape than the one recorded here: the
`## Reasoning Order` section stays in `evolution.md` for the five
clone-authored operators, but `COHERENCE_FEASIBILITY` and `OUT_OF_BOX` no
longer render that template at all — each carries the published imperatives in
the published words on its own template. The two "left for the owner" items
are both built (the `{notes}` slot on both ranking templates; A.5's Turn 1
summary, which follows from A.5 having its own template). The record below is
kept for the token-cost and call-multiplicity measurements, which still hold.

**One restoration: `MP-7`'s reasoning scaffold.** Both evolution-06 and
evolution-07 scaffold the model's reasoning before it writes the answer
(domain overview → recent-research synopsis → reasoned argument for
viability → core contribution); `evolution.md` went straight from a list of
improvement axes to the JSON schema with no equivalent. Added a
`## Reasoning Order` section to `templates/evolution.md` (between
"Refinement Approach" and "Novelty Language"), applied template-wide — to
every operator, not only `COHERENCE_FEASIBILITY` and `INSPIRATION` — for the
same reason `evolution.md`'s existing MP-5 guard is template-wide: the
ordering is generic scaffolding (ground the domain, then the literature,
then the argument, then commit), not content specific to feasibility or
inspiration.

- **Diff:** `engine/src/co_scientist/prompts/templates/evolution.md` — 11
  lines added, no existing line changed.
- **Measured token delta:** 623 characters, **126 tokens** (`tiktoken`
  `cl100k_base`), added once to every rendered evolution prompt.
- **Call-site multiplicity:** one evolve call per parent hypothesis per
  evolution round (`agents/evolution/evolve.py`; `select_operators` assigns
  one operator per parent, no per-candidate fan-out) — the same call the
  prompt already made, not a new one. The 126-token addition scales with
  however many evolve calls a run already makes (pool size × evolution
  rounds), the same way every other line already in `evolution.md` does; it
  adds no new LLM call and no new call-site multiplication.
- **Test:** `test_prompt_carries_the_published_reasoning_order` in
  `engine/tests/test_evolution_operators.py` — still green, now parametrized
  over the five operators that render `evolution.md`; the two published-prompt
  operators are covered by
  `test_feasibility_prompt_carries_the_published_guidelines` and
  `test_out_of_box_prompt_is_the_published_analogy_prompt` in the same file.

**Two findings left for the owner, not restored** (both judged in their
sections above; **both built on 2026-09-06** — see the note at the head of this
section):

1. **Ranking's `{notes}`/"Considerations" slot** (`ranking-04`, `ranking-05`)
   — the published prompt gives this field no defined content in any
   example the corpus contains, and three functionally overlapping channels
   already reach the judge (`evaluation_criteria`, `preferences`,
   `supervisor_guidance`). Restoring it would mean inventing what
   "considerations" holds, which is padding, not restoration. Revisit if a
   concrete source for match-level considerations is ever defined.
2. **`ranking-05`'s "Turn 1 begins with a summary" instruction** — pacing,
   not a decision-changing rule; the judge's seven named comparison-criteria
   fields already function as a structured, both-sides summary every turn.
   Not restored because the multi-turn debate path judges roughly a quarter
   of a full tournament's matchups, and no behavior the schema doesn't
   already produce would be gained.

No other template in this audit needed a change.

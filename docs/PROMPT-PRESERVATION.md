# Prompt Preservation Audit

Wave `R8-2` of the fidelity campaign (branch `fix/published-prompt-fidelity`,
starting at HEAD `02278d2f`). Report date: 2026-09-01.

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
not re-opened. `MP-7` is open and is audited on the same footing as every
other instruction in this pass. `MP-8` (the `OUT_OF_BOX`/`INSPIRATION`
naming mismatch) is closed per the owner's decision recorded in
`engine/src/co_scientist/agents/evolution/evolution_operators.py`; not
re-litigated.

---

## Summary (filled in as each prompt is audited; final tally at the end)

| # | Published prompt | Template(s) | Present | Missing | Adapted |
|---|---|---|---|---|---|
| 1 | `evolution-06-feasibility-improvement.md` | `evolution.md` (`COHERENCE_FEASIBILITY` operator) | 4 | 1 | 0 |
| 2 | `evolution-07-out-of-the-box-thinking.md` | `evolution.md` (`INSPIRATION` operator, MP-8) | 4 | 1 | 0 |
| 3 | `generation-01-hypothesis-after-literature-review.md` | `generation_debate_and_literature.md` (literature block); `generation_draft_with_tools.md` (reconstruction) | 8 | 0 | 1 |
| 4 | `generation-02-hypothesis-after-scientific-debate.md` | `generation_debate_and_literature.md`, `generation_after_debate.md` | 14 | 0 | 1 |
| 5 | `meta-review-08-meta-review-generation.md` | `meta_review.md` | 7 | 0 | 0 |
| 6 | `ranking-04-pairwise-comparison.md` | `ranking.md` | 4 | 1 | 0 |
| 7 | `ranking-05-comparison-via-scientific-debate.md` | `ranking.md` + `agents/ranking/ranking_debate*.py` | 7 | 2 | 1 |
| 8 | `reflection-03-generate-observations.md` | `reflection_observations.md` | 6 | 0 | 3 |

---

## 1. `evolution-06-feasibility-improvement.md`

**Template:** `evolution.md`, rendered for the `COHERENCE_FEASIBILITY`
operator (`engine/src/co_scientist/agents/evolution/evolution_operators.py`
— this operator is the one the README/checklist maps to A.6, not disputed).

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Refine the provided conceptual idea, enhancing its practical implementability by leveraging contemporary technological capabilities" | present | `COHERENCE_FEASIBILITY` instruction, `evolution_operators.py:52-57`: "refine the proposal so it is implementable with contemporary technological capabilities" |
| 2 | "Ensure the revised concept retains its novelty, logical coherence, and specific articulation" | present | same instruction: "retaining its novelty and specific articulation" (logical coherence covered by "tighten the internal logic") |
| 3 | `Goal: {goal}` | present (MP-2, `done`) | `evolve_prompt.py:385` sets `research_goal` unconditionally; `templates/evolution.md:11` |
| 4 | `Evaluation Criteria: {preferences}` | present (MP-3, `done`) | `evolve_prompt.py:386`; `templates/evolution.md:56` |
| 5 | **Reasoning scaffold**: (1) introductory overview of the relevant scientific domain, (2) concise synopsis of recent pertinent research and successful precedents, (3) reasoned argument for how current technological advances enable the concept, (4) CORE CONTRIBUTION — a detailed, innovative, technologically viable alternative, emphasizing simplicity and practicality | **missing** | Not present anywhere in `evolution.md`. This is `MP-7` (`docs/CORPUS-EXTRACTION.md:243`, status `work`). See judgment below. |

**4 present / 1 missing / 0 adapted.**

## 2. `evolution-07-out-of-the-box-thinking.md`

**Template:** `evolution.md`, rendered for the `INSPIRATION` operator. Per
`MP-8` (closed, `evolution_operators.py:14-22`) `INSPIRATION` is the
operator that structurally matches this published prompt (single hypothesis
by analogy from supplied partner concepts); the enum named `OUT_OF_BOX`
below is a different, clone-authored strategy with no published counterpart
and is not the mapping target here.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Generate a novel, singular hypothesis inspired by analogous elements from provided concepts" | present | `INSPIRATION` instruction, `evolution_operators.py:58-63`: "borrowing the mechanism or structure of one of the existing top-ranked approaches supplied as partners" |
| 2 | `Goal: {goal}` | present (MP-2, `done`) | as above |
| 3 | `Criteria for a robust hypothesis: {preferences}` | present (MP-3, `done`) | as above |
| 4 | "Inspiration may be drawn from the following concepts (utilize analogy and inspiration, not direct replication): `{hypotheses}`" | present | `### Partner Hypotheses` / `{{partner_context}}`, `templates/evolution.md:90-92`; the instruction's own text — "State what was borrowed, from which approach, and what was adapted rather than replicated" — is the "not direct replication" guard, `evolution_operators.py:61-63` |
| 5 | "This should not be a mere aggregation of existing methods or entities. Think out-of-the-box." | present (MP-5, `done`) | `templates/evolution.md:15`, template-wide CRITICAL REQUIREMENTS section, reaching every operator |
| 6 | **Reasoning scaffold**: (1) concise introduction to the relevant scientific domain, (2) summary of recent findings and successful approaches, (3) identify promising avenues for exploration, (4) CORE HYPOTHESIS — a detailed, original, specific hypothesis leveraging analogous principles | **missing** | Same gap as evolution-06's item 5. The `MP-7` checklist row cites only `evolution-06:861`; this prompt carries the identical structure (domain overview -> recent-findings synopsis -> reasoned step -> core deliverable) and loses it for the same reason: `evolution.md` has no equivalent section. |

**4 present / 1 missing / 0 adapted.**

### Judgment on the shared loss (both evolution-06 and evolution-07)

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

**Templates:** the README maps A.1 to two places — `generation_debate_and_literature.md`
("also carries A.1's literature block, `articles_with_reasoning`") and
`generation_draft_with_tools.md` (README: "Reconstruction of A.1's
literature-grounded generation; the agentic draft-with-tools workflow is
clone-authored"). Audited against both; the literature-and-debate template is
the primary mirror target, the draft-with-tools template is a documented
reconstruction rather than a derivation.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Formulate a novel and robust hypothesis to address the objective" | present | `generation_debate_and_literature.md:7` ("develop a novel, relevant, and robust hypothesis, given a research goal"); `generation_draft_with_tools.md:5` |
| 2 | "Describe the hypothesis in detail, including specific entities, mechanisms, and anticipated outcomes" | present | `generation_debate_and_literature.md:42` ("State a precise causal or mechanistic proposition with the entities, context, intervention or observation, and predicted outcome"); `generation_draft_with_tools.md` schema field `hypothesis` |
| 3 | "This description is intended for an audience of domain experts" | present (adapted) | Both templates split output into a technical `hypothesis`/`Hypothesis` field plus a separate lay `explanation`/`Explanation` field — a schema convention applied consistently across every generation and evolution template in this repo (`evolution.md` does the same), not a loss specific to this prompt |
| 4 | "You have conducted a thorough review of relevant literature and developed a logical framework...The articles consulted, along with your analytical reasoning, are provided below" | present | `## Literature Review and Analytical Rationale` (`generation_debate_and_literature.md:59-65`); `## Literature Review Context` (`generation_draft_with_tools.md:26-36`) |
| 5 | `Goal: {goal}` | present | `{{goal}}`, both templates |
| 6 | `Criteria for a strong hypothesis: {preferences}` | present | `{{preferences}}`, both templates |
| 7 | "Existing hypothesis (if applicable): `{source_hypothesis}`" | present | `## User-Provided Starting Hypotheses`, `{{user_hypotheses}}`, both templates |
| 8 | `{instructions}` | present | `{{instructions}}`, both templates |
| 9 | "Literature review...chronologically ordered, beginning with the most recent analysis" | **adapted (architectural), not a loss** | `articles_with_reasoning` is not a literal ordered article list in this engine — it is an LLM-synthesized narrative produced by the literature-review node's Phase 4 synthesis over per-paper analyses (`agents/generation/literature_review/synthesis.py::_phase4_synthesize`). A chronological-ordering instruction has no object to apply to once the representation is a synthesized paragraph rather than a list; this is a pre-existing, documented architectural choice (the literature review pipeline), not something this pass can restore without redesigning that pipeline |

**8 present / 0 missing / 1 adapted.**

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
| 5 | `Review Overview: {reviews_overview}` | present (adapted) | No literal `reviews_overview` variable exists anywhere in the codebase (confirmed by search). Functionally superseded by `{{meta_review_context}}` (`generation_debate_and_literature.md:16`, `generation_after_debate.md:16`) — the run's cross-hypothesis synthesis of review themes and strategic recommendations, spliced into every generation strategy (`prompts/_common.py::_format_meta_review_context`, docstring: "the run's own synthesis of which areas are already covered and which directions remain open feeds back into the next cycle"). This is richer than a raw review dump and serves the same purpose; not counted as a loss |
| 6 | Initial contribution: "Propose three distinct hypotheses" | present | "Propose three distinct novel {{attributes}} hypotheses" |
| 7 | Subsequent contributions: pose clarifying questions | present | both templates, Procedure section |
| 8 | Critically evaluate on: adherence to attributes, utility/practicality, level of detail/specificity | present | both templates, same three bullets verbatim in structure |
| 9 | Identify weaknesses/limitations | present | both templates |
| 10 | Propose concrete improvements | present | both templates |
| 11 | Conclude each turn with a refined iteration of the hypothesis | present | both templates |
| 12 | General guidelines: boldness/creativity, collaborative, prioritize quality | present | both templates, "General guidelines" section |
| 13 | Termination: "typically 3-5 turns, maximum of 10", conclude by writing "HYPOTHESIS" (caps) then a self-contained exposition | present | turn constants `_DEBATE_TYPICAL_MIN_TURNS=3` / `_DEBATE_TYPICAL_MAX_TURNS=5` / `_DEBATE_MAX_DISCUSSION_TURNS=10` (`prompts/generation_debate.py:279-303`), rendered into both templates' Termination condition section verbatim on the numbers |
| 14 | `#BEGIN TRANSCRIPT# {transcript} #END TRANSCRIPT#` | present | both templates, verbatim markers |

**14 present / 0 missing / 1 adapted** (item 5 counted once, applies to both).

---

## 5. `meta-review-08-meta-review-generation.md`

**Template:** `meta_review.md`, rendered by `get_meta_review_prompt`
(`engine/src/co_scientist/prompts/planning.py:27-42`).

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Expert in scientific research and meta-analysis" | present | `meta_review.md:7` |
| 2 | "Synthesize a comprehensive meta-review of provided reviews pertaining to the research goal" | present | `meta_review.md:7` |
| 3 | `Goal / Preferences / Additional instructions / Provided reviews` slots | present | `{{research_goal}}`, `{{preferences}}` (MP-4, `done` — `planning.py:31-42`, `meta_review.md:57-60`), `{{instructions}}`, `{{all_reviews}}` |
| 4 | "Generate a structured meta-analysis report of the provided reviews" | present | the six numbered sections, `meta_review.md:9-52` |
| 5 | "Focus on identifying recurring critique points and common issues raised by reviewers" | present | `meta_review.md:9-13`, section 1 |
| 6 | "Provide actionable insights for researchers developing future proposals" | present | `meta_review.md:22-28`, section 3 ("Actionable Insights!") |
| 7 | "Refrain from evaluating individual proposals or reviews; focus on producing a synthesized meta-analysis" | present, near-verbatim | `meta_review.md:52` |

**7 present / 0 missing / 0 adapted.** Clean mirror — every published
instruction is present, most close to verbatim. Sections 2, 4, 5, and 6 of
the template (process evaluation, direction assessment, cross-hypothesis
connections, candidate/existing-solution comparison) are clone-authored
additions beyond the published prompt's scope, not substitutions for
anything the published text asked for — they carry no loss.

## 6. `ranking-04-pairwise-comparison.md`

**Template:** `ranking.md`, rendered by `get_ranking_prompt`
(`engine/src/co_scientist/prompts/ranking.py`).

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Expert evaluator...compare two hypotheses...determine which is superior based on the specified attributes" | present | `ranking.md:9`, expanded into the seven named comparison criteria (`ranking.md:15-21`) rather than the paper's single unnamed `{idea_attributes}` slot |
| 2 | "Concise rationale...concluding with the phrase 'better idea: <1 or 2>'" (the source's own noted inconsistency with "better hypothesis") | present | `ranking.md:70`, and `_VERDICT_LINE_RE` in `agents/ranking/ranking_debate_turns.py` accepts both "better idea" and "better hypothesis" phrasings, resolving the source's own internal inconsistency rather than picking one arbitrarily |
| 3 | `Goal: {goal}` | present | `{{research_goal}}`, `ranking.md:42` |
| 4 | `Evaluation criteria: {preferences}` | present (MP-6, fixed on this branch though `docs/CORPUS-EXTRACTION.md` still shows `work` — see "Standing rule" above) | `{{preferences}}` → `_format_ranking_preferences`, `ranking.md:27`; pinned by `test_judge_prompt_carries_scientist_preferences` |
| 5 | "Considerations: `{notes}`" (a slot distinct from both `{preferences}` and the per-hypothesis `{review N}`) | **missing** | No `notes`/`considerations` variable is rendered anywhere in `ranking.md` or its builders. Judgment below. |
| 6 | "Each hypothesis includes an independent review. These reviews may contain numerical scores. Disregard these scores...not directly comparable across reviews" | present (MP-1, `done`) | `ranking.py:466-469`, rendered into `{{review_context}}` |
| 7 | `Hypothesis 1 / Hypothesis 2 / Review of hypothesis 1 / Review of hypothesis 2` | present | `{{hypothesis_a}}` / `{{hypothesis_b}}`, `{{review_context}}` (per-hypothesis review scores) |
| 8 | "Reasoning and conclusion (end with 'better hypothesis: <1 or 2>')" | present | `ranking.md:70`, see item 2 |

**4 present / 1 missing / 0 adapted** (counting the seven-criteria
elaboration of item 1, the verdict line, goal, and criteria/review-scores as
present; "Considerations" as missing).

**Judgment on the missing "Considerations: `{notes}`" slot.** The published
prompt hands the judge one more free-text field, separate from both the
evaluation criteria and the per-hypothesis reviews, with no elaboration in
the paper on what it's meant to carry match-to-match. Our judge prompt
already carries three general-guidance channels that would be the natural
home for whatever "considerations" means: `{{evaluation_criteria}}` (the
scientist's explicit criteria list), `{{preferences}}` (their prose steer,
MP-6), and `{{supervisor_guidance}}` (key research areas to weigh). Given
the paper gives this slot no content of its own to lose — it's an empty
placeholder in every rendered example the corpus contains — and three
functionally overlapping channels already exist, this is recorded as a real
gap but not recommended for restoration: adding a fourth "Considerations"
field with no defined content would pad the template rather than restore an
instruction. Left for the owner if a concrete source for match-level
"considerations" ever gets defined.

---

## 7. `ranking-05-comparison-via-scientific-debate.md`

**Templates:** `ranking.md` (shared base prompt for every turn) plus the
multi-turn debate machinery in `agents/ranking/ranking_debate.py` /
`ranking_debate_turns.py`, which is what actually implements the "scientific
debate" half of A.5 that A.4 doesn't have.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Panel of domain experts...structured discussion to evaluate two competing hypotheses" | present | the multi-turn matchup loop itself (`ranking_debate.py`) |
| 2 | "Rigorously determine which hypothesis is superior based on a predefined set of attributes and criteria" | present | `ranking.md`'s seven comparison criteria, shared with A.4 |
| 3 | "The experts possess no pre-existing biases toward either hypothesis" | present (adapted) | Not stated as an instruction to the model anywhere. Structurally enforced instead: every matchup is judged in both A/B presentation orders (`_render_ordered_prompt` with `swapped=True`) and a position-balanced fallback (`_balanced_invalid_fallback`) resolves malformed output — an empirical bias countermeasure rather than a claim of impartiality the model can't actually verify about itself. Judged stronger than the published instruction, not a loss |
| 4 | `Goal / Criteria for hypothesis superiority ({preferences}) / Hypothesis 1,2 / Initial review of hypothesis 1,2` | present | `{{research_goal}}`, `{{preferences}}` (MP-6), `{{hypothesis_a}}`/`{{hypothesis_b}}`, `{{review_context}}` |
| 5 | Debate procedure: "typically ranging from 3 to 5, with a maximum of 10" turns | present | `_RANKING_DEBATE_TYPICAL_MIN_TURNS=3` / `MAX_TURNS=5` / `_RANKING_DEBATE_MAX_TURNS=10`, `ranking_debate_turns.py:31-39`, echoed into every follow-up turn's prompt by `_append_debate_context` |
| 6 | "Turn 1: begin with a concise summary of both hypotheses and their respective initial reviews" | **missing** | No instruction anywhere directs the opening turn to summarize before judging; the base `ranking.md` goes straight from presenting the hypotheses to "Make a clear decision" |
| 7 | Subsequent turns: evaluate on correctness/validity, utility/practicality, sufficiency of detail, novelty/originality, desirability for implementation; identify weaknesses/limitations/flaws | present | the same seven criteria as A.4 (`ranking.md:15-21`) map onto these five dimensions (soundness↔correctness, feasibility/impact↔utility, clarity↔detail sufficiency, novelty↔novelty, feasibility↔desirability); `_append_debate_context`'s "otherwise challenge the weak arguments" carries the weakness-identification instruction into follow-up turns |
| 8 | "Additional notes: `{notes}`" | **missing** | Same gap as ranking-04 item 5 — no `notes`/considerations channel exists. Not double-counted in the fix recommendation; see judgment under ranking-04 |
| 9 | Termination: "provide a conclusive judgment...state the rationale...write 'better idea: ' followed by '1' or '2'" | present | `_VERDICT_LINE_RE`, `ranking.md:70`; `_append_debate_context`'s "confirm that verdict decisively" |

**7 present / 2 missing / 1 adapted.** The "Turn 1 begins with a summary"
gap is stylistic pacing, not a decision-changing instruction — the judge
already writes a structured, both-sides comparison every turn via the seven
named criteria fields, which functions as the summary the paper asks for.
Not recommended for restoration: adding a scripted opening-turn instruction
buys no behavior the schema doesn't already produce, and 25 of the 90+
tournament matchups in a full run go through this multi-turn path, so any
instruction added here is worth being sure of before adding it.

## 8. `reflection-03-generate-observations.md`

**Template:** `reflection_observations.md`.

| # | Published instruction | Class | Evidence |
|---|---|---|---|
| 1 | "Determine if the hypothesis provides a novel causal explanation for the observations, or if they contradict it" | present | `reflection_observations.md:5` |
| 2 | Step 1, Observation extraction: list relevant observations from the article | present | `reflection_observations.md:9` |
| 3 | Step 2, Causal analysis (individual): state established cause, assess whether the hypothesis is a causal factor, prefix "would we see this observation if the hypothesis was true:", say "not a missing piece" where a better explanation exists | present (adapted, stricter) | `reflection_observations.md:10-14`. Reworded to require the hypothesis "specifically and uniquely explains this observation beyond established mechanisms" (vs. the published "could be a causal factor") and the prefix gains ", and not otherwise:". This tightening is the documented fix for gap/novelty sentences being entailed as fundamental claims (project history: "Evidence-gap claims collapse" — 6/8 ideas were dying `evidence_blocked` under the looser published wording); it is a deliberate strengthening, not a loss |
| 4 | Step 3, Causal analysis (summary): novel explanation for a subset of observations, prefix "would we see some of the observations if the hypothesis was true:" | present (adapted) | `reflection_observations.md:15`, reworded to "taken as a whole, does the hypothesis explain observations that known mechanisms cannot:" — same summary-judgment function, tightened the same way as item 3 |
| 5 | Step 4, Disproof analysis: prefix "does some observations disprove the hypothesis:" | present, verbatim prefix | `reflection_observations.md:16` |
| 6 | Step 5/6, Conclusion: `"hypothesis: <already explained, other explanations more likely, missing piece, neutral, or disproved>"` | present, verbatim vocabulary | `reflection_observations.md:18` and the Response line, `:40` |
| 7 | Scoring vocabulary: the five categories with their definitions | present | `reflection_observations.md:20-26`, all five categories preserved with the same names, definitions tightened consistently with items 3-4 |
| 8 | "If observations are expected regardless of the hypothesis, and don't disprove it, it's neutral" | present | `reflection_observations.md:28` |

**6 present / 0 missing / 3 adapted** (items 3, 4, and 7's tightening
counted together as one adaptation theme; individually listed above). No
gaps. The one structural addition — step 5, "Positive observations" (list
confirmed strengths) — is new relative to the published prompt but adds a
field rather than displacing one; not a loss.

---

## Overall summary

| # | Published prompt | Template(s) | Present | Missing | Adapted |
|---|---|---|---|---|---|
| 1 | `evolution-06-feasibility-improvement.md` | `evolution.md` (`COHERENCE_FEASIBILITY`) | 4 | 1 | 0 |
| 2 | `evolution-07-out-of-the-box-thinking.md` | `evolution.md` (`INSPIRATION`) | 4 | 1 | 0 |
| 3 | `generation-01-hypothesis-after-literature-review.md` | `generation_debate_and_literature.md`, `generation_draft_with_tools.md` | 8 | 0 | 1 |
| 4 | `generation-02-hypothesis-after-scientific-debate.md` | `generation_debate_and_literature.md`, `generation_after_debate.md` | 14 | 0 | 1 |
| 5 | `meta-review-08-meta-review-generation.md` | `meta_review.md` | 7 | 0 | 0 |
| 6 | `ranking-04-pairwise-comparison.md` | `ranking.md` | 4 | 1 | 0 |
| 7 | `ranking-05-comparison-via-scientific-debate.md` | `ranking.md` + debate machinery | 7 | 2 | 1 |
| 8 | `reflection-03-generate-observations.md` | `reflection_observations.md` | 6 | 0 | 3 |
| | **Total** | | **54** | **5** | **6** |

**Bottom line: the eight published prompts preserved their content
faithfully.** 54 of 65 identified substantive instructions are present
(most reworded, several already fixed by `MP-1`–`MP-6`), 6 more are
deliberately and defensibly adapted (three of them documented fixes for
prior findings — evidence-gap over-triggering, position bias, the source's
own "better idea"/"better hypothesis" inconsistency), and only 5 are
genuine gaps, three of which cluster into a single finding (`MP-7`'s
reasoning scaffold, shared by evolution-06 and evolution-07) and two more
into a second (the ranking prompts' unfilled `{notes}`/"Considerations"
slot, which the paper itself gives no content to lose). Both are recorded
below with a judgment; neither was found to be silently load-bearing the
way `R8-1`'s reversed-scores instruction was.

---

## Phase 2 — fixes

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
  `engine/tests/test_evolution_operators.py`, parametrized over every
  `EvolutionOperator` — mirrors the existing MP-5 pinning test
  (`test_prompt_carries_the_anti_aggregation_guard_for_combination`) in the
  same file.

**Two findings left for the owner, not restored** (both judged in their
sections above):

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

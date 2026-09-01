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
| 5 | `meta-review-08-meta-review-generation.md` | `meta_review.md` | pending | pending | pending |
| 6 | `ranking-04-pairwise-comparison.md` | `ranking.md` | pending | pending | pending |
| 7 | `ranking-05-comparison-via-scientific-debate.md` | `ranking.md` + `agents/ranking/ranking_debate*.py` | pending | pending | pending |
| 8 | `reflection-03-generate-observations.md` | `reflection_observations.md` | pending | pending | pending |

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

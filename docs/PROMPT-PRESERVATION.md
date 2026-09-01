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
| 3 | `generation-01-hypothesis-after-literature-review.md` | `generation_debate_and_literature.md` (literature block); `generation_draft_with_tools.md` (reconstruction) | pending | pending | pending |
| 4 | `generation-02-hypothesis-after-scientific-debate.md` | `generation_debate_and_literature.md`, `generation_after_debate.md` | pending | pending | pending |
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

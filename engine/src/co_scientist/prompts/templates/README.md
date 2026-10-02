# Prompt template provenance

Google's full prompt library is undisclosed; only eight templates are public
(the paper's appendix prompts A.1–A.8, reproduced byte-exact in
`docs/CORPUS-EXTRACTION.md`, Appendix A). Every template in this directory is
therefore either derived from one of those eight or a clone-authored
reconstruction — never Google source.

Since the 2026-09-06 verbatim rewrite, "derived" means something stricter than
it used to: **every published sentence of each of the eight renders word for
word, in published order**, through the real builders. What the derived
templates add on top of that is run context the public templates predate
(`{{supervisor_guidance}}`, `{{meta_review_context}}`, `{{run_guidance}}`, …),
the json_object output contract, and a small number of measured production
fixes. Each of those is listed below, per template, and pinned by
`engine/tests/test_published_prompt_fidelity.py`.

## Derived from the eight published templates

| Template | Published source | Carried verbatim |
|---|---|---|
| `generation_draft_with_tools.md` | A.1 — hypothesis after literature review | Role sentence, the describe-in-detail and domain-expert sentences, the literature framing pair, `Goal:`, `Criteria for a strong hypothesis:`, `Existing hypothesis (if applicable):`, the chronologically-ordered literature label, and the `Proposed hypothesis (detailed description for domain experts):` answer cue |
| `generation_debate_and_literature.md` | A.2 — hypothesis after scientific debate; also carries A.1's literature block | A.2's role sentence, `Goal:`, `Criteria for a high-quality hypothesis:`, `Instructions:`, `Review Overview:`, the full `Procedure:` (initial and subsequent contributions, the three critique axes, the general guidelines), the termination condition and its `HYPOTHESIS` token, and the `#BEGIN TRANSCRIPT#` / `#END TRANSCRIPT#` fences; plus A.1's literature label and its own `#BEGIN/#END LITERATURE REVIEW#` fences |
| `generation_after_debate.md` | A.2 — the same debate prompt without the literature block | As above, minus the literature block |
| `reflection_observations.md` | A.3 — observation generation | The whole prompt: both opening sentences, `Instructions:`, the five numbered steps with the arXiv **four** lettered sub-steps a–d, all three mandated `Start with: "..."` literals, `Conclusion:`, `Scoring:` with all five definitions, the `Important:` sentence, and the `Article:` / `Hypothesis:` / `Response:` labels |
| `ranking_pairwise.md` | A.4 — pairwise comparison (single-turn) | The `You are an expert evaluator…` role sentence, `Goal:`, `Evaluation criteria:`, `Considerations:`, the three review sentences ending "Disregard these scores… not directly comparable across reviews", `Hypothesis 1/2:`, `Review of hypothesis 1/2:`, and the `better idea: <1 or 2>` verdict line |
| `ranking_debate.md` | A.5 — comparison via scientific debate (multi-turn) | The panel-of-domain-experts role sentences, `Goal:`, `Criteria for hypothesis superiority:`, `Additional notes:`, `Hypothesis 1/2:`, `Initial review of hypothesis 1/2:`, the whole debate procedure (`Turn 1:` summary, `Subsequent turns:` with the clarifying-questions bullet and the five evaluation aspects), the 3–5 typical / 10 maximum envelope, and the termination judgment with its verdict line |
| `evolution_feasibility.md` | A.6 — feasibility improvement | The whole prompt: role sentence, `Goal:`, `Guidelines:` with its four reasoning imperatives (domain overview → recent-work synopsis → reasoned argument → CORE CONTRIBUTION), `Evaluation Criteria:`, `Original Conceptualization:`, and the `Response:` cue |
| `evolution_out_of_box.md` | A.7 — out-of-the-box thinking | The whole prompt: role sentence, `Goal:`, `Instructions:` with its four imperatives ending on CORE HYPOTHESIS and "This should not be a mere aggregation of existing methods or entities. Think out-of-the-box.", `Criteria for a robust hypothesis:`, the analogy-not-replication instruction over the provided concepts, and the `Response:` cue |
| `meta_review.md` | A.8 — meta-review generation | The whole prompt in published order: role sentence, `Goal:`, `Preferences:`, `Additional instructions:`, `Provided reviews for meta-analysis:`, `Instructions:` with its four bullets (`Refrain from evaluating individual proposals or reviews…` last), and `Response:` |

### Justified differences, per template

Everything below is ours, with no published counterpart. Nothing here rewords
a published sentence — a paraphrase would fail the fidelity guard.

**`generation_draft_with_tools.md` (A.1)**

- The `## Available Tools` list and `{{tool_instructions}}` — published A.1 is
  single-shot; our draft node runs an agentic tool loop and the tool list must
  reach the model or the loop cannot run.
- `{{articles_metadata}}` and `{{citation_reference_section}}` — the retrievable
  paper list and the `[C*]` citation-key mechanic, which is enforced in code
  (`agents/generation/citations.py`), so the model has to be told about it.
- `Attributes to prioritize:` + `{{attributes}}` — this is A.2's own published
  `{idea_attributes}` input; A.1 has no slot for it, so it is folded under the
  published criteria label rather than given a section of its own.
- `Write {{hypotheses_count}} of them, each addressing a different gap or
  approach.` — this node drafts a whole pool in one call where published A.1
  writes one hypothesis; the clause is what makes an N-item request well-formed.
- The full-depth drafting sentence — our Phase 1 draft is preserved by Phase 2
  validation, so depth lost here is lost for good.
- `## Novelty Language` — a measured fix: this path's retrieval is bounded, so
  an unhedged "first of its kind" claim is unfalsifiable.
- The `#BEGIN/#END LITERATURE REVIEW#` fences — the paper's own device (A.2's
  `#BEGIN TRANSCRIPT#`) applied to the paper's own literature slot.
- Run-context slots and the output-format block; see the shared list below.

**`generation_debate_and_literature.md` / `generation_after_debate.md` (A.2)**

- `Put that token on its own line.` — a *following* sentence, not spliced into
  the published one: the `HYPOTHESIS` token is parsed line-anchored
  (`agents/generation/debate_support.py`), and a missed convergence signal costs
  the run a whole serial turn.
- The anti-padding sentence on the termination condition ("do not spend a turn
  restating agreement") — the `HYPOTHESIS` signal really terminates the debate
  here, and debate turns are the deepest serial chain in a run. It adds no
  condition the published text does not already state.
- `{{evaluation_criteria}}` under the published criteria label, and
  `Existing hypothesis (if applicable):` + `{{user_hypotheses}}` — real run
  inputs; the second borrows A.1's published label rather than inventing one.
- `_DEBATE_FINAL_TURN_INSTRUCTIONS`, appended by the builder after the template
  on the one turn that emits structured output.
- The literature block in the `…_and_literature` variant is published **A.1**
  text, placed with the debate's other inputs.
- `## Novelty Language`, run-context slots, output-format block; see below.

**`reflection_observations.md` (A.3)**

- **Batching is the structural adaptation.** Published A.3 runs once per article;
  ours runs once per hypothesis over the whole retrieved corpus. One call per
  article would multiply provider calls by corpus size, per hypothesis, per
  cycle — the per-item-LLM-pass failure the root `CLAUDE.md` records, against a
  free chain capped near 100 requests/day per model. The published `Article:`
  label is kept verbatim and the fan-out is stated in the same line ("Run steps
  1 and 2 for every article in turn, then steps 3 to 5 once across all of them").
- One calibration sentence appended to the published `Important:` paragraph,
  reserving "missing piece" for a concrete explanatory gap. It is the surviving
  trace of the evidence-gap fix whose rewordings of the published steps and
  scoring definitions were all deleted in this pass.
- `{{indra_evidence}}` — knowledge-graph enrichment, a disclosed local source.
- `positive_observations` — a live feature, moved out of the numbered steps into
  the output block so the published step list is five steps again.

**`ranking_pairwise.md` (A.4) and `ranking_debate.md` (A.5)**

- `## Output Format`, explicit and last: the `winner`/`confidence_level` enums,
  the `judgment_explanation` key legend, and the rule that `decision_summary`
  ends on the literal verdict line the published prompt specifies.
- "Make a clear decision…" — ranking is the run's highest-volume call site with a
  measured answerless-retry rate, and the panel framing reads as an invitation to
  keep deliberating.
- "Keep each comparison to 1-2 sentences…" — a token bound on an O(n²) call.
- The `novelty_comparison` hedging paragraph — a measured fix for the judge
  asserting a hypothesis is unprecedented without having checked.
- The published `{preferences}` slot carries two blocks: the scientist's prose
  preferences (always) and their explicit criteria list under a governing
  sub-label (when supplied). A.4's `{idea_attributes}` is resolved onto the same
  block — nothing at the ranking seam carries a separate attributes list.
- The per-side review slot carries scores, the reflection analysis, the
  deep-verification probes and mature-review verdicts, but **not** the reviewer's
  prose narrative, which is withheld on cost grounds (O(n²) per cycle).
- `ranking_debate.md` only: A.4's scores caveat is carried into A.5, because our
  review blocks contain numerical scores A.5's own prompt never anticipated; and
  the sentence requiring a complete JSON answer on every turn, turn 1 included,
  because ours is one call per turn where the published debate is one
  conversation judged at termination.
- `ranking_debate.md` only: the turn envelope is a literal (3 / 5 / 10) rather
  than a template variable — templating it would import
  `agents/ranking/ranking_debate_turns` back through `co_scientist.prompts`, a
  cycle. `test_ranking_prompt.py::test_debate_template_states_the_envelope_the_loop_enforces`
  keeps the prose and the enforced behaviour from drifting.
- Appended by the builder on turn ≥ 2: `## Prior Debate Turns (re-examine and
  refine)` and its guidance paragraph (`ranking_debate_turns.py::_append_debate_context`),
  which reconstructs the conversational context a one-shot-per-turn call lacks.
  It deliberately repeats two sentences the template now also carries, aimed at
  the transcript above it; `docs/PARITY.md` `RANK-DEBATE-CLARIFY-001` pins the
  clarifying-questions sentence's position as the lead of that paragraph.

**`evolution_feasibility.md` (A.6) and `evolution_out_of_box.md` (A.7)**

- A title heading naming the template in logs and saved prompt artifacts; it
  carries no instruction.
- `## Run Context` — `{{review_feedback}}`, `{{meta_review_insights}}`,
  `{{specialist_feedback}}`, `{{supervisor_guidance}}`, `{{run_guidance}}`,
  `{{lab_constraints_section}}`, `{{falsified_assumptions_section}}`.
- `### Literature Review and Analytical Rationale` — the grounding evidence our
  evolution retrieves; the published prompts assume a model that already read
  the field, ours is handed what the run retrieved.
- `## Novelty Language`; `{{diversity_section}}`, which names the near-duplicate
  guard's context hypotheses and removed duplicates so a child is not discarded
  after the fact (the guard itself is enforced in `evolve.py`).
- `## Output Format` plus a bridging sentence ("work through the guidelines above
  in the order given; the fields below are what you return"): the published
  prompts expect prose whose first three steps are reasoning, and under
  json_object mode a model that emits those as preamble breaks the parse.
- A.7 only: the parent-hypothesis block, because published A.7 generates from
  concepts alone while ours evolves a parent and records lineage; and the
  `## Provided Concepts` header inside `{{partner_context}}`, which also carries
  the empty-pool fallback.

**`meta_review.md` (A.8)**

- Sub-bullets under the four published bullets, each naming a schema field the
  model must fill, which a published free-text prompt has no need of. Our seven
  former sections are folded in there rather than kept alongside.
- The candidate/existing-solution comparison tables are sub-bullets *under* the
  published `Refrain from evaluating individual proposals or reviews…` directive,
  introduced by a sentence framing them as set-level synthesis (they place the
  pool on shared axes and carry no verdict on any single proposal). They have
  their own published-output provenance — `docs/PARITY.md`
  `RANKING-CRITERIA-TABLE-001` and `MAIN-RESEARCH-DIRECTIONS-001`.
- `## Output Format`, the text-formatting guidelines, and the `hypothesis_index`
  numbering rule (the reporting-correctness fix the root `CLAUDE.md` records
  under "counts named for different things").
- `{{domain_review_guidance}}`, not `{{domain_evolution_guidance}}`: the
  meta-review is a review of reviews, and the evolution guidance was a
  copy-paste from `evolution.md`.

**Shared by every derived template**

- Run-context slots — `{{supervisor_guidance}}`, `{{meta_review_context}}` (named
  `{{reviews_overview}}` in the two debate templates, where it fills A.2's own
  published `Review Overview:` slot), `{{run_guidance}}`, `{{domain_context}}`
  and the per-agent domain guidance. The paper describes this mechanism itself:
  the Meta-review agent's feedback "is simply appended to their prompts in the
  next iteration" (`docs/PARITY.md` `META-CRITIQUE-APPEND-001`).
- An `## Output Format` block, explicit and **last** before the published answer
  cue. The published prompts take free text; we parse json_object output, and a
  free json_object-mode model answers in prose without a terminal contract.

## Shaped by a published *output*

`research_overview.md` has no published prompt, but the paper prints three
complete Specific Aims pages (§A.5.3), so the section vocabulary it asks
for is read off those exemplars rather than invented:
disease description, unmet need, proposed solution, the aims (each with an
overarching goal, the hypothesis it tests, and the reasoning), and a
closing pilot evaluation. `engine/tests/test_published_artifact_shapes.py`
pins the schema against the exemplar files themselves.

## Clone-authored reconstructions

No published counterpart; reconstructed from the paper's described agent
behavior (or local design where the paper is silent):

`evolution.md`, `supervisor.md`, `review.md`, `review_batch.md`,
`proximity.md`, `deep_verification.md`, `full_review.md`,
`simulation_review.md`, `research_overview.md`, `generation_assumptions.md`,
`generation_assumption_tree.md`, `generation_assumption_sub.md`,
`hypothesis_validation_synthesis_with_tools.md`,
`hypothesis_novelty_analysis.md`, `hypothesis_query_generation.md`,
`literature_review_synthesis.md`, `literature_review_paper_analysis.md`,
`literature_review_query_generation_generic.md`,
`literature_review_query_generation_pubmed.md`,
`literature_review_query_generation_indra.md`,
`research_stances.md`, `research_questions.md`, `research_query.md`,
`research_extract.md`, `research_compress.md`

`evolution.md` is the operator-driven template for the five clone-authored
evolution operators — `ENHANCEMENT`, `INSPIRATION`, `COMBINATION`,
`SIMPLIFICATION`, `ANALOGY`. The two operators the paper published a prompt for
route away from it: `COHERENCE_FEASIBILITY` renders `evolution_feasibility.md`
and `OUT_OF_BOX` renders `evolution_out_of_box.md`
(`evolution_operators.py::operator_template`). It still carries two lines read
off the published prompts — A.7's "not a mere aggregation… think out-of-the-box"
guard and the four-step reasoning order — because those generalize to every
operator. `INSPIRATION` keeps the paper's separately disclosed "inspiration from
existing hypotheses" strategy and is **not** a counterpart to A.7:
`test_every_operator_is_briefed_exactly_once` enforces that an operator carries
either a published template or an `_INSTRUCTIONS` entry, never both.

## The fidelity guard

`engine/tests/test_published_prompt_fidelity.py` is what keeps this file
honest. For each of the eight, it renders the counterpart(s) through the real
builders with one fully populated fixture
(`tests/_published_prompt_fixtures.py`, `tests/_published_prompt_renders.py`)
and asserts:

- every assertable fragment of the published prompt appears in the **rendered**
  prompt as a normalized-literal substring (whitespace collapse, case fold,
  markdown emphasis removed — nothing more, so **a paraphrase does not pass**);
- the fragments appear in **published order**;
- no slot rendered empty (`test_every_slot_rendered` fails first, so a fixture
  gap cannot masquerade as a fidelity gap);
- a handful of named regressions stay gone — the reversed scores instruction,
  the two narrowed A.3 start-phrases, the per-proposal evaluation A.8 forbids,
  and the debate cull bullet.

Matching runs against the rendered prompt rather than the static template
because published text can live in a Python builder and template text can be a
slot that renders nothing. The whole module skips when the engine is checked out
without `docs/CORPUS-EXTRACTION.md` (its source for the published text), so a
corpus-free checkout stays green.

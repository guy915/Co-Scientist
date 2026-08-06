# Prompt template provenance

Google's full prompt library is undisclosed; only eight templates are public
(the paper's appendix prompts A.1–A.8, reproduced in
`references/core/google-co-scientist/prompting-architecture-and-prompt-library.md`,
section 4). Every template in this directory is therefore either derived
from one of those eight or a clone-authored reconstruction — never Google
source. All templates are reconstructions in the strict sense: even the
derived ones extend the published structure with the run-context slots
(`{{supervisor_guidance}}`, `{{meta_review_context}}`, `{{run_guidance}}`,
…) that the public templates predate.

## Derived from the eight published templates

| Template | Published source |
|---|---|
| `reflection_observations.md` | A.3 — observation generation; the five analysis steps, scoring vocabulary, and the `hypothesis: <…>` termination line are preserved |
| `generation_debate_and_literature.md` | A.2 — generation after scientific debate (procedure, turn envelope, `HYPOTHESIS` termination token); also carries A.1's literature block (`articles_with_reasoning`) |
| `generation_after_debate.md` | A.2 — same debate procedure without the literature block |
| `ranking.md` | A.4 + A.5 — pairwise tournament judge; the multi-turn simulated-debate mechanics and the concluding `better idea: <1 or 2>` verdict line |
| `meta_review.md` | A.8 — meta-review synthesis; opening and the "refrain from evaluating individual proposals" directive preserved |
| `evolution.md` | Partly A.6/A.7 — the paper's feasibility-improvement and out-of-the-box prompts survive as operators in a clone-authored operator-driven template, not as standalone prompts |
| `generation_draft_with_tools.md` | Reconstruction of A.1's literature-grounded generation; the agentic draft-with-tools workflow is clone-authored |

## Clone-authored reconstructions

No published counterpart; reconstructed from the paper's described agent
behavior (or local design where the paper is silent):

`supervisor.md`, `review.md`, `review_batch.md`, `proximity.md`,
`deep_verification.md`, `full_review.md`, `simulation_review.md`,
`research_overview.md`, `generation_assumptions.md`,
`generation_assumption_tree.md`, `generation_assumption_sub.md`,
`hypothesis_validation_synthesis.md`,
`hypothesis_validation_synthesis_with_tools.md`,
`hypothesis_novelty_analysis.md`, `hypothesis_query_generation.md`,
`literature_review_synthesis.md`, `literature_review_paper_analysis.md`,
`literature_review_query_generation_generic.md`,
`literature_review_query_generation_pubmed.md`,
`literature_review_query_generation_indra.md`

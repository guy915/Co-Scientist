# Model call roles

`CompletionSpec` and `LLMCallOptions` carry a role and optional effort.
Options override the spec. The role scope covers every retry, tool turn and
closing turn. App calls pass `call_role` and optional `call_effort`.

These defaults apply to the Azure adapter. Free-route profiles retain their
existing provider settings, including Ling's medium effort. BYOK keeps its
selected models and credentials.

| Role | Tier | Default effort |
|---|---|---|
| supervisor, meta_review, overview | Supervisor | medium |
| overview_review | Supervisor | low |
| overview_outline, overview_directions | Supervisor | none |
| worker, generation, literature_synthesis, reflection, review, deep_verification, evidence_queries, simulation, evolution, grounding_queries, research_extract, interview, chat | Worker | medium |
| orchestrator, literature_queries, literature_analysis, drafting, novelty, ranking, proximity, relevance, research, claims, safety, question_repair, goal_text, announcement, credential_probe | Worker | low |

Set `LLM_EFFORT_<ROLE>` to override a named role, for example
`LLM_EFFORT_RANKING=low`. Otherwise an explicit call effort applies, followed by
`LLM_WORKER_EFFORT` or `LLM_SUPERVISOR_EFFORT`, then the table default. Environment
values are read per request. Only none, low and medium are accepted; workers
require low or medium. A retry that disables thinking uses worker low or
supervisor none.

Exact USD prices and model versions live in `platform/llm/profile/`. Azure
deployment names do not define prices. Luna includes cache-write and
long-context rates; Nano has no extra cache-write fee. The spend ledger must
use Luna's long-context rate until its price boundary is confirmed.

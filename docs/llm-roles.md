# Model call roles

`CompletionSpec` and `LLMCallOptions` carry a role and optional effort.
Options override the spec. The role scope covers every retry, tool turn and
closing turn. App calls pass `call_role` and optional `call_effort`.

Free OpenRouter routes bill per request, not per token, so every role asks for
effort max, which the gateway maps to each model's top tier. Chat, interview,
session titles and restatements (`goal_text`) and the run announcement use
medium so users are not left waiting; output budgets are sized for these
efforts. Paid OpenRouter routes bill per token, so they keep the table's effort
(low for none). Azure runs every role on Luna at low, except supervisor and
overview at medium, and the table's none roles and the no-reasoning roles below
at none. Every direct Haiku call uses effort low, with adaptive thinking where
Luna reasons and disabled thinking where it does not, regardless of the table or
overrides. BYOK keeps its selected models and credentials.

| Role | Tier | Default effort |
|---|---|---|
| supervisor, meta_review, overview | Supervisor | medium |
| overview_review | Supervisor | low |
| overview_outline, overview_directions | Supervisor | none |
| worker, generation, literature_synthesis, reflection, review, deep_verification, simulation, evolution, interview, chat | Worker | medium |
| orchestrator, evidence_queries, grounding_queries, research_extract, literature_queries, literature_analysis, drafting, novelty, ranking, proximity, relevance, research, claims, safety, question_repair, goal_text, announcement, credential_probe | Worker | low |

Azure no-reasoning worker roles: evidence_queries, grounding_queries,
research_extract, literature_queries, proximity, relevance, research,
question_repair, goal_text, announcement and credential_probe.

Set `LLM_EFFORT_<ROLE>` to override a named role, for example
`LLM_EFFORT_RANKING=low`. Otherwise an explicit call effort applies, followed by
`LLM_WORKER_EFFORT` or `LLM_SUPERVISOR_EFFORT`, then the table default. Environment
values are read per request and apply to Azure; free routes ignore them. Only none, low and medium
are accepted. A retry that disables thinking uses none on Azure.

Exact USD prices and model versions live in `platform/llm/profile/`. Azure
deployment names do not define prices. Luna includes cache-write and
long-context rates. Its published boundary is 272,000 input tokens: a request
above it pays the long rates for every token. The ledger prices a call at the
short rates when its input bound or reported prompt is at or below the boundary.

Production operator routing selects the native Responses client for Azure.
`LLM_AZURE_ENABLED`, a positive hard total and an unexpired cutoff are required.
The subscriber API slot always uses low effort, and reasons only where Luna
does, regardless of this table. Its output ceilings include hidden thinking.

Operator short roles have a 180-second deadline; overview, meta review and
literature analysis have 600 seconds. Unknown transport outcomes retain spend
and must not be replayed by an outer retry.

# Retrieval and tool cost audit

Inspected 2026-09-19 at `a44fc721`. Classification: **local design choice**;
this is campaign spend control, not a claim about Google's implementation.
No retrieval or inference experiment was executed. Existing comments calling a
provider free are not current billing evidence.

## Paths and findings

| ID | Path / mechanism | Finding and required disposition |
|---|---|---|
| FREE-TOOLS-01 | `engine/mcp_server/tools/web/providers.py`, `web_search.py` | Brave/Tavily use host keys; refusal can fall back to the other configured provider. No campaign gate. Disable unqualified search providers and their availability advertisement before any request, including direct provider entry points. |
| FREE-TOOLS-02 | `engine/mcp_server/tools/lit_review/openalex_search.py::_build_search_params` | Adds `OPENALEX_API_KEY` when present. A free daily allowance does not prevent prepaid usage after exhaustion. Campaign must use a verified no-billing route or omit the provider; preserve ordinary usage. |
| FREE-TOOLS-03 | `engine/src/co_scientist/mcp_client_session.py` | Both `call_tool` and model-driven `execute_tool_call` invoke remote tools. Custom configuration controls servers and tool mappings; a permitted name alone does not establish implementation or cost. Enforce at both invocation paths and qualify the server/configuration, including availability probes. |
| FREE-TOOLS-04 | `engine/src/co_scientist/skills/credentials.py`, `workspace/command_tools.py` | Trusted skill scripts receive host NCBI, AlphaGenome, OpenAlex and FDA variables. Script recognition establishes code origin, not free billing. Campaign must not inject unqualified credentials. |
| FREE-TOOLS-05 | `workspace/run_workspace.py::open_draft_workspace`, `workspace/session.py` | Draft workspaces enable network and skills; review workspaces default to network disabled but can opt in; generated commands can request arbitrary network services. Environment is rebuilt, but skill injection and explicit environment additions remain separate paths. Enforce a campaign-safe execution policy without disabling local computation. |
| FREE-TOOLS-06 | `llm_free_policy.py` | Paid model plugins, server tools, unqualified endpoints and unsupported request extras are already rejected. Keep existing regression coverage; custom MCP tools are not covered by this model guard. |
| FREE-TOOLS-07 | `app/app/run_corpus.py`, literature `relevance.py`, proximity `proximity_graph.py` | No embedding API call found in maintained engine/app code. Corpus scoring is local; semantic relevance and proximity use the guarded model interface. No new embedding service is needed. |

Default configuration declares/wires PubMed, OpenAlex, Europe PMC, preprints, arXiv,
bioRxiv, ChEMBL, UniProt, clinical trials, STRING, Reactome, Open Targets,
Ensembl, gnomAD, web search and URL reading. Web search is registered only
when a provider key resolves; configuration alone does not make it callable. This is an inventory, not a
zero-cost approval. Their maintained implementations are under
`engine/mcp_server/tools/`; custom INDRA uses configurable `INDRA_COGEX_URL`.
`app/app/engine_adapter/tools.py` accepts local and remote configuration.

Literature search retries (`literature_review/search_retry.py`) and recursive
research (`research_adapter/retrieval.py`) both call the MCP client. The
model-facing provider (`tools/provider.py`) forwards to its second invocation
path. A filter only on tools advertised to the model would miss direct searches.

## Current external evidence

[OpenAlex pricing](https://help.openalex.org/access/pricing/), inspected today,
describes daily free usage followed by prepaid consumption. Its
[example costs](https://help.openalex.org/access/example-costs/) documents a
limited no-key allowance. Do not treat the older source comment “free index” as
an account spending guarantee. A credential-free route is a candidate to test;
an arbitrary account key is not approved.

[Tavily pricing](https://docs.tavily.com/documentation/api-credits), inspected
today, documents free credits and optional pay-as-you-go charges. No evidence
of this deployment's billing cap was obtained. Neither it nor Brave is approved
for campaign calls merely because a key exists. Account balances and keys were
not printed or changed.

## Required next evidence

M1-03c2 must reproduce forbidden provider/fallback calls at the actual transport,
then prove suppression with fake ambient keys and custom configurations. Cover
both MCP invocation paths, provider-direct calls, probes, skill credential
injection and workspace execution. Reject unknown cost paths rather than
silently route them elsewhere. If confinement changes, run the mandated Linux
sandbox check. Preserve normal non-campaign behavior.

M1-03c3 must use isolated credentials and the guarded project interfaces to
retrieve a fixed public scientific query, retain source IDs/URLs and extracted
evidence, and exercise provider failure/rate-limit behavior. Start with public
literature implementations already shipped; qualify additional sources only
when their billing path is established. A mock response is not live retrieval
acceptance. An unavailable source remains unavailable, never a paid fallback.

## Configuration and implementation decision

Registry overrides also include `~/.coscientist/tools.yaml` and
`~/.config/coscientist/tools.yaml`; example external servers use
`EXTERNAL_MCP_SERVER_URL` and `ARXIV_MCP_SERVER_URL`. At the reference server,
`server.py::_MCP_TOOLS` controls exposure, and web search is conditionally
registered. Therefore configuration inventory alone overstates live tool
availability. Probe results establish reachability, not free billing.

Use the existing campaign flag for the enforcement work, with explicit resolved
server/tool qualification and server-side provider protection. A second opt-in
flag risks enabling free models while accidentally leaving paid tools active.
Metadata in YAML may describe a tool but cannot certify a remote implementation.
Non-campaign behavior must remain independently covered. Exact adapter/policy
shape will be selected after failing boundary tests, without adding a competing
tool runtime. Enforcement and real retrieval acceptance remain open.

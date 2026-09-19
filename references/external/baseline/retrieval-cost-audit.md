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

## FREE-TOOLS-01/02 implementation — M1-03c2a

The standalone reference MCP package now parses the same strict
`COSCIENTIST_REQUIRE_FREE_MODELS` contract as the engine. It does not import the
engine (a separate deployment/package), and has no second opt-in mode. Campaign
startup omits web search and its probe; dynamic provider selection returns no
paid providers. Direct Brave/Tavily functions reject before creating transport,
so previously registered tools and fallback calls cannot evade the guard.

OpenAlex campaign requests omit the host API key and disable environment proxy
routing. They use the existing anonymous endpoint, with its provider-enforced
quota; this does not claim a new local request-volume ceiling. A quota failure
remains an explicit unavailable-source error; there is no credentialed retry.
Ordinary non-campaign credentials, selection and transport remain covered.
The campaign flag must be set on the MCP service as well as the API at release;
no remote server is assumed to inherit the caller's environment.

Four failing boundary cases preceded implementation. Verification: 87 targeted
provider checks, strict mypy on four changed Python files, Ruff and diff checks.
The startup test launches the actual server module in a separate process with
fake keys and dotenv disabled. Remaining tests use HTTP mocks, including real
httpx request serialization, key omission, proxy bypass, invalid settings and
429 propagation. No live provider request was sent. FREE-TOOLS-03/04/05 and
live retrieval verification remain open; these controls alone do not qualify a
custom MCP server or arbitrary workspace command.

## FREE-TOOLS-03 implementation — M1-03c2b

Campaign MCP admission binds one resolved streamable-HTTP configuration to the
explicit `COSCIENTIST_CAMPAIGN_MCP_URL`. Multiple servers, stdio, extra transport
options, alternate URLs and custom authentication headers are refused before
SDK discovery. Only the existing shared-secret header is permitted. Both direct
and model-driven calls recheck the bound configuration and serving policy before
execution; stale clients created outside campaign mode cannot advertise tools or
answer availability checks after the flag is enabled. Redirects and environment
proxies are disabled for both policy and SDK transport.

The reference server advertises policy `coscientist-public-retrieval-v1` at its
root and registers only the 16 reviewed public literature/database tools in
campaign mode. The existing registration wrapper also enforces the allowlist at
each invocation, including tools registered before the flag was enabled. General
URL fetching, web search/probes, INDRA and unknown tools remain unavailable.
This is a local design choice, not a Google-backed requirement.

The explicit endpoint must be our independently verified deployment. A matching
self-reported manifest does not authenticate arbitrary third-party source code
or establish its billing. Use HTTPS for public deployment transport, or the
existing trusted Railway private network / local loopback. Root policy reads
are public metadata; tool requests retain existing shared-secret authentication.
Public tools need not be literally credentialless: NCBI rate-limit credentials
are distinct from metered search accounts. OpenAlex is forced anonymous.

Behavioral evidence includes failing direct/model admission tests and two failing
stale-client discovery tests before their corrections. Targeted engine checks
cover custom configurations, policy changes, bound-route mutation, hidden tools,
SDK transport and normal client compatibility. Standalone tests exercise actual
server startup registration and synchronous/asynchronous registered execution.
These are offline transport tests, not live retrieval evidence. The separate
M1-03c3 item must demonstrate actual public-source results and provenance.

## FREE-TOOLS-04/05 implementation — M1-03c2c

Campaign workspace commands use the existing OS confinement with networking
disabled, even if a caller requests network access or reuses a session created
before campaign mode. Both bounded commands and persistent command sessions
apply the shared policy immediately before launch. EXTERNAL and full-access
workspace policies are rejected because their network confinement cannot be
verified here. Ordinary non-campaign behavior is unchanged.

The restriction is at workspace command entry points rather than globally in
`wrap_argv`: trusted Git snapshot commands use a separate host-owned path for
local provenance. Changing that path would risk breaking shadow-store writes
without improving confinement of model-authored commands. Code executed by a
workspace process remains inside its inherited OS sandbox.

Skill credential resolution returns no host credentials in campaign mode.
Drafting retains the existing guarded MCP provider and skips remote skill
instructions, extra workspace allocation and licence seeding. Workspace schemas
reflect offline execution, including sessions created before the mode change.
Local computation and file tools remain available. This intentionally withholds
unqualified arbitrary network scripts; public-source retrieval uses the separately
guarded MCP tools, not an assumed-free script or ambient account.

Regression evidence uses a real loopback listener: ordinary commands must reach
it before campaign commands are required to fail the connection while completing
local arithmetic. Both bounded and persistent execution paths are exercised.
A real recognized skill script reports credential presence normally and absence
in campaign mode using a synthetic key. These are confinement tests, not live
scientific retrieval or provider-billing evidence.

Final verification: 87 affected host tests; strict mypy on seven modules; Ruff
and diff checks. The required Linux harness passes 133 tests under Landlock
(3 existing platform skips) and 132 under bubblewrap (4 existing platform skips).
All seven campaign boundary tests pass separately on both with the final module;
none is skipped. Stale skill instruction requests are rejected and offline
recognized scripts do not add source-query attribution. Live source verification
remains M1-03c3; no inference or external scientific query was performed here.

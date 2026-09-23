# Security Review: co-scientist

## Scope

Offline review of committed range 7dce086d..c3cdef26.

- Scan mode: branch_diff
- Target kind: git_diff
- Target ID: target_sha256_2dcd559b93ed8ff7a1888e65190bde53cae4935d62d6c3cb136363a249c2ffc4
- Revision range: 7dce086dd483831b40a12532a84cf7321f058e52...c3cdef26769aefc4bd877755871473cc7e0b36e8
- Snapshot digest: codex-security-snapshot/v1:sha256:7cf25c6bca7b934fd8b15ac5dfeab2e6de632c8fad87d643ab5aaaf69eb1ba3c
- Inventory strategy: diff
- Included paths: .
- Excluded paths: none
- Runtime or test status: No live provider or production tests were run by this scan.
- Artifacts reviewed: artifacts/01_context/threat_model.md, artifacts/02_discovery/in_scope_files.txt, artifacts/02_discovery/candidate_ledger.jsonl

Limitations and exclusions:
- Later commits and uncommitted AGENTS.md are outside this fixed scan.
- No live NCBI call.

### Scan Summary

| Field | Value |
| --- | --- |
| Scan outcome | completed |
| Reportable findings | 2 |
| Severity mix | low: 2 |
| Confidence mix | high: 2 |
| Coverage | complete |
| Validation mode | Static source/control/sink tracing; no provider requests. |

Canonical artifacts: `scan-manifest.json`, `findings.json`, and `coverage.json`. This report is a deterministic projection of those files.

## Threat Model

Text: # Threat Model: co-scientist ## Overview The repository ships a browser-facing FastAPI/React research workbench, a durable LangGraph hypothesis engine, and a separately deployed MCP literature service. The API registers run, interview, document, share, account-export, authentication, log, and diagnostics routers (`app/app/main.py:354-362`). Durable engine tasks load the run-scoped BYOK credential and install both the app and engine credential contexts around execution (`app/app/engine_tasks.py:474-483`). Production persists state in a Railway-mounted SQLite database while the API runs as root to retain write access (`docs/DEPLOYMENT.md:15`). The reviewed change adds a campaign mode intended to admit only currently zero-priced OpenRouter routes, suppress credential-bearing skills and paid search, confine generated workspace commands offline, and bind literature retrieval to one qualified MCP endpoint. Provider calls pass through `enforce_free_request` before transport (`engine/src/co_scientist/llm_request.py:175-183`); campaign MCP calls bind one configured `/mcp` endpoint and recheck its advertised policy before each allowed tool (`engine/src/co_scientist/mcp_campaign.py:40-67`, `engine/src/co_scientist/mcp_campaign.py:94-127`). The production MCP route is an HTTP Railway-private-network URL with a shared-secret header (`docs/DEPLOYMENT.md:30-31`), and the MCP service holds Entrez credentials (`docs/DEPLOYMENT.md:40`). ## Assets - Researchers' goals, prompts, hypotheses, interview content, uploaded documents, and persisted reports. - Run ownership and authentication state, run-scoped BYOK provider keys, the MCP shared secret, and service-side literature-provider credentials. - SQLite integrity and durable task/checkpoint state. - The campaign's zero-spend and credential-isolation guarantees. - Scientific evidence provenance and integrity: literature returned by MCP tools influences claim verification, ranking, and reports. - Host filesystem and process authority exposed to model-generated workspace commands. ## Trust Boundaries - Browser or API caller to FastAPI: requests cross authentication, ownership, input-validation, safety, and rate-limit controls before reaching persisted runs and tasks (`app/app/main.py:354-362`). - Durable worker to provider: a run credential is scoped around task execution (`app/app/engine_tasks.py:474-483`), and the campaign admission seam checks model metadata and attaches zero price ceilings before the LiteLLM transport (`engine/src/co_scientist/llm_free_policy.py:116-153`). - Model output to local workspace: command arguments and file operations are model-controlled; the session applies an OS sandbox and forces campaign commands offline (`engine/src/co_scientist/workspace/session.py:151-157`, `engine/src/co_scientist/workspace/command_session.py:152-160`). - API/engine to MCP service: campaign mode accepts only one explicitly configured URL and a reviewed tool-name set, rejects redirects/proxies, and checks the service's public policy payload (`engine/src/co_scientist/mcp_campaign.py:40-83`, `engine/src/co_scientist/mcp_campaign.py:94-127`). The shared secret authenticates callers to `/mcp` but the `/` status/policy route is intentionally public (`engine/mcp_server/auth_middleware.py:30-40`, `engine/mcp_server/auth_middleware.py:62-81`). - MCP service to public literature services: model-supplied search terms leave the deployment and remote metadata becomes evidence. PubMed uses process-global Entrez identity and API-key state (`engine/mcp_server/entrez.py:18-47`, `engine/mcp_server/entrez.py:50-79`). ## Attacker Capabilities - An unauthenticated Internet caller can reach only routes intentionally left public; an authenticated researcher can create and interact with their own runs and supply goals, messages, uploads, and BYOK credentials. Cross-user ownership bypass is not assumed. - A provider or retrieved publication can return adversarial text that reaches LLM prompts. That text has no authority to alter host configuration or scan scope. - The model can choose offered tool names and arguments, write files in its run workspace, and request confined commands; it does not begin with host environment credentials or unrestricted network/filesystem access. - A network attacker may control traffic on an untrusted public segment but is not assumed to control Railway's private network, deployment environment variables, the operator account, or trusted configuration. - A compromised external provider may return false metadata or content; TLS and exact endpoint binding are expected to protect transport integrity and credentials in transit. ## Security Objectives - Enforce authentication and per-run ownership before protected reads, writes, execution, export, or publication. - Keep BYOK and service credentials scoped to their intended provider operation; never expose them to model-authored commands, logs, reports, or unrelated campaign tools. - In campaign mode, fail closed before transport unless every possible model route is currently verified zero-cost and a binding zero-price ceiling is attached. - Keep generated commands inside the run workspace with no campaign network access, even for long-lived command sessions. - Bind campaign MCP discovery and invocation to the same qualified endpoint and reviewed tool set; reject redirects, proxy overrides, configuration drift, and server policy drift. - Authenticate and verify TLS for public provider connections so search evidence and API credentials cannot be observed or altered in transit. - Preserve source/provenance and distinguish model judgments, deterministic fallbacks, unknown costs, and unverified evidence without upgrading their authority. ## Assumptions and Open Questions - This model applies to immutable range `7dce086dd483831b40a12532a84cf7321f058e52..c3cdef26769aefc4bd877755871473cc7e0b36e8`; 122 later commits and the current working tree are outside the scan. - No repository `SECURITY.md` exists, so the repository instructions and source-backed deployment documentation supply severity context. - Production keeps the MCP service on Railway's private network and configures the shared secret as documented; deployments that omit it rely solely on network placement (`docs/DEPLOYMENT.md:30-40`). - The scan performs offline source analysis and bounded local checks only; it does not contact providers, inspect production, spend credits, or read credential values. - Public-provider availability, current pricing, and external service behavior are mutable and cannot be proven from the frozen source alone. The changed request path deliberately fetches current OpenRouter metadata before each admitted campaign call.

## Findings

| Finding | Severity | Confidence | Detailed write-up |
| --- | --- | --- | --- |
| [Default Entrez requests disable TLS certificate validation](#finding-1) | low | high | inline below |
| [Campaign PubMed requests use the shared Entrez API credential](#finding-2) | low | high | inline below |

### Confidence Scale

| Label | Meaning |
| --- | --- |
| high | Direct evidence supports the finding with no material unresolved blocker. |
| medium | Evidence supports a plausible issue, but material runtime or reachability proof remains. |
| low | Evidence is incomplete and the item is retained only for explicit follow-up. |

<a id="finding-1"></a>

### [1] Default Entrez requests disable TLS certificate validation

| Field | Value |
| --- | --- |
| Severity | low |
| Confidence | high |
| Confidence rationale | The branch inversion and replacement of Python's default HTTPS context with the unverified factory are explicit in source, and the changed campaign allowlist directly reaches the Entrez initialization path. |
| Category | TLS certificate validation disabled |
| CWE | CWE-295 |
| Affected lines | engine/mcp_server/campaign.py:24-28, engine/mcp_server/entrez.py:37-47, engine/mcp_server/entrez.py:82-87, engine/mcp_server/tools/lit_review/search_pubmed.py:63 |

#### Summary

New campaign PubMed path uses a default-unverified TLS context for public Entrez requests. Campaign mode newly allows all PubMed tool variants in `engine/mcp_server/campaign.py:24-28`, and `search_pubmed` reaches `initialize_entrez()` at `engine/mcp_server/tools/lit_review/search_pubmed.py:63,202`. In `engine/mcp_server/entrez.py:37-47`, an unset `DISABLE_SSL_VERIFY` produces `ssl_verify=False` and then calls `_disable_ssl_verification()`; that helper replaces Python's default HTTPS context factory with `ssl._create_unverified_context` at lines 82-87. Thus the default path disables certificate verification, while setting the variable named `DISABLE_SSL_VERIFY=true` paradoxically leaves verification enabled. Public-network Entrez responses can be intercepted or modified, and the configured Entrez identity/API key can be exposed in transit.

#### Root Cause

Attacker-controlled input is traffic on the public-network path between the MCP service and NCBI. The changed campaign allowlist makes this supporting-code sink part of the reviewed campaign evidence path. The closest apparent control is the `DISABLE_SSL_VERIFY` flag, but its branch is inverted. Impact includes scientific-evidence integrity compromise and exposure of Entrez request credentials to an on-path attacker.

#### Validation

Validation outcomes are recorded below.

Validation method: Static source/control/sink trace of the frozen campaign entrypoint and Python TLS-context mutation. A bounded local import check was attempted but the active interpreter lacks Biopython (`ModuleNotFoundError: Bio`); no network or provider request was made.

- **Status:** validated

Assertions:
- Campaign mode reaches the public PubMed client
- The default configuration takes the certificate-disabling branch
- The branch installs an unverified HTTPS context globally
- No later certificate or hostname verification control is present in this path
- An on-path attacker can affect evidence or request credentials across the public-provider boundary

Evidence:
- engine/mcp_server/campaign.py:24-28 admits the PubMed tool family.
- engine/mcp_server/tools/lit_review/search_pubmed.py:63 and :202 call `initialize_entrez()` before Entrez operations.
- engine/mcp_server/entrez.py:37-47 computes true only when `DISABLE_SSL_VERIFY` is requested, then disables verification when that result is false.
- engine/mcp_server/entrez.py:82-87 replaces `ssl._create_default_https_context` with `ssl._create_unverified_context`.
- engine/mcp_server/entrez.py:67-75 installs the Entrez API key that accompanies requests when configured.
- docs/DEPLOYMENT.md:40 confirms the production MCP service carries Entrez identity and API-key configuration.

Counterevidence and remaining uncertainty:
- The attacker needs an on-path position; Railway's private network protects only the API-to-MCP hop, not the MCP-to-NCBI public hop. The installed validation interpreter lacks Biopython, so the exact dependency call was not dynamically traced, but the repository's Entrez integration and global HTTPS-factory replacement are direct.

Limitations:
- No live TLS interception was attempted, and the scan did not inspect runtime container packages or production environment values.

#### Dataflow

Campaign model invokes an allowed PubMed tool -\> `search_pubmed` calls `initialize_entrez` -\> the unset/default `DISABLE_SSL_VERIFY` branch calls `_disable_ssl_verification` -\> Python's default HTTPS context becomes unverified -\> Bio.Entrez sends the query and configured identity/key to NCBI over a connection whose certificate is not authenticated -\> on-path attacker observes or changes the response.

#### Reachability

The vulnerable client path is automatic for every campaign PubMed request under the default environment. Exploitation additionally requires an attacker capable of intercepting the MCP service's outbound public-network connection.

Preconditions:
- A campaign run invokes an allowed PubMed tool.
- `DISABLE_SSL_VERIFY` is unset or false, which is the documented/default configuration.
- The attacker can intercept the public-network connection.

Limitations:
- The API-to-MCP route is confined to Railway's private network and protected by a shared secret, but those controls do not cover the subsequent MCP-to-NCBI public HTTPS connection. The on-path requirement materially lowers likelihood, and the Entrez API key has narrower authority than a cloud or model-provider key.

#### Severity

**Low** — The branch deterministically disables certificate validation and crosses a public-provider trust boundary, allowing evidence tampering and possible Entrez credential observation. Exploitation requires network interception, and the affected credential/evidence channel is narrower than an authentication or code-execution boundary, so the policy matrix yields low severity. Verified production interception or evidence that the key protects sensitive account functions would raise severity; proof that Bio.Entrez supplies an independently pinned verified context would suppress it.

Correct the flag branch so certificate verification remains enabled by default and permit an unverified context only after an explicit opt-out; add a test asserting the default context has `CERT_REQUIRED` and hostname checking.

#### Remediation

Keep verified TLS by default and fail closed on DISABLE_SSL_VERIFY=true.

Tests:
- Verify certificate and hostname checks remain enabled by default.
- Verify DISABLE_SSL_VERIFY=true fails closed.

<a id="finding-2"></a>

### [2] Campaign PubMed requests use the shared Entrez API credential

| Field | Value |
| --- | --- |
| Severity | low |
| Confidence | high |
| Confidence rationale | The frozen source and production deployment guide directly establish all four material facts: campaign-mode allowance, `initialize_entrez` reachability, loading of `ENTREZ_API_KEY`, and production presence of that credential. |
| Category | Credential isolation failure |
| CWE | CWE-284 |
| Affected lines | engine/mcp_server/campaign.py:24-28, engine/mcp_server/entrez.py:67-75, engine/mcp_server/tools/lit_review/search_pubmed.py:63 |

#### Summary

Campaign mode authorizes PubMed while retaining the MCP service's shared Entrez API credential. `engine/mcp_server/campaign.py:24-28` newly includes `check_pubmed_available`, `search_pubmed`, and `pubmed_search_with_fulltext` in the campaign allowlist. Those paths call `initialize_entrez()` (`engine/mcp_server/tools/lit_review/search_pubmed.py:63,202`), whose unchanged implementation loads `ENTREZ_API_KEY` into process-global `Bio.Entrez.api_key` (`engine/mcp_server/entrez.py:67-75`). The deployment guide states the MCP service carries `ENTREZ_EMAIL` and `ENTREZ_API_KEY` (`docs/DEPLOYMENT.md:40`). Campaign filtering blocks metered web search and suppresses OpenAlex's key, but contains no equivalent Entrez credential removal or anonymous-mode assertion. A model-directed campaign search therefore uses shared credential authority and quota despite the change's credential-isolation objective; the key value is not directly returned.

#### Root Cause

Attacker-controlled input is the campaign model's allowed PubMed tool choice and query. The broken control is the campaign tool policy's use of name-only admission without clearing or forbidding the service-held Entrez credential. Impact is unauthorized use/exhaustion of shared NCBI quota and loss of credential-isolation evidence; no direct key exfiltration is established by this candidate.

#### Validation

Validation outcomes are recorded below.

Validation method: Static source/control/sink trace over the frozen revision, deployment configuration, and campaign-mode call path; no provider call. A local import check was attempted but the active interpreter lacks Biopython, so no runtime request was made.

- **Status:** validated

Assertions:
- Campaign mode advertises and executes PubMed tools
- The PubMed path invokes process-global Entrez initialization
- Initialization loads a service-held API key when present
- Production configuration supplies that API key
- No campaign-mode control clears or forbids the Entrez key

Evidence:
- engine/mcp_server/campaign.py:24-28 includes all PubMed variants in `PUBLIC_TOOLS`.
- engine/mcp_server/tools/lit_review/search_pubmed.py:63 and :202 invoke `initialize_entrez()`.
- engine/mcp_server/entrez.py:67-75 assigns `ENTREZ_API_KEY` to `Entrez.api_key`.
- docs/DEPLOYMENT.md:40 states that the MCP service carries `ENTREZ_EMAIL` and `ENTREZ_API_KEY`.
- OpenAlex has an explicit campaign-mode credential suppression at engine/mcp_server/tools/lit_review/openalex_search.py:331-334; the Entrez path has no equivalent.

Counterevidence and remaining uncertainty:
- The credential value is never returned to the model, NCBI access is free, and the direct impact is quota/authority use rather than billing or key disclosure. No live provider request was made.

Limitations:
- The repository does not document the NCBI account's exact quota, operational sensitivity, or whether every non-production deployment sets the key.

#### Dataflow

Campaign model selects `search_pubmed`/`pubmed_search_with_fulltext` -\> campaign name allowlist admits the tool -\> tool calls `initialize_entrez` -\> MCP process reads `ENTREZ_API_KEY` into global `Entrez.api_key` -\> NCBI request consumes shared credential authority and quota.

#### Reachability

Directly reachable from the campaign's model-facing MCP tool surface whenever the documented production Entrez key is configured. The caller does not need to know the key; choosing an allowed PubMed query exercises it.

Preconditions:
- COSCIENTIST_REQUIRE_FREE_MODELS is enabled on the MCP service so its campaign policy verifies.
- ENTREZ_API_KEY is present, as documented for production.
- The model selects one of the allowed PubMed tools.

Limitations:
- The MCP shared secret and private network limit who can call the service directly, the key is not returned, and NCBI requests are not billed. These controls narrow impact but do not restore the campaign's credential-isolation invariant because the authorized campaign engine itself can direct the credentialed call.

#### Severity

**Low** — Any campaign run can select the allowed PubMed tools, so reachability is high, but the demonstrated authority gain is limited to use and possible exhaustion of a shared free-service API quota; direct secret disclosure, billing, or broader account compromise is not established. The severity would rise if the Entrez credential grants sensitive account access or quota exhaustion materially disrupts the production service.

Set the MCP process to anonymous Entrez mode in campaign operation, or explicitly reject campaign PubMed admission while `Entrez.api_key`/`ENTREZ_API_KEY` is present.

#### Remediation

Pass api_key=None per campaign Biopython request and use anonymous pacing; retain ordinary keyed operation.

Tests:
- Intercept a real Biopython campaign request and assert the shared key is absent.
- Verify anonymous pacing.

## Reviewed Surfaces

| Surface | Risk Area | Outcome | Notes |
| --- | --- | --- | --- |
| Campaign PubMed credential path | Credential isolation | Reported | Candidate candidate-12efc4f5fbb26731 validated against immutable revision. |
| Campaign PubMed TLS path | Transport integrity | Reported | Candidate candidate-c707c0544b07303b validated against immutable revision. |
| Remaining reviewed changed source files | Auth, ownership, zero-cost routing, tools, sandbox, storage, evaluations | No issue found | 76 changed-source rows closed in scan inventory; only two PubMed candidates survived. |

## Open Questions And Follow Up

- Commits after c3cdef26 require separate coverage before release.

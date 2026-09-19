# M1 baseline dossier

## M1-01 — Records and access

Observed 2026-09-19. [Sanitized access evidence](access-2026-09-19.json) and
[deployment inventory](releases-2026-09-19.json) contain no credentials or run data.

- GitHub authenticated repository API reports admin/maintain/push access to
  `guy915/Co-Scientist`, default branch `main`.
- Railway account and production project reads succeeded. API and MCP deployment
  states are `SUCCESS`, both at `7dce086d`; API has one replica and `/app/data` mount.
  API `/health` returned HTTP 200, `healthy`. This is not full production acceptance.
- API variables select `openrouter/minimax/minimax-m3:free` for all four model
  roles, retain DeepSeek and OpenRouter credentials, and preserve the required
  UID/cache/worker settings. Current pricing and serving behavior remain unverified.
- Local environment selects `openrouter/deepseek/deepseek-v4-flash` for all four
  roles. It must not be used for campaign inference without zero-cost enforcement.
- OpenRouter authenticated `/api/v1/key` returned 200. No completion was requested.
  The returned rate-limit field is deprecated; do not infer usable capacity from it.
- Vercel integration confirmed the production alias, `READY` deployment and
  matching `7dce086d` source revision. CLI initially obtained metadata but failed
  its cache write; an escalated read reported an invalid token. Use the authenticated
  connector for reads; CLI authentication may need repair before CLI-based deployment.
- Railway OAuth refresh initially could not persist in the sandbox; the escalated
  read succeeded. CLI skill is current. No MCP installation is needed for this audit.

No infrastructure mutation, inference, email, or upstream checkout occurred.

## M1-02 — Publication evaluator contradiction drift

Status: implemented and verified locally; release pending. Classification: **local design choice**; reuse: existing
live publication predicate. No external source code involved.

The evaluator's `_contradicted_ids` treats every contradicting claim as blocking;
`app.report_content_gates._contradicted_hypothesis_ids` exempts speculative proposals.
Acceptance: evaluator releases an otherwise eligible idea with only a speculative
contradiction; categorical/legacy contradictions and safety holds still withhold.
Boundary: report publication (`scientific_release_gate` and live report finalization).
No quality threshold is relaxed; this aligns the evaluator with existing behavior.
Costs: offline tests only. Release remains pending M1's complete acceptance checks.

Red: `test_a_contradicted_speculative_proposal_is_still_published` failed with
`withhold` instead of `release` before the change. Removed the evaluator's duplicate
predicate; it now calls the live helper with supplied edges, without database I/O.
Green: all 10 release-gate tests pass, including the mixed speculative/categorical
case and legacy role-less contradictions. All 44 app claim-gate, grounding, drain
and drain-safety tests pass, including `test_a_contradicted_proposal_still_reaches_the_report`.
Ruff lint/format and targeted mypy pass. One existing Starlette/httpx deprecation
warning remains. No scientific-quality improvement or production release is claimed.

## Open investigations

- **M1-03a–d, local design choice:** `_gateway_provider` omits `max_price` for
  zero-priced or unknown entries; static pricing and suffixes cannot establish
  current free eligibility. Inspect provider contract before enforcing zero caps.
  App `config_thinking` already delegates to engine thinking/gateway body shaping:
  verify its outgoing requests before adding any new wrapper. Inspect evaluation
  `_run_driver` paid credential loading and each tool provider's billing path.
  No embeddings spend path was identified in preliminary code inspection; that
  is not a completed audit. These slices replace the oversized original item.
- **M1-09, local design choice:** review found evaluator `_releasable` only checks
  persisted safety status, while live publication screens absent/pending legacy
  statuses. Determine the actual artifact precondition and reproduce before fixing.
  Also examine how completed artifacts prove final rendered-report screening;
  the evaluator currently lacks the live `_screen_final_report` behavior.
  This is separate from the verified contradiction fix and remains open.

## M1-03a1 — Explicit zero provider-price ceiling

Classification: **local design choice**. Reuse: the existing shared
`llm_gateway_routing._gateway_provider` builder; no new request abstraction.
Status: implemented and verified offline; production release pending.

Gap: the builder returned early when prompt price was zero, so free routes
carried no ceiling. Changed it to retain prompt/completion ceilings at zero
and add a zero per-request ceiling when both token prices are zero. Paid
BYOK routes retain their existing priced ceilings. The declared fallback list,
provider ordering, and reasoning behavior are preserved.

Contract evidence, checked 2026-09-19: OpenRouter's
[provider-routing reference](https://openrouter.ai/docs/guides/routing/provider-selection#max-price)
defines inclusive token-price ceilings and a per-request `request` ceiling.
Zero ceilings therefore exclude positive prices under that API contract;
they do not establish model availability or cover independently charged plugins.
The [model catalog documentation](https://openrouter.ai/docs/guides/overview/models)
also describes per-request, reasoning, cache and conditional pricing, which
M1-03a2 must validate before live inference.

Boundary: `call_llm`, `call_llm_json`, and `call_llm_with_tools` provider requests.
Red: all three cases failed with missing `max_price`; paid BYOK passed.
Green: `test_llm_zero_price_ceiling.py` covers those paths, JSON budget escalation,
a tool request/result followed by a second completion, free BYOK credentials,
and preserved paid BYOK. The pricing contract test also covers standalone
catalogued routes, not only fallback-chain heads. One test runs the installed
LiteLLM serializer with only HTTP transport replaced and verifies the actual
OpenRouter JSON body. No real inference response was requested or fabricated.

Verification: 61 engine routing/reasoning/BYOK tests and 19 app model/thinking
tests passed. Targeted Ruff lint/format, mypy and diff checks passed. Installed
LiteLLM emitted Pydantic serialization and async-client shutdown warnings after
the HTTP-fixture test; assertions passed and no warnings were suppressed.
Cleanup/deslop removed obsolete comments claiming free routes should be uncapped.

Remaining: M1-03a2 must reject stale, paid, unknown, aliased or unverifiable routes
and charged add-ons, checking every fallback as well as the primary. Validate
applicable prices with decimal arithmetic, including conditional overrides;
do not infer zero from missing fields or a `:free` suffix. Validate before
counting a provider attempt, and preserve explicit/scoped BYOK behavior. The
current-price audit, app integration, tools, live evaluators and live acceptance
remain open. No system-wide zero-spend guarantee is claimed by this sub-item.

## M1-03a2 — Current-price admission before inference

Classification: **local design choice**. Reuse: the existing shared completion
seam, retry classifier, credential scope, response cache and budget counter.

The engine now checks every physical campaign request and every system free
route before counting or sending it. `COSCIENTIST_REQUIRE_FREE_MODELS=1` enables
campaign mode, including calls carrying an explicit key. Outside campaign mode,
explicit/scoped BYOK keeps its existing behavior. The policy receives BYOK
provenance separately from request kwargs; merely supplying a deployment key to
a future app caller does not establish BYOK. App integration remains M1-03b.

Admission requires exact current catalog entries for the primary and every
fallback, text-compatible input/output, and finite exact-zero decimal prices.
All advertised ancillary rates must be zero. Conditional schedules remain
unqualified rather than assumed free. Public metadata is fetched without
credentials, environment proxies or redirects, with a 15-second timeout. A
60-second snapshot is shared under a thread lock off the event loop; expiry
requires a successful refresh. Failed refreshes never reuse expired evidence.

The official [free-variant contract](https://openrouter.ai/docs/guides/routing/model-variants/free)
says currently listed free variants provide inference without cost. This is
additional evidence for omitted ancillary fields only when the exact `:free`
variant exists and its advertised prices are zero; a suffix alone is never
sufficient. Other zero-price promotional routes require explicit zero request,
reasoning and cache rates as well. The
[reasoning contract](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
classifies reasoning tokens as output tokens; any separately advertised rate is
still checked. Unknown and malformed rates are rejected, including tiny positive
values that binary floats could underflow. Zero prompt/completion/request
ceilings bind outgoing OpenRouter requests under its
[provider-routing contract](https://openrouter.ai/docs/guides/routing/provider-selection#max-price).

Campaign requests use the canonical API endpoint and only the existing text,
structured-output and local function-tool request fields. Plugins, server tools,
multimodal payloads, unknown options, router aliases and unverified endpoints are
unavailable. Installed LiteLLM also consults global `model_fallbacks` and
`model_alias_map` after our seam; guarded requests reject those configurations.
No global SDK configuration is mutated. Campaign mode disables LLM response
caching so an old paid/BYOK completion cannot skip admission or masquerade as a
new experiment. Retrieval/node-cache isolation is still owned by M1-03d and the
baseline procedure, not established by this change.

Evidence: six public plain/JSON cases initially sent requests with missing or
paid pricing; all failed the new behavioral assertion. Review reproduced three
paid-cache bypasses and two SDK routing bypasses before their corrections, plus
six malformed-container errors before terminal-error validation. Tests now
exercise expiration, refresh failure, concurrent event loops, exact decimals,
ancillary prices, fallback/add-on rejection, campaign/BYOK isolation, cache
bypass prevention, budget accounting, and actual installed SDK wire serialization
with HTTP transport mocked. No offline fixture is presented as a live result.

[Live metadata observation](openrouter-eligibility-2026-09-19.json) records 447
catalog entries, 22 routes passing metadata admission, and the deployed primary
absent. The actual guard admitted a currently listed Nemotron route using a real
public catalog fetch. This was metadata only: zero inference requests, no model
capability or scientific-quality claim. Model comparisons, app calls, retrieval,
runner enforcement and production acceptance remain open.

Validation commands: from `engine/`, `../.venv/bin/python -m pytest tests/test_llm*.py -q -o addopts=''` passed 429 checks; following the final
malformed-container/modality corrections, the five affected policy, wire,
budget and wrapper files passed 109 checks. Targeted Ruff lint/format and mypy
passed. Existing SDK warnings remain unsuppressed. `httpx~=0.28.1` now declares
the installed transport dependency directly; no package installation occurred.

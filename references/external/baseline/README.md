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

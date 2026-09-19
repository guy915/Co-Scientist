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

Status: investigating. Classification: **local design choice**; reuse: existing
live publication predicate. No external source code involved.

The evaluator's `_contradicted_ids` treats every contradicting claim as blocking;
`app.report_content_gates._contradicted_hypothesis_ids` exempts speculative proposals.
Acceptance: evaluator releases an otherwise eligible idea with only a speculative
contradiction; categorical/legacy contradictions and safety holds still withhold.
Boundary: report publication (`scientific_release_gate` and live report finalization).
No quality threshold is relaxed; this aligns the evaluator with existing behavior.
Costs: offline tests only. Release remains pending M1's complete acceptance checks.

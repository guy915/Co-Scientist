# Campaign route release observation

PR [#62](https://github.com/guy915/Co-Scientist/pull/62) merged the tested
`4f937b3339cab4b49d3ba75a57d7b395503f3c96` branch head into `main` as
`29c5b0029783ec8ce455dbc78b2997eeb6f35860` on 2026-09-27. The
repository's Affected targets CI check failed before downstream jobs ran;
the owner's prior hosted-CI waiver was applied after all required local
checks passed on the exact branch. A Codex Security diff scan of all 23
changed production files reported no high-confidence finding.

The existing services deployed that merge commit:

| Service | Deployment | Observed state |
| --- | --- | --- |
| Railway API | `58b6d725-b838-49a4-8987-a9d5f97b646d` | SUCCESS |
| Railway MCP | `892ec54f-d912-4a60-ade1-46c767dfe893` | SUCCESS |
| Vercel frontend | `dpl_AAh2GbiCD6SBDaJubz5ARrbuRkXe` | READY, production |

The existing keyless `python -m evaluations.prod_smoke` passed health,
MCP/status probes, ownership isolation, untrusted-origin CORS and sanitized
share checks (5/5). The production frontend returned HTTP 200. No migration
or production model-role setting changed. The previous Railway API SUCCESS
deployment `84c91ef2-dda5-4cef-94f9-87761a796737` at merge commit
`d92e5546e15f50c1dc6aaee08372125d387b780d` remains the immediate
availability rollback candidate; a rollback would still require verifying
that the zero-cost policy and current free route remain intact.

Immediately before preparing the live campaign check, the [official endpoint
listing](https://openrouter.ai/api/v1/models/stealth/space-bunny-alpha/endpoints)
showed one Stealth endpoint with prompt and completion price `0` and no
other provider endpoint. This public listing is an admission signal, not an
invoice or actual served-model telemetry.

The new browser tab can read public workbench state but does not carry a
researcher bearer session from an older tab. A new run's campaign policy is
server-derived from that bearer subject, and the fallback browser client ID
does not qualify. Creating a standard run would risk using the production
model-role settings that automatic review prohibited reading, so no run or
inference was started. M12-03b2 remains open for actual served-model readback;
M12-03b3 remains open for a completed campaign-owned goal and Robin refinement.

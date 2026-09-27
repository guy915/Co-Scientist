# Robin refinement correction release

[PR #65](https://github.com/guy915/Co-Scientist/pull/65) merged reviewed head
`15b3fe1e22793de4f28c0e21e7071cd8e330befa` as
`54d5a2626ec8575e43f5fdf593758800fc6c9e18` on 2026-09-27. Targeted
Robin children now compare their generated text with sibling hypotheses,
without reusing parent–peer proximity edges. The separate refinement task
persists physical-call model usage on success, failure, retry and checkpoint
replay. The earlier production `no_child` results did not prove the proximity
edge was their cause; the correction was reproduced and verified offline.

The exact branch passed `make test-all` (3169 engine tests, 2027 app tests,
312 MCP tests, parity and evaluation checks), `make lint`, `make typecheck`,
`make eval-smoke` and `make e2e` (18/18). `make build` and the frontend test
command (803/803) passed on unchanged frontend code and dependencies. Scoped
cleanup found no scratch or dead Python imports/variables. The Codex Security
diff scan `400ce7f2-d91b-4346-9383-addc3d3328eb` reviewed all four changed
source files and reported no finding. GitHub's hosted **Affected targets** job
again failed before downstream jobs ran; the owner's existing hosted-CI waiver
was applied only after these local checks and review. Hosted CI is not counted
as passing.

| Existing production service | Deployment | Commit | Observed state |
| --- | --- | --- | --- |
| Railway API | `fd5088ae-c419-413d-8817-6a363e003b3c` | `54d5a262` | SUCCESS |
| Railway MCP | `5248e262-c469-48ef-ad19-0d5c7411baf2` | `54d5a262` | SUCCESS |
| Vercel frontend | `dpl_FdFNn7dTDJwf4DeUAd3ex2DL6y23` | `54d5a262` | READY, production |

The public frontend returned HTTP 200. The keyless production smoke passed
health, MCP/status, ownership isolation, untrusted-origin CORS and sanitized
share checks (5/5) against `https://api.ai-co-scientist.com`. It made no model
call. No schema migration or production model-role configuration changed. The
preceding `cbf145f5` API deployment `15a902d9-28d4-4fb1-8e00-be9ea76cbb37`
is rollback-capable and already had the campaign-only zero-price route; price
eligibility must still be rechecked before any future inference or rollback.

The first live post-release refinement did create a child with one-parent
lineage, but its follow-on review then replaced the run metrics with a
partial snapshot. The [post-release receipt](m12-robin-postrelease-2026-09-27.json)
records the production observation. This healthy deployment is therefore
**not** accepted as Robin telemetry verification; a typed-checkpoint correction
and new release are required.

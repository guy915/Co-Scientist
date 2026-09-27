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

## Corrective typed-metrics release

[PR #66](https://github.com/guy915/Co-Scientist/pull/66) merged reviewed head
`387431540ec9828eb64f194169441902f9d7c104` as
`33f0d149038997470750980cfd18fccf83840e27`. It preserves typed
`ExecutionMetrics` in successful Robin child checkpoints and retry restoration.
The new red-to-green behavioral test seeds five prior model calls, creates a
Robin child, runs its first successor review and verifies both old and new
usage through the public metrics endpoint. This fixes the observed checkpoint
loss; actual production telemetry remains a separate live acceptance check.

The exact head passed `make test-all` (3169 engine, 2028 app, 312 MCP,
parity and evaluations), `make lint`, `make typecheck`, `make eval-smoke`
and `make e2e` (18/18). Frontend build and 803 frontend tests were reused
from PR #65 because relevant frontend code, dependencies and inputs were
unchanged. Scoped cleanup found no scratch or duplicate logic; Ruff's
unused-import and unused-variable checks passed. Codex Security diff scan
`f1072593-bb2a-401b-bf3c-561bebee4dda` found no issue in the changed
production file. Hosted CI's **Affected targets** job failed in two seconds
and skipped downstream jobs; the existing owner waiver was applied only
after local checks and review. Hosted CI is not counted as passing.

| Existing production service | Deployment | Commit | Observed state |
| --- | --- | --- | --- |
| Railway API | `94f63ad1-0ce3-4f26-984e-3a96b7104ba5` | `33f0d149` | SUCCESS |
| Railway MCP | `5ba88f74-95dd-4296-9326-1d145a6cffaf` | `33f0d149` | SUCCESS |
| Vercel frontend | `dpl_2H5HAMV5u9hxUHqUDHzFVWvdWYRY` | `33f0d149` | READY, production |

The public frontend returned HTTP 200 and keyless production smoke passed
5/5 with no model call. There was no schema migration or role-setting change.
The preceding `54d5a262` Railway API deployment
`fd5088ae-c419-413d-8817-6a363e003b3c` is rollback-capable and carries
the same campaign-only zero-price route. Its telemetry defect is known, so
rollback would restore availability, not telemetry acceptance; this is why
the post-release live refinement remains open separately.

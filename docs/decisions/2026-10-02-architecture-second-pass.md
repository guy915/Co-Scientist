# Second architecture pass

Reviewed and refactored 2 October 2026, building on the
[first-pass review](2026-10-01-architecture-review.md). The requested
`improve-codebase-architecture` skill was absent from the workspace and all
installed skill packages. This pass used a direct source/dependency review,
parallel subsystem audits, React best practices and fresh verification.

## Changes

| Concern | Ownership after this pass | Behavior evidence |
|---|---|---|
| Generation planning/finalization | Public engine operations consumed by graph and durable execution | Generation operation and durable task contract tests |
| Evidence helper imports | Defining evidence modules; obsolete internal facade removed | Existing search, parsing, collection, probe and research suites |
| Interview lifecycle | Turn service and access/credential guards below HTTP/SSE handlers | Interview, streaming cancellation, revision and fallback suites |
| Staged attachments | Shared ownership resolution and metadata views below document/run/interview routers | Attachment admission and run creation tests |
| Operator access | One token/direct-loopback policy for logs, diagnostics and docs | Operator matrix and endpoint security suites |
| PubMed persistence | Standard-library storage layer below fetching and shared-pool orchestration | Metadata digest proof and relocated run-link tests |
| Evaluation identities | Execution-independent digest, validation and request-policy snapshot module | Panel/comparison drift suites and import isolation tests |
| Frontend run refresh | Event policy, snapshot reads and per-resource request ownership | Deferred-request overlap, navigation, unmount and debounce regressions |
| Frontend histories | Shared list-reload lifecycle with provider-owned reads/events | History refresh, stale-response and cleanup regressions |
| API image source access | Runtime user owns both app and engine source; import check follows the user switch | Default-user image import smoke |

## Preserved execution policies

Generation finalization still precedes durable store transactions. Scheduling,
task counts, idempotency keys, leases, failed-item isolation, call accounting,
lineage and transcript ordering remain with their existing owners.

Graph-only expansion retrieval remains graph-only. Graph assumptions still
receive literature/citations; durable assumptions retain their current inputs.
Combining strategy dispatch would otherwise conceal a grounding/spending change.

The first review's tool-turn throttling and app provider-accounting decisions
remain open. This structural pass does not change retry/spend policy. Remaining
private durable Ranking/Reflection imports are candidates for a subsequent
explicit operations boundary.

Those remaining boundaries are completed in the
[public engine operations continuation](2026-10-02-engine-operation-boundaries.md).
The separate [provider-policy change](2026-10-02-provider-policies.md) resolves
tool-turn retries and app accounting and is included in the final integration.

The MCP no-link sidecar still proves the exact metadata bytes. A failed lookup
invalidates the proof even if it writes identical JSON. Run symlinks remain
relative and survive moving the corpus. Identity digest encoding, errors and
all fourteen request-policy file hashes retain their prior definitions.

## Validation

- Engine: 3,427 passed, four platform/optional skips.
- API: 2,283 passed in the full run; 41 final focused tests also pass,
  including boundary guards added after that run collected its tests.
- MCP: 376 passed and strict mypy passed.
- Evaluations: all 214 tests passed, including file/function length gates;
  parity validates all 115 ledger rows and offline safety/citation smoke passes.
- Frontend: 893 tests passed, including thirteen new deferred-request/lifecycle
  regressions. Ten reproduced failures before implementation.
- Browser: eighteen isolated workbench tests and three authenticated production
  asset tests passed with system Chromium.
- Repository Python/frontend lint, strict Python types, TypeScript, frontend
  build/prerender and whitespace checks passed. Contract comparisons tolerate
  Prettier's leading union bars for both aliases and property types.
- Fresh processes imported all 312 engine and 284 app production modules.
  Independent review also checked import order across engine, MCP and evaluation
  boundaries and found no concrete regressions.

Both image builds needed the workspace's CA bundle mounted as a BuildKit secret
at build time because the environment proxy's certificate is absent from the
base image. Temporary Dockerfiles added only that mount; repository trust,
dependency locks and image runtime configuration were not changed for it.
Both final images built successfully, and their default-user runtime import
checks passed. The API check also verifies that the build retains no database.

An API runtime smoke then exposed root-owned engine directories copied with
restrictive host permissions. Build-time root imports had passed, while the
image's default user could not import `co_scientist.constants`. The image now
corrects engine ownership along with app ownership and checks imports after
switching users, using a temporary database removed in the same build step.
The production Railway UID override remains unchanged.

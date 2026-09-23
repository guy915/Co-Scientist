# M2 release review — Kaimen campaign boundary

Reviewed branch: `feat/external-m02-kaimen` through `11285e63`, against deployed
`7dce086d`. The original sealed [security scan](security-diff-scan-original196.md)
covers `7dce086d..c3cdef26`; the [manual supplement](security-supplement196.md)
covers changed production source through `b5d9a701`. Neither is represented as
a scan of later commits or of production.

## Later source and test delta

The coordinator inspected every production-source delta after `b5d9a701`:
`app/app/config.py`, `engine/src/co_scientist/llm_free_catalog.py`,
`engine/src/co_scientist/llm_gateway_routing.py`, and
`evaluations/_comparison_identity.py`, plus their changed tests and example
configuration. A separate GPT-6 Luna/xhigh semantic review independently
traced the selected route through BYOK and campaign admission. Its two
actionable findings were corrected before this review: the advertised model
expiry now gates campaign calls, and `docs/DEPLOYMENT.md` distinguishes the
observed MiniMax production values from the intended Nex Pro release.

The added expiry check runs in the existing free-route admission seam before
provider transport and budget recording. It cannot turn a paid route into an
admitted route: price, route identity, modality, fallback and zero-price cap
checks still run. Absent/null expiry remains admissible; malformed and elapsed
non-null dates fail closed. Tests use zero-priced rows when exercising invalid
dates, so a pricing rejection cannot mask an expiry regression. Explicit BYOK
still bypasses campaign catalog admission, while campaign BYOK remains refused
at run creation. No new credentials, external endpoints, or copied Kaimen code
entered the release.

No new reportable source-level security issue or structural regression was
found in this later delta. The expiry helper is local to the catalog module;
the selected model changes reuse the existing four-role configuration and
gateway route. The eligibility test file remains below the repository's
500-line limit. This is a manual supplement, not a new sealed security scan.

## Verification and release limits

At commit `11285e63`, `make test-all` exited 0: 3,140 engine tests passed
(2 skipped), 1,874 app tests passed, 283 MCP tests passed, and the parity
ledger passed. `make lint`, `make typecheck`, `make build`, `make eval-smoke`,
the 718-test frontend suite, and the two explicit source-size ceiling tests
exited 0. The first browser run shared CPU with the full backend suite and
timed out in three cases; the failure artifacts showed an ongoing run and a
rendered page. A serial `make e2e` rerun passed all 9 browser tests. No
assertion, timeout, or threshold was weakened. The host restart removed the
temporary full-suite log after its exit status had been captured; the serial
browser log was captured separately. Frontend source did not change between
the build/frontend checks and this review.

Pull-request checks, production backup, configuration staging, deployment,
and live serving checks remain separate acceptance steps.
An OpenRouter credential exposed in earlier session output has not been
rotated; zero-price application policy does not address use of that credential
outside the application. The official Nex Pro free endpoint advertises expiry
on 25 September 2026, so later campaign inference must use a newly verified
exact free route or stop.

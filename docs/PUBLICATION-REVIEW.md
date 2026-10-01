# Publication review — 1 October 2026

This records the repository cleanup's local validation. It does not certify
a deployed environment, scientific results, or redistribution rights. These
checks were completed locally before committing the cleanup; no production
deployment or repository visibility change was performed during validation.

## Validation

| Check | Result |
| --- | --- |
| Setup with Python 3.12, Bun 1.3.14, Node 24 | Passed again from a clean source snapshot with no inherited virtualenv, node_modules, database or dotenv file; lint and strict types also passed there |
| Ruff formatting/lint and frontend GTS lint | Passed |
| Strict mypy: app, engine, evaluations, MCP | Passed |
| Engine tests | 3,169 passed; 4 skipped, on both Python 3.10 and 3.12 after dependency updates |
| App tests | 2,082 passed after updates; configuration redaction added afterward and included in a passing 22-test focused regression run |
| MCP tests | 374 passed after dependency and Host-header authorization fixes |
| Frontend tests | 828 passed, including five new session-race regressions; those cases also passed after moving to a dedicated test file |
| Evaluation/parity tests | 212 passed; evidence ledger passed |
| Offline safety/citation evaluation smoke | Passed |
| Frontend production build | Passed; existing bundle-size warning remains |
| Browser tests | 18 development flows and 3 built-asset launch checks passed using system Chromium 151 |
| Production browser build isolation | Passed; all 26 normal frontend build artifacts retained identical hashes |
| Hash-pinned API/MCP runtime installs and dependency compatibility | Passed in separate clean environments |
| Locked runtime startup, API auth, MCP shared-secret boundary | Passed |
| Installed wheels outside the checkout | API/engine completed an authenticated offline durable run and report; MCP protocol initialization and tool listing passed |
| Three Python wheels, resources, Apache metadata and LICENSE/NOTICE | Passed |
| Workflow syntax and CI aggregate failure handling | Passed |
| Dependency advisory audits | Frontend, browser harness and isolated skills closure clear; remaining Python findings reviewed in [DEPENDENCY-SECURITY.md](DEPENDENCY-SECURITY.md) |
| Docker production builds | Blocked before build layers by Docker Hub unauthenticated pull limit (HTTP 429) |
| Docker build-context validation | Network-free scratch build accepted production COPY inputs; exported tree contains runtime assets and no env secrets, databases, virtualenvs, caches, or build outputs |

The managed Playwright Chromium download was blocked by the environment's
network restrictions. The documented `COSCI_E2E_CHROMIUM_EXECUTABLE` override
used the installed browser for this run. CI retains the normal managed browser.
The production build still warns about the size of its main JavaScript bundle;
browser tests do not measure performance on a slow device or connection.
Engine/MCP suites also emitted dependency warnings; passing tests do not imply
a warning-free runtime.

The dependency refresh and Host-header fixes passed the complete app, engine,
MCP and frontend suites, browser tests, and offline evaluations. The final
configuration change hides input values in rendered validation errors and
passed focused authentication/backup regressions. Packaging also passed
after these checks; generated `build/` and `dist/` trees are excluded from
type checking so creating distributions does not introduce duplicate modules.

The built-asset launch check reproduced a login failure in required-auth mode:
a delayed anonymous 401 cleared the newly established researcher session.
The shared frontend transport now invalidates only the token actually sent by
that request, if it still matches the stored session. JSON calls, downloads,
interview streams and run-event streams use this rule. The launch browser
check passed login, completed offline report retrieval after a reload, and
cross-researcher ownership isolation. It now runs in CI and `make check`.
Both browser targets disable local dotenv loading and explicitly select
offline evidence and claim checks; this is not provider-backed validation or
verification of hosted routing.
The production browser build lives in its temporary state directory and leaves
normal `dist/` artifacts untouched. CI frontend, browser and root-tooling jobs
now explicitly install Node 24.19.0, alongside the pinned Bun version.

A read-only attempt through the local GitHub CLI to verify repository settings
returned Forbidden. A later connector metadata check confirmed the repository
is private and its default branch is `main`. Private vulnerability reporting and
branch protection settings remain unverified. No account settings were changed.

## Secret scan

Gitleaks 8.30.0, with its default rules and release checksum verified, scanned
all reachable Git refs and a separate snapshot of tracked and new publication
files. Values were redacted in reports and never tested against a provider.
The local reports are outside the repository.

| Scope | Detector matches | Assessment |
| --- | --- | --- |
| Current publication tree | 383 in 121 files | 218 source/revision/scoring digests, 16 service/deployment IDs, 144 blinded evaluation item IDs, 4 fake test credentials, 1 public model route in a probe record |
| Reachable history | 851 in 282 file/rule groups | Generic detections include the metadata/fixtures above and retired third-party browser bundles. 406 detections are Google client API keys in historical browser captures. |

The history scan processed 2,115 commit diffs, approximately 690 MB, from
2,244 reachable commits. Historical captures also include third-party client
tokens and resource identifiers whose restrictions and publication rights
have not been established. A sampled HAR contained no Authorization or Cookie
request headers and no structured request cookies; this sample is not a
privacy review of every captured response or historical file.

No first-party provider credential was identified in the current detector
matches. This is a pattern scan with triage, not a clean-history certification
or a substitute for reviewing private research content and account metadata.
Retired browser captures remain reachable after deleting their current paths.
Review those archives before publishing Git history. If history must be
removed or rewritten, prepare a separate coordinated migration and preserve
the private original; changing visibility is not a history cleanup.

Reproduce the history detector pass with Gitleaks 8.30.0:

```bash
gitleaks git --log-opts=--all --redact=100 --report-format=json --report-path=/private/review/history-secrets.json .
```

A detector exit code of 1 requires triage; it is not proof that every match is
a credential. Do not suppress all reference files or all hexadecimal strings
to obtain a green report. Review new matches and keep reports private.

## Remaining release gates

- Rebuild both production images when registry pulls are available.
- Review historical browser captures, private research content, and rights to
  included papers, screenshots, protocols, and data before changing visibility.
- Configure required public authentication, private MCP shared-secret access,
  trusted proxy handling, and the documented single-API SQLite topology.
- Verify the intended deployed revision, provider routing, ownership isolation,
  restart recovery, backups, and rollback in that environment.
- Enable private vulnerability reporting and require **Required checks** in
  GitHub branch protection.

Use [LAUNCH.md](LAUNCH.md) for the release procedure and operational checks.

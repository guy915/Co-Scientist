# Lane C: retired-board handoffs

Disposition of the open notes on [optimization #238](https://github.com/guy915/Co-Scientist/issues/238)
and [shrink #240](https://github.com/guy915/Co-Scientist/issues/240), checked against
latest comments and source during the re-architecture campaign. Active tracking is
[board #332](https://github.com/guy915/Co-Scientist/issues/332).

| Old note | Disposition / recommendation | Owner |
|---|---|---|
| #238 preview deployments, health checks, monitoring, draining timeout | Latest comments confirm completion; preserve the documented deployment invariants. | Completed |
| #238 PyPI reservation | `co-scientist-engine` 0.0.1 reservation placeholder is recorded as published; the engine source remains installed editable from this repository. | Completed |
| #238 benchmark retrieval keys and artifact provenance | Retrieval keys/wiring completed in #334; landing media provenance completed in #336. The optimization session closed #238; no new live benchmark is required for this lane. | Completed |
| #238 stale performance branches | Latest comment confirms branch cleanup; temporary CI proof branches can use the existing manual prune workflow after the campaign. | Completed / maintainer |
| #238 frontend hosting move | At the chosen move, copy public `VITE_*` configuration, repoint Sentry/UptimeRobot, remove stale backend credentials from the old Vercel frontend project. Do not alter production settings during this campaign. | Owner + lane F |
| #238 retention | Document retention is 30 days; the owner wants runs kept until explicit deletion/export. The existing run default is 90 days, so use `COSCIENTIST_RUN_RETENTION_DAYS=0` before enabling a scheduled sweep. Implement daily sweeping inside the API process after re-architecture; a separate Railway cron cannot access its private mounted volume. | Owner decision + lead |
| #238 icon licensing | Root NOTICE still records unconfirmed icon provenance. Confirm the license or replace the icons before publication. | Owner + lane F |
| #238 publication/history cleanup | Enable private vulnerability reporting; preserve the immutable research archive and update pinned history links before any planned public-history reset. | Owner + lead |
| #240 extraction follow-ups | #325–#330 record the remaining complexity, CSS, typed claim, matchup and documentation work as completed; #331 records mobile keyboard focus. | Completed |
| #240 remaining evidence/hypothesis/review splits | The old session declined these for small readability gains and compatibility risk. Keep the decision unless current re-architecture establishes a concrete need. | Lead |
| #240 engine/package and Railway watch paths | ADR-001 retains `engine/src/co_scientist`; watch-path/deploy settings follow the eventual architecture, not an obsolete shrink proposal. | Lead / Owner if needed |
| #240 raw chat matchups | The chat path forwards tournament matchups, while the manifest reader expects `rationale` and engine matchups declare `reasoning`. Normalize at the boundary and add a reproduction before fixing. | Lane X / lead |
| #240 evaluation hypothesis text | The evaluation driver reads `text`, while stored hypothesis rows declare `statement`. Triage with a fixture from a real store row and normalize the input. | Lane X / lead |
| #240 retraction/correction metadata | Reference extraction copies type/title/URL/authors/year and drops `is_retracted` / `correction_status`, which the app review adapter reads. Preserve metadata and add a round-trip regression. | Lane X |
| #240 historical chat QA hydration timeout | Subsequent runs passed; route to lane F if the failure recurs. Keep hermetic tests and investigate the cause. | Lane F if reproduced |

## CI scheduling follow-up

During this audit, main run [37645023942](https://github.com/guy915/Co-Scientist/actions/runs/37645023942)
was canceled before any jobs were created. GitHub replaces pending runs in a
shared concurrency group even when `cancel-in-progress` is false. CI now gives
every non-PR run its own group; PR commits still share their branch group.
Validation commands and comprehensive main target selection remain unchanged.

## GitHub launch settings

- Synchronize `.github/labels.yml`; enable Discussions for the issue chooser.
- No merge queue (owner decision): the repository stays on a personal account.
- Import `.github/rulesets/main.json`. Replace/disable the existing
  overlapping `Default` ruleset (17522178), require only `Required checks`, and
  turn off **require branches to be up to date**. Keep PR and no-force-push rules.
- Allow squash merging only; disable merge and rebase methods in repository
  settings.
- Confirm CodeQL results in Security; enable private vulnerability reporting.

These are recommendations and handoffs. Committing this file changes no repository
or hosting settings and does not resolve the application bugs listed above.

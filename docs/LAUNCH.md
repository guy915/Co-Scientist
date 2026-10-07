# Launch readiness

Use this document for product releases. The completed reference campaign's conclusions and
immutable evidence links are preserved at [`PLAN.md` @ 33ec8984](https://github.com/guy915/Co-Scientist/blob/33ec8984c6f9292a6653cc6a661d32210f55c688/PLAN.md).
Scientific evaluations remain scoped to
their original protocols and must not be summarized as general validation.

The [1 October cleanup validation record](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/PUBLICATION-REVIEW.md) reports
completed checks, detector triage, and outstanding external release gates.

## Repository checks

From a clean checkout with the documented tooling:

```bash
make setup
make check
make docker-build
```

The first validation command runs format/lint, strict types, backend and
frontend unit suites, evaluation harness tests, offline evaluation smoke,
the production frontend build, isolated development browser tests, and a
separate built-asset check with anonymous ownership. The second builds
both production images without pushing or deploying. CI performs these
checks in separate jobs. Configure branch protection to require **Required
checks**, the aggregate job that rejects any selected failed/cancelled job.
Skipped jobs are accepted only after affected-target selection succeeds.

Production Python runtime versions and hashes live in
[`requirements/`](../requirements/README.md). Frontend and browser harness
installs use their frozen Bun locks with Bun 1.3.14. Check lock changes and
image builds whenever runtime dependencies change. CI actions are pinned;
Dependabot proposes Actions and Bun updates for review. Python runtime
updates require the documented lock regeneration and validation.

Run `make audit-deps` separately for current online advisory data. Review
[dependency guidance](../requirements/README.md) and the reachability lesson
in [operations](OPERATIONS.md); do not suppress detector findings.

## Hosting configuration

Read [DEPLOYMENT.md](DEPLOYMENT.md) and [OPERATIONS.md](OPERATIONS.md) before
changing a service. Confirm these settings on the intended release:

| Concern | Required configuration |
| --- | --- |
| Browser access | Exact frontend origins in `ALLOWED_ORIGINS`; correct `VITE_API_BASE_URL` |
| BYOK | Separate random `BYOK_ENCRYPTION_KEY` if enabled; keys stay encrypted at rest |
| Literature tools | MCP stays private; matching `COSCIENTIST_MCP_SHARED_SECRET` on both services |
| SQLite | One API replica; persistent volume for `COSCIENTIST_DB_PATH` |
| Railway volume | Preserve `RAILWAY_RUN_UID=0` until volume ownership is deliberately handled by an entrypoint |
| Models | Matching provider credentials and explicit role settings; confirm `/status`; retain free-route spend bounds |
| Notifications | Correct SMTP settings and `PUBLIC_APP_URL` if enabled |
| Operations | Retained logs, disk monitoring, private operator token, tested backups and recovery |
| Monitoring | `VITE_SENTRY_DSN` set on the new frontend host (read at build time); UptimeRobot pointed at the live URLs ([MONITORING.md](MONITORING.md)); only `VITE_` variables on the frontend host, since the old Vercel project also holds the api's secrets |

Ownership is a per-browser client ID: neither CORS nor client-selected IDs
establish identity, so treat runs as private-by-obscurity, not authenticated.
Configure trusted proxy handling for per-IP limits.

Deploy the validated revision through the established release process.
Record the commit and deployment identifiers, health/readiness results, and
rollback revision. Validate run creation, streamed progress, completion,
restart recovery, report retrieval, and ownership isolation in the intended
environment. Provider-backed verification is separate from offline CI and can
incur provider usage. A historical healthy-service receipt is not verification
of a new release.

## Backup and restore

Create a consistent SQLite backup through the backup API rather than copying
only the `.db` while its WAL may contain committed work. From the repo root:

```bash
.venv/bin/python app/dev/backup_db.py coscientist.db /private/backups/coscientist-2026-10-01.db
```

The destination directory must already exist. The helper opens the source
read-only, copies committed database and WAL pages into one standalone file,
checks integrity, applies private file permissions, and refuses to overwrite
an existing destination. A failed backup leaves no published backup file.
`--timeout` bounds the copy (default 30 seconds); choose an appropriate value
for the database size. This helper imports no serving-process code and runs no
VACUUM or truncating checkpoint. For production, run it in an operator context
with access to the mounted database, adapting the source and destination paths.

Backups contain researcher data and encrypted credentials. Store them outside
the repository/build context, protect access, define retention, and retain the
matching BYOK encryption key separately. The source DB path and sidecars must
never be committed or shared as diagnostic attachments.

Restore into an isolated location first and verify `PRAGMA integrity_check`,
run counts, checkpoints, reports, and access isolation. For an actual rollback,
stop all writers, retain the old database and sidecars as a recovery copy, and
restore the standalone backup with correct ownership. Do not combine a restored
DB with WAL/SHM files from another snapshot. Restart one API process and verify
recovery before admitting new work. Reverting code alone does not revert schema
or persisted state; validate compatibility before restoring an older release.

## Public repository prerequisites

The first-party software is Apache 2.0; [NOTICE](../NOTICE) and the vendored
license files preserve third-party terms. Review the rights for included paper
excerpts, screenshots, protocols, and data independently of the software license.
The favicon and app icons come from an unidentified icon set (see NOTICE):
identify its license or replace the mark before publication.

Before changing repository visibility, review **all reachable Git history**
for secrets and private researcher data, rotate any discovered credentials,
and resolve any redistribution restrictions. `.gitignore` and `.dockerignore`
protect future local artifacts; they do not remove prior commits. Enable
private vulnerability reporting and require the CI aggregate check in GitHub.
These account/repository settings are external launch prerequisites.

Offline passing checks establish implementation behavior, not external model
quality, expert agreement, biological safety, or wet-lab effectiveness. Keep
these limits visible in launch copy and evaluate scientific outcomes separately.

# Launch readiness

Use this checklist for each release. Scientific evaluations stay scoped to
their own protocols and must not be summarized as general validation.

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
| Monitoring | `VITE_SENTRY_DSN` set on the frontend host (read at build time) and uptime checks on the live URLs ([MONITORING.md](MONITORING.md)) |
| Frontend host | Only `VITE_` variables: everything there is compiled into public assets |

Ownership is a per-browser client ID: neither CORS nor client-selected IDs
establish identity, so treat runs as private-by-obscurity, not authenticated.
Set `COSCIENTIST_TRUSTED_PROXY_CIDRS` and check it before you open admission
([trusted visitor addresses](TRUSTED-PROXY.md)).

Deploy the validated revision through the established release process.
Record the commit and deployment identifiers, health/readiness results, and
rollback revision. Validate run creation, streamed progress, completion,
restart recovery, report retrieval, and ownership isolation in the intended
environment. Provider-backed verification is separate from offline CI and can
incur provider usage. A historical healthy-service receipt is not verification
of a new release.

## Launch runbook

The launch moves the code to https://github.com/guy915/Open-Co-Scientist with
a single initial commit, the frontend and DNS to Cloudflare, and the API and
MCP server to a new Railway project. Production starts with an empty database.
Run the steps in order; each ends with a check.

1. **Freeze.** Merge or close every open pull request in this repository, run
   `make check` and `make docker-build` on `main`, and confirm the tree has no
   secrets, databases or run outputs.
2. **Publish the code.** Export `main` without history (for example,
   `git archive main` into an empty directory), create one initial commit and
   push it to the new repository. Check that `NOTICE`, the package `NOTICE`
   and `LICENSE` copies and `vendor/` arrived unchanged.
3. **Configure the repository.** Enable Discussions and private vulnerability
   reporting, apply `.github/labels.yml`, import `.github/rulesets/main.json`
   and allow squash merges only. Add the repository secrets the manual
   workflows need (see [CI](CI.md)). Check that CI passes on the initial
   commit.
4. **Start the API and MCP server.** In the new Railway project, create the
   `api` and `mcp` services from the root Dockerfiles, with a volume at
   `/app/data`, `RAILWAY_RUN_UID=0` and exactly one API replica
   ([deployment](DEPLOYMENT.md)). Set matching `COSCIENTIST_MCP_SHARED_SECRET`
   values, the model credentials, `BYOK_ENCRYPTION_KEY`, `LOGS_ADMIN_TOKEN`
   and `ALLOWED_ORIGINS=https://open-coscientist.com`, plus the
   `LITESTREAM_R2_*` credentials for replication to R2
   ([deployment](DEPLOYMENT.md#database-replication-optional)). Check
   `https://api.open-coscientist.com/health` and `/status`.
5. **Start the frontend.** Deploy the Cloudflare Worker in `wrangler.jsonc`
   from a build with `VITE_API_BASE_URL=https://api.open-coscientist.com`
   and `VITE_SENTRY_DSN` ([deployment](DEPLOYMENT.md#frontend)). Point DNS at it. Check deep links, a report reload
   and a full Express run.
6. **Remove the pre-launch setup.** Merge the pull request that drops the old
   origins and hosting files, then repeat the step 4 and 5 checks.
7. **Watch.** Point uptime checks and error tracking at the new URLs
   ([monitoring](MONITORING.md)) and take the first backup
   ([backup and restore](#backup-and-restore)).
8. **Retire the old repository.** Make it private only after the new
   deployment has served real runs.

## Backup and restore

With R2 replication on, the API verifies a fresh backup every day
([deployment](DEPLOYMENT.md#database-replication-optional)). Take manual
backups as well before risky changes.

Create a consistent SQLite backup through the backup API rather than copying
only the `.db` while its WAL may contain committed work. From the repo root:

```bash
.venv/bin/python app/dev/backup_db.py coscientist.db /private/backups/coscientist-YYYY-MM-DD.db
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

Before publishing, scan the tree for secrets and private researcher data and
rotate anything found. `.gitignore` and `.dockerignore` protect future local
artifacts only. Enable private vulnerability reporting and Discussions, apply
`.github/labels.yml` and import `.github/rulesets/main.json` so the CI
aggregate check is required.

Offline passing checks establish implementation behavior, not external model
quality, expert agreement, biological safety, or wet-lab effectiveness. Keep
these limits visible in launch copy and evaluate scientific outcomes separately.

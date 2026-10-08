# Local Litestream restore drill

Run this before launch and after changing the backup format or API startup.
It creates a synthetic application database, backs it up to a local file
replica, restores into a separate scratch file and starts one offline API on
loopback. It never opens an existing database or an R2 replica.

## Procedure

Run `make setup` with Bun 1.3.14 first. Obtain Litestream **0.5.17**, the
version pinned in `Dockerfile.api`, for your host from the
[release](https://github.com/benbjohnson/litestream/releases/tag/v0.5.17).
Verify its archive against the release's `checksums.txt` before extracting.
The Linux x86_64 archive used for this drill has SHA-256
`cfb371176d164437ae869f8351cfde49bd1804ae71c61923f75c9cba9c9c006d`.

From the repository root, with the absolute path to that binary:

```sh
.venv/bin/python scripts/operations/restore_drill.py --litestream /absolute/path/litestream
```

The command creates a private `cosci-restore-drill-*` directory under the
system temporary directory. Use `--scratch-parent /absolute/scratch/directory`
to choose another parent. It preserves the fixture, local replica,
configuration, API log and JSON receipt there for inspection.

The script performs these steps, stopping on an error:

1. Initialize the actual application schema and a synthetic marker in
   `source.db`. No research task is queued.
2. Run `litestream replicate -config <scratch>/litestream.yml -once` with a
   file replica and `truncate-page-n: 0`.
3. Start the recovery timer and run
   `litestream restore -o <scratch>/restored.db file://<scratch>/replica`.
   Verify `PRAGMA integrity_check` and the original marker using a read-only
   connection.
4. Start one API with the restored database on an ephemeral 127.0.0.1 port.
   The child runs in scratch with an environment allowlist: forced offline
   execution, LiteLLM's local-only cost catalog, disabled tracing and no
   inherited provider, SMTP, Sentry, proxy or Python-path settings. No
   repository dotenv file is loaded.
   SQLite application checkpoints remain disabled as under Litestream.
5. Poll `/health` until healthy, with a 60-second readiness deadline. Record
   restore-only and restore-to-healthy elapsed time.
6. Stop the API, verify integrity and the marker again, then publish
   `receipt.json`. Failed startup leaves the scratch logs and no success
   receipt. The script terminates its child even when readiness fails.

Inspect the receipt and logs before deleting only the reported scratch
directory. Never substitute the production volume or an existing database
for the synthetic source or restored target.

## Measured receipt

On 8 October 2026, Linux x86_64, Litestream 0.5.17, this procedure exited
**0**. Restore took **0.033 seconds**; restore through healthy API took
**3.339 seconds**. SQLite integrity was `ok` before and after API startup and
shutdown, and the original marker survived. No provider call, production
data access or hosting change occurred.

This small fixture validates the local restore/startup procedure. It does
not measure production RTO, backup freshness/RPO, R2 credentials/network
availability, researcher ownership, encrypted BYOK recovery, checkpoint
compatibility or full-sized database recovery. An operator restoring an
actual backup must separately verify those against an isolated, compatible
release before replacing any store; see
[backup and restore](LAUNCH.md#backup-and-restore). Keep the database and its
matching encryption key private. Stop all writers for actual replacement,
retain the old database and sidecars together, never pair a restored DB
with another snapshot's WAL/SHM, and restart exactly one API writer.

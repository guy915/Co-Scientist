# Phase 3: DBOS prototype results

Branch `proto/dbos` (never merged), base `main` @ `35d68bf`. DBOS 3.2.0,
system tables in the app's SQLite file. Each check below has a script in
this directory and its raw output in `results/`. Every experiment uses the
offline backend and a fake reviewer (`harness.install_fake_review`) that
logs each provider call to a JSONL file *before* it waits, so a call counts
even when the process dies mid-call.

**Recommendation: no-go.** Checks 3, 5 and 6 fail. Keep the hand-built
runtime behind one `orchestration.runtime` interface (ADR-003).

## What was ported

Behind `COSCIENTIST_DBOS_REVIEW` (`1` = every run, `stamped` = runs created
with `durable_runtime: dbos`), the review node starts one DBOS parent
workflow, `review:{run}:{checkpoint_seq}`, instead of enqueueing item and
aggregate rows.

- **Parent workflow.** Starts one child workflow per unreviewed hypothesis,
  in a fixed order so that step numbering replays deterministically.
- **Child workflows.** Each runs its attempts sequentially.
- **Commit step.** The parent's last step writes the checkpoint and enqueues
  the successor through the existing portfolio code, fenced by run liveness
  and an unchanged checkpoint.
- **Hooks into the old queue** (27 lines):
  - The node dispatch routes review to DBOS.
  - `cohort_poll` and startup discovery count a pending review workflow as
    live work.
  - The lifespan launches DBOS from a worker thread.
  - Run cancel cancels the run's workflows.

Code: `app/app/dbos_proto/__init__.py` (147 lines), `review.py` (471).

Everything the checks required beyond plain DBOS had to be written into the
port:

| Rule | DBOS alone | Port adds |
|---|---|---|
| Unknown provider outcome fails closed | Steps are at-least-once: a killed step replays its call | Issuance marker per invocation (own table) |
| Rate-limit park spends no retry | n/a | Durable `DBOS.sleep_async` and attempt bookkeeping |
| Zero-cost timeout waits the outage backoff | Fixed-interval step retries | Durable sleep of `provider_outage_backoff_seconds` |
| Cancel stops new and in-flight calls | Cancellation is checked at step boundaries | Cancel hook, `preemptible=True`, run-liveness read before each call |
| Call budget, BYOK and zero-cost scopes | Recovered workflows start with no app scopes | Each workflow re-enters the scopes |
| Recovery across deploys | Version = hash of workflow source, so each deploy strands in-flight work | Pinned `application_version` |

## Results

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Kill mid-fan-out, resume with no duplicate calls and no lost results | **Pass** (only with the port's issuance marker) | 5 kill points, unstamped run: 0 duplicate calls, 0 lost recorded results; resume to commit 1.2–5.8 s (hand-built: 293 s). DBOS alone: 4 duplicate calls |
| 2 | Leases, retry budgets, future-due tasks, steering as OPERATIONS requires | **Pass** for a single process | 8 scenarios match today's rules. Under process overlap DBOS re-executes live workflows (4 duplicate calls). Railway cannot overlap volume-backed deploys, so production is safe today |
| 3 | Shares the SQLite file safely | **Fail** | Idle with no workflows: 118 write transactions in 60 s (2/s) from two DBOS threads; hand-built: 0. No long write locks, no VACUUM or checkpoint, WAL kept |
| 4 | Startup cheap, recovery off the port path | **Pass** | `DBOS.launch()` 0.03–0.13 s; spawn-to-healthy +0.7–0.9 s (mostly the 0.75–0.91 s `import dbos`); recovered calls start 1.06 s after `/health` answers, on DBOS's loop |
| 5 | Works with the cohorts' separate event loops, no shared asyncio primitive | **Fail** | One cohort loop that awaits any async DBOS API, then exits, breaks DBOS process-wide. All DBOS work runs on one shared loop (lag max 392 ms with 3 small runs); launched from a running loop it runs on the API loop |
| 6 | Moving every phase deletes ≥ 1.5k lines net | **Fail** | Central estimate −755 production lines (−580 to −900); about −1,550 only if every contested line is deleted and the port is built at minimum size |
| 7 | Cutover path for in-flight runs | **Pass** | See below |

### 1. Kill mid-fan-out (`check1_kill.py`)

The real app process (lifespan, startup recovery, cohorts) runs a seeded run
at the review node: 12 hypotheses, 4 slots, 2 s per call. It is SIGKILLed
after K calls finish, then restarted, and the script waits for the review
workflow to finish. "Lost result" means a step output DBOS had durably
recorded before the kill that is missing from the committed checkpoint.

| Run | K | In flight at kill | Calls | Duplicates | Lost | Reviewed | Failed closed | Resume to commit |
|---|---|---|---|---|---|---|---|---|
| unstamped | 1 | 3 | 12 | 0 | 0 | 8 | 4 | 5.8 s |
| unstamped | 4 | 3 | 11 | 0 | 0 | 8 | 4 | 3.8 s |
| unstamped | 6 | 3 | 11 | 0 | 0 | 8 | 4 | 3.3 s |
| unstamped | 9 | 3 | 12 | 0 | 0 | 9 | 3 | 1.2 s |
| unstamped | 11 | 1 | 12 | 0 | 0 | 11 | 1 | 1.2 s |
| zero-cost | 6 | 3 | 16 | 4 (allowed: lost leases may retry under zero-price admission) | 0 | 12 | 0 | 5.6 s |
| unstamped, **no marker** (DBOS alone) | 6 | 3 | 16 | **4** | 0 | 12 | 0 | |
| hand-built baseline | 6 | 6 | 12 | 0 | — | 6 | 6 | **293 s** (waits for lease expiry) |

- **Failed closed** counts the items in flight at the kill. It also counts
  an item whose slot was taken and marker issued but whose call had not yet
  logged, and one whose call returned just before its output was recorded.
  These are the same windows the expired-lease rule fails today.
- **Restart re-runs the review node.** Startup resume re-enqueues the node
  task. It reattaches to the same workflow id and no call repeats (DBOS logs
  "Workflow already exists").

### 2. OPERATIONS rules (`check2_rules.py`, `check2_park_restart.py`, `check2_baseline_cancel.py`, `check1_kill.py overlap`)

| Scenario | Calls | Outcome | Rule |
|---|---|---|---|
| Item fails 3 times; another fails twice then succeeds | 3, 3, 1, 1 | first `review_failed`, second reviewed, commit | retry budget of 3, sibling isolation |
| Call budget exceeded | 1 per item, no retry | run `failed`, no checkpoint, no successor, budget released | budget is a permanent failure |
| Rate-limit park, then 3 ordinary failures | 4 (park spends no attempt) | cohort stays alive during the park (`active=True`); startup discovery lists the run | future-due work keeps its cohort |
| Park, SIGKILL during the 20 s park, restart | 2 | the second call came 30.1 s after the park, from the restarted process (jitter ≤ 15 s) | not-before survives restart |
| Unknown provider outcome (timeout, not zero-cost) | 1 | item fails, siblings commit, run continues | no replay, no sibling cancel |
| Zero-cost timeout | 2, the second after 26 s | reviewed | outage backoff (`provider_outage_backoff_seconds(1)` ≈ 16–27 s) |
| Run cancelled with 4 in flight and 4 queued | 0 new calls; 4 in-flight cancelled | no checkpoint, no successor | hand-built: 0 new calls, 4 in-flight run to completion |
| Steering sent during review | — | review commit leaves it pending (1) | only the orchestrator acknowledges steering |
| **Two processes on the file** (deploy overlap), 6 s calls | unstamped: 12 calls but 4 items needlessly failed; zero-cost: **16 (4 duplicates)** | the second process's recovery re-executes the first's live workflows | leases forbid running one boundary twice |

DBOS has no ownership lease on SQLite. Recovery takes every `PENDING`
workflow of its executor id at launch and assumes the owner is gone. Railway
docs: "services with an attached volume cannot run two deployments at once",
so production cannot overlap today. Two local processes on one file can.

### 3. SQLite sharing (`check3_sqlite.py`)

The real app ran with every statement on every app and DBOS connection
traced (`serve.py`). An outside writer probed `BEGIN IMMEDIATE` every 100 ms.

| | DBOS idle (60 s) | Hand-built idle | DBOS fan-out | Hand-built fan-out |
|---|---|---|---|---|
| Write transactions | **118 (1.97/s)** | 0 | 63 DBOS + 26 app in 7 s | 28 in 5.1 s |
| Longest write transaction | 3.9 ms | — | 16.5 ms | 59.4 ms |
| Outside writer wait p99 / max | | | 1.1 / 8.5 ms | 0.4 / 1.3 ms |
| VACUUM, `wal_checkpoint`, `journal_mode`, `synchronous` | none | none | none | none |
| Journal mode after | | | wal | wal |

The idle writes (`results/check3_idle_statement_counts.txt`) are each one
`BEGIN IMMEDIATE`, one `UPDATE`, one `COMMIT`, once a second, every second
the process lives:

- `dbos-workflow-timeout`: `UPDATE workflow_status SET status='CANCELLED' …`
  (the timeout sweep; interval `_SWEEP_POLLING_INTERVAL_SEC = 1`, a module
  constant, not configurable).
- `queue_thread`: `UPDATE workflow_status SET status='ENQUEUED' …` for the
  internal queue.

This is the "write on every poll tick" OPERATIONS forbids. Removing it means
patching DBOS internals. The rest of the check holds:

- **Network I/O:** no write lock was held across a provider call. Steps run
  outside transactions, and the longest write was 16.5 ms against 2 s calls.
- **Maintenance:** no maintenance statements were issued.
- **Single writer:** writes serialise through `BEGIN IMMEDIATE`.

DBOS logs at launch that its SQLite system database "is for development and
testing. PostgreSQL is recommended for production use."

### 4. Startup (`check4_startup.py`)

Medians of 3 boots, from spawn to `/health` 200:

| Database | DBOS | Hand-built | `DBOS.launch()` |
|---|---|---|---|
| Fresh (DBOS migrates) | 8.00 s | 7.09 s | 0.133 s |
| 3,913 workflows / 11,137 step rows of history | 7.42 s | 6.70 s | 0.029 s |

- **Cost breakdown:** the difference is mostly `import dbos`, which takes
  0.75–0.91 s on top of `app.main`. The launch itself is cheap. The import
  could move into the off-path recovery task.
- **Recovery off the port path:** a SIGKILLed fan-out with 10 s calls
  restarted healthy in 6.87 s. Its 8 recovered calls began 1.06 s *after*
  `/health` answered and ran on DBOS's background loop.
- **Other startup work:** `launch()` runs migrations and registers the app
  version inline, which is cheap.

### 5. Event loops (`check5_loops.py`, `check5_executor.py`)

Three runs, each driven by its own real cohort thread, reached review
together.

- **Off-loop launch (the prototype's lifespan):** all 30 calls ran on one
  loop, DBOS's background loop, not the three cohort loops. There were 0
  cross-loop errors and all three committed. Lag on that loop: p50 22 ms,
  max 392 ms. Every run's DBOS work shares one loop and one thread, which
  undoes the per-run isolation the cohorts give today.
- **Launched from a running loop:** all 30 calls ran on the API loop.
  Recovery would then compete with request handling, which startup rules
  forbid.
- **Shared executor (`check5_executor.py`):** any async DBOS API calls
  `loop.set_default_executor(<DBOS's process-wide pool>)` on the calling
  loop. When a cohort's `asyncio.run` returns, it shuts that default
  executor down. Every later DBOS call in the process then fails:

  ```
  {"before_cohort_exit": 2, "after_cohort_exit": "RuntimeError: cannot schedule new futures after shutdown"}
  ```

  The prototype hit this in its own test driver. It avoids it only by never
  awaiting a DBOS async API on a cohort loop, a rule nothing enforces. It is
  the same class of bug as the ranking semaphore incident: state bound to
  one loop leaking across the cohorts' loops.

### 6. Lines (`results/check6_inventory.md`)

| | Lines |
|---|---|
| Deleted if every phase moved (gross) | 1,885 |
| Adapter code added, extrapolated from the measured review port | ~1,130 (990–1,310) |
| **Production net** | **−755** (−580 to −900) |
| Tests net | about −460, plus ~1,150 lines to rewrite |

These counts:
- **Per-family growth:** the review port alone is 618 lines plus 27 lines of
  hooks, and it grew by 47 lines while fixing what checks 1–2 found.
- **Where the bar is met:** about −1,550 only if ~650 contested lines
  (supervisor queue actions, safety-hold parking, pause and cancel
  semantics, run settlement) all count as deleted.
- **Dependencies:** DBOS adds `sqlalchemy`, `psycopg`, `psycopg-binary`
  (an unused Postgres client), `greenlet`, `python-dateutil` and `six`. That
  is about 239 hash lines (+7.6%) in `requirements/api.txt` and about 55 MB
  installed.
- **Serialization:** DBOS pickles step outputs and errors by default.

### 7. Cutover (`check7_cutover.py`)

CHECK7_RESULT

Cutover steps:

1. **Ship dark.**
   - Add `dbos` to `app/requirements-app.txt` and `app/pyproject.toml`, and
     regenerate the hash locks.
   - Launch DBOS in the lifespan from a worker thread, after reconcile and
     before the recovery task.
   - Pin `application_version`; bump it only when a workflow's step order
     changes.
   - The flag stays off. DBOS creates its tables in the same file
     (idempotent migrations; no name collisions with the 31 app tables).
2. **Stamp at creation.** With the flag in `stamped` mode, `create_run`
   writes `durable_runtime: dbos` into the run config, in the create
   transaction. Routing reads the stamp per run, never a process flag. An
   unstamped run uses the hand-built queue for its whole life: resume,
   safety-hold release, retry and startup recovery included.
3. **Run both.** One process serves both: cohorts for unstamped runs and
   DBOS for stamped ones. Startup reconcile and recovery cohorts still run
   for legacy work, and `DBOS.launch()` recovers stamped work.
   `cohort_poll` and startup discovery treat a pending DBOS workflow as live
   work for hybrid runs.
4. **Drain.** Watch `DRAIN_QUERY` in `check7_cutover.py`: live
   `scientific_tasks` rows of non-terminal, unstamped runs. Paused runs and
   safety holds awaiting a human can stay non-terminal indefinitely. After
   a fixed window, either fail them with a clear status or move them: a
   checkpoint is runtime-neutral (it persists `resume_successor`), so
   stamping such a run and re-entering at its last checkpoint resumes it on
   DBOS.
5. **Delete.** When the drain query returns 0, one PR deletes the
   hand-built runtime (the files in `results/check6_inventory.md`) and the
   routing. The `scientific_tasks` table stays read-only until no reader
   (progress, diagnostics, supervisor queue snapshot) uses it; a later
   migration drops it.
6. **Roll back.** Before step 5, setting the flag off stops new stamping.
   Stamped runs in flight still need DBOS, so its code stays until they
   drain too.

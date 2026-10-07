# ADR-003: Durable runtime — keep the hand-built one

**Status:** accepted, 7 October 2026. Re-architecture phase 3, from lane P's
prototype report (campaign board #332; branch `proto/dbos` at `c955a29`,
never merged; evidence in `proto/dbos/RESULTS.md` on that branch).

## Context

Runs execute through a hand-built durable runtime: `scientific_tasks` rows
with leases, idempotency keys, retry budgets, parks and checkpoints, drained
by one worker cohort per run inside the API process (`engine_tasks/`,
`task_worker/`, `store/tasks*.py`). DBOS ships checkpointed steps, durable
queues and retries on SQLite, so the plan time-boxed one prototype: port the
review fan-out to DBOS and adopt it only if all seven checks pass.

## The prototype

The review fan-out ran on DBOS 3.2.0 with its tables in the app's SQLite
file, behind a flag, as one parent workflow per review commit, one child per
hypothesis and one commit step (642 lines plus 25 lines of hooks). It was
tested in the real app process with the offline backend and a fake reviewer
that logs every provider call.

| # | Check | Result |
|---|---|---|
| 1 | Kill mid-fan-out: no duplicate calls, no lost results | Pass, but only with an issuance marker the port added; DBOS alone made 4 duplicate calls (steps are at-least-once) |
| 2 | Leases, retry budgets, future-due tasks, steering | Pass in one process; with two processes on the file DBOS recovery re-executes live workflows |
| 3 | Shares the SQLite file safely | **Fail**: 118 write transactions a minute while idle (timeout sweep and queue thread), a write on every poll tick |
| 4 | Cheap startup, recovery off the port-binding path | Pass |
| 5 | Works with the cohorts' separate event loops | **Fail**: DBOS installs one process-wide executor as each loop's default; when a cohort's loop exits, every later DBOS call in the process fails |
| 6 | Moving every phase deletes at least 1.5k lines net | **Fail**: about −755 production lines (range −580 to −900) |
| 7 | Cutover path for in-flight runs | Pass: stamped runs on DBOS and legacy runs on the queue recovered side by side |

## Decision

**Keep the hand-built runtime.** Three checks fail, and the plan allows no
second library in this campaign.

**Put it behind one interface, `co_scientist.orchestration.runtime`.** The
phase 4 moves place the queue (`store/tasks.py`, `store/tasks_lifecycle.py`),
the worker cohort (`task_worker/`), the task executor (`engine_tasks/`) and
recovery under `orchestration`. Phase 5 then gives the runtime one public
interface: enqueue, claim and lease, commit with checkpoint and successor,
park, retry, fail, cancel and recover. Workflow code (nodes, fan-out
phases, the run lifecycle) uses only that interface, and only the runtime
touches the `scientific_tasks` and `checkpoints` tables.

## Consequences

- No new dependencies, no second scheduler on the SQLite file, and every
  invariant in `docs/OPERATIONS.md` keeps its current implementation.
- What DBOS did better stays a known gap, not a goal of this campaign:
  recovery in seconds rather than after the 300-second lease, durable sleep
  for parks, and cancelling in-flight calls. Each would be a behavior change
  with its own benchmark.
- Revisit only if the store moves off single-writer SQLite (a non-goal) or a
  library passes checks 3, 5 and 6; the prototype's check scripts can be
  rerun from the branch.

# Check 6: net lines deleted if every phase moved to DBOS

Source: working tree of `proto/dbos`, base `main` @ `35d68bf`. Whole-file
counts with `wc -l`; partial files counted per function from the AST
(`end_lineno - start_lineno + 1`, decorators and leading comment included).

## Deleted production code (after cutover)

| File: functions | Lines | Why DBOS takes it over |
|---|---|---|
| `store/tasks.py`: `_insert_task_row`, `NewTask`, `_task_row_values`, `enqueue_task`, `_dependencies_complete`, `_rescue_expired_leases`, `_queued_tasks_query`, `_try_lease_task`, `claim_task`, `list_active_engine_task_run_ids` | 153 | queue, claim, dependencies, rescue, recovery discovery |
| `store/tasks_lifecycle.py`: `complete_task`, `renew_task_lease`, attempt-history helpers, readiness SQL, `_has_claimable_task`, `has_task_of_type`, queue health, `cohort_poll`, `park_task_for_rate_limit`, `_revive_task_row`, `revive_task_for_retry`, dead-lease functions | 348 | leases, heartbeat, retry bookkeeping, durable sleep |
| `store/models.py`: `_decode` | 26 | row decoding |
| `task_worker/__init__.py`: heartbeat, lease-lost wrapper, `_run_claimed_task`, `run_once`, cohort loop, pool, idle exit | 221 | worker cohort |
| `task_worker/enqueue.py`: all but `enqueue_run_workflow` | 261 | resume-task discovery |
| `task_worker/outcomes.py`: lease and park plumbing, downstream-cancel helpers, `_record_success` | 62 | |
| `engine_tasks/__init__.py`: dispatch table | 25 | task-type routing |
| `engine_tasks/support.py`: `ExactSuccessor`, `_require_item_task`, `assert_task_commit_allowed`, exact-successor enqueue | 82 | successor enqueue, lease fence |
| `engine_tasks/portfolio.py`: lookahead enqueue, stale-chain cancel | 115 | task chaining |
| `engine_tasks/fanout.py`: item and aggregate row enqueue | 183 | fan-out scheduling |
| `engine_tasks/fanout_aggregates.py`: `_AggregateSpec`, `_enqueue_aggregate_task` | 32 | |
| `engine_tasks/ranking.py`: match-chain enqueue | 42 | |
| `engine_tasks/node.py`, `engine_tasks/inputs.py`: portfolio predecessor check, bootstrap enqueue | 54 | |
| `store/runs.py`, `safety/__init__.py`: lease matchers and guard | 34 | |
| `runs/lifecycle.py`, `main.py`, `store/runs_views.py`: resume workers, startup reconcile | 168 | recovery at `DBOS.launch()` |
| `store/schema.py`: `scientific_tasks` DDL, retired-outcome migration | 79 | only after old runs drain |
| **Gross** | **1,885** | |

Stays (not counted): `store/checkpoints.py` (the scientific checkpoint the UI,
Q&A and reports read), run settlement, `fail_task`, steering, safety holds,
pause and cancel semantics, supervisor queue actions and
`_durable_queue_snapshot` (the supervisor agent reads the queue), budgets,
fail-closed rules.

## Added adapter code

Measured on the prototype: the review port is 618 lines
(`dbos_proto/__init__.py` 147, `review.py` 471) plus 27 lines of hooks in
`node.py`, `main.py`, `runs/lifecycle.py`, `store/tasks.py` and
`store/tasks_lifecycle.py`. It grew from 571 to 618 lines while fixing what
the checks found (park keys, outage backoff, cancel, preemption).

| Added | Lines |
|---|---|
| Shared: launch, scopes, issuance markers, task view, failure classes, commit fence, budget stop, slots, cancel | ~300 |
| Four fan-out families (~130 each; ~240 total with one generic primitive) | 240–560 |
| Ranking match loop | ~70 |
| Node-task loop | ~80 |
| Bootstrap, finalize | ~60 |
| Pause/hold/resume, progress without `scientific_tasks`, supervisor queue emulation, reconcile, email workflow | ~255 |
| **Total** | **~1,130 (990–1,310)** |

## Net

| | Lines |
|---|---|
| Production, central | **−755** (−580 to −900) |
| Production, every arguable line deleted and minimum port | about −1,550 |
| Tests: delete 959, add 400–700 kill/resume tests | about −460 |
| Tests to rewrite rather than delete | ~1,150 |

The 1.5k bar is met only if about 650 contested lines (supervisor queue
actions, safety-hold parking, pause and cancel semantics, run settlement) are
counted as deleted and every family is ported at the minimum size. The
prototype shows the opposite pressure: each OPERATIONS rule the checks
exercised added code to the port.

## Dependencies

`dbos` 3.2.0 adds `sqlalchemy`, `psycopg`, `psycopg-binary`, `greenlet`,
`python-dateutil`, `six` to `requirements/api.txt` (~239 hash lines, +7.6%;
`websockets`, `click`, `pyyaml` are already there). About 55 MB installed;
`psycopg-binary` is an unused Postgres client.

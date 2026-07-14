# Failure-recovery evaluation

**Date:** 2026-07-14
**Scope:** durable scientific-task queue, worker leases, checkpoint/resume,
and the report-publication path (`app/app/store/tasks.py`,
`app/app/task_worker.py`, `app/app/engine_tasks.py`,
`engine/src/co_scientist/checkpoint.py`).

## Purpose and honest boundaries

This report documents the failure and recovery behavior that the durable
substrate guarantees, backed by named automated tests that exercise each
scenario. It is a **reconstruction** of the durability properties disclosed for
Google Co-Scientist (persistent context memory, restart-after-failure); it does
**not** claim parity with Google's undisclosed production queue, worker
topology, or infrastructure SLOs. The tests run against a single-host SQLite
queue with multiple worker processes/threads — not a distributed multi-machine
executor. Long-duration production soak behavior is environment-specific and is
not asserted here.

Two failure classes are distinguished throughout:

- **Transient failure** (provider timeout, tool error): retried with bounded
  attempts, then the task fails terminally and its evidence is preserved.
- **Optimistic-concurrency obsolescence** (a superseded checkpoint after a
  newer branch already won): completed idempotently, not treated as a scientific
  failure.

## Scenarios and evidence

| # | Failure injected | Required behavior | Test |
|---|---|---|---|
| 1 | Two processes claim the same ready task | Exactly one lease winner | `test_task_queue.py::test_multi_process_claim_has_single_lease_winner` |
| 2 | Duplicate completion of the same task (redelivery) | Exactly one committed effect | `test_task_queue.py::test_multi_process_duplicate_completion_commits_one_effect` |
| 3 | Worker process crashes mid-task, then restarts | Lease is redelivered and the task completes once | `test_task_queue.py::test_crashed_process_lease_is_redelivered_after_restart` |
| 4 | Lease expires without a heartbeat | Task is recovered and re-claimable | `test_task_queue.py::test_expired_lease_is_recovered` |
| 5 | Owner renews a live lease | No spurious redelivery while work is in flight | `test_task_queue.py::test_owned_lease_can_be_renewed_without_redelivery` |
| 6 | Transient task failure repeats | Bounded retries, then terminal failure (no infinite loop) | `test_task_queue.py::test_failure_retries_then_stops` |
| 7 | Idempotent enqueue of the same workflow/task | No duplicate task rows | `test_task_queue.py::test_enqueue_is_idempotent`; `test_task_worker.py::test_enqueue_workflow_is_idempotent` |
| 8 | Run cancelled while tasks are queued and leased | Queued and leased work revoked; late acks rejected | `test_task_queue.py::test_cancel_run_tasks_revokes_queued_and_leased_work` |
| 9 | Run paused then resumed | Queued tasks become non-claimable, then reclaimable | `test_task_queue.py::test_pause_and_resume_make_queued_tasks_non_claimable` |
| 10 | API/worker restart mid-run | Resume from the last committed checkpoint; completed LLM/tool work is reused, not repeated | `test_resume_engine.py::test_engine_resume_does_not_repeat_completed_llm_calls`; `test_resume.py::test_interrupted_run_is_resumable_and_completes_once` |
| 11 | Superseded checkpoint after a newer branch won | Idempotent completion, not a retryable scientific failure | `test_task_worker.py::test_worker_completes_superseded_engine_task` |
| 12 | Lease revoked while a long task executes | Execution is interrupted at a safe boundary | `test_task_worker.py::test_worker_cancels_execution_after_lease_revocation` |
| 13 | One fan-out child fails in isolation | Sibling work and the aggregate proceed | `test_task_worker.py::test_worker_isolates_unknown_task_failure`; `test_engine_tasks.py::test_review_aggregate_is_ready_after_isolated_child_failure` |
| 14 | Resume re-publishes a report | One report; task history and scientist input preserved | `test_resume.py::test_publication_replay_preserves_task_history_and_scientist_input`; `test_engine_drain.py::test_resumed_finalize_does_not_double_publish` |
| 15 | Resume reconstructs terminal artifacts | Identical terminal artifacts (no duplicate hypotheses/reviews/matches) | `test_resume.py::test_resume_reconstructs_identical_terminal_artifacts` |

## Real-run corroboration

The 2026-07-13 real-provider soak (run `95b46092`, DeepSeek via LiteLLM)
exercised scenarios 3, 4, and 11 in production: startup recovery reclaimed an
interrupted run, and two obsolete tasks that had exhausted retries with
"checkpoint was superseded" motivated the idempotent-completion fix (commit
`c2ac6c3e`). On 2026-07-14 two real runs (`ea0a3198`, `973ed7cd`) executed
concurrently through the same durable queue without cross-run interference.

## Result

All scenarios above are covered by passing automated tests (see the
verification log in `fidelity_closure_overrides.json` for the aggregate suite
count on 2026-07-14). The residual gap is scale: these guarantees hold for a
single-host multi-worker SQLite deployment; distributed-executor behavior is an
evidence-bounded reconstruction, not a verified property.

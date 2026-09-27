# Space Bunny same-run recovery procedure and outcome

Run: `5edffdcc-aac9-4ea2-b722-a1986dce3cca`
Instance: `20260927T090631Z-85c16b`
Database: `.remember/tmp/space-bunny-run/instances/20260927T090631Z-85c16b/coscientist.db`

The run has 73 completed durable tasks and one failed task. Its latest checkpoint is sequence 30, written by completed task `7f8368da-8117-4b23-9306-ea95e8511103`; the checkpoint records `engine.node.research_overview` as its successor. The failed row is task `e6170f9f-8395-46bd-9873-3e662b79b6eb`, at attempt 3/3, with idempotency key `engine.node.research_overview:after:7f8368da-8117-4b23-9306-ea95e8511103`.

## Preconditions

Proceed only after the coordinator confirms the `authors=None` code fix is committed and verified, then independently rechecks that OpenRouter currently admits this exact model at zero prompt and completion price. The launcher's built-in `verify_provider_pin()` checks the checked-out static route and zero-price cap; it does not perform the fresh catalog admission check. This plan does not authorize a model request before those gates pass.

## Restart the isolated stack

1. Confirm `.remember/tmp/space-bunny-run/active-instance` still contains `20260927T090631Z-85c16b` and that this instance's `run.json` still contains the run ID above. Stop if either differs; do not create a new instance.
2. From the repository root, run `.remember/tmp/space-bunny-run/launch.py up`. It starts the loopback services and points the API at this instance's existing `coscientist.db`; the terminal run is failed, so startup recovery does not resume it automatically.
3. Run `.remember/tmp/space-bunny-run/launch.py status` and confirm model `openrouter/stealth/space-bunny-alpha`, real engine backend, public MCP/literature available, web search and email disabled, and this same run still `failed`.
4. Complete the fresh zero-price catalog admission check after restart and immediately before resume. Stop if it fails or cannot be verified.

## Resume the same run

Run `.remember/tmp/space-bunny-run/launch.py resume`. The launcher exchanges the local access code in memory, runs its status preflight, then sends authenticated `POST /api/runs/5edffdcc-aac9-4ea2-b722-a1986dce3cca/resume` with an empty JSON body. Do not use `/start`: a failed run with a checkpoint is required to use `/resume`.

In the current resume path, `_enqueue_resume_task` derives the same `engine.node.research_overview:after:7f8368da-8117-4b23-9306-ea95e8511103` key and calls `revive_task_for_retry` before the idempotent enqueue. That revives the existing failed row in place, preserving the run ID and completed work while authorizing one fresh attempt. Confirm the same failed task ID becomes queued/leased with the retry ceiling extended from 3 to 4; no new run should be created.

Monitor with `.remember/tmp/space-bunny-run/launch.py wait --interval 60`, then check status and report publication for the same run ID.

## Current state

The fresh endpoint catalog check passed, and `launch.py resume` resumed the same run. The existing `research_overview` task row was revived in place at attempt 4/4; the single 60-second watcher observed completion at 75/75 tasks. The report and provenance summary are in [the completed-run receipt](m12-space-bunny-completed-run-2026-09-27.json), with the full Markdown report retained as [a compressed artifact](m12-space-bunny-report-2026-09-27.md.gz). The final key usage readback matched the 10:57:28Z baseline exactly; it remains an account-level comparison.

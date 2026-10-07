"""Check 2 baseline: the hand-built runtime under the same cancellation
scenario (8 items, 4 slots, 3 s calls, cancel once 4 calls are in flight).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time

import harness

WORKDIR = tempfile.mkdtemp(prefix="dbos-c2b-")
harness.configure(f"{WORKDIR}/co.db", dbos=False)
os.environ["WORKER_POOL_SIZE"] = "4"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def main() -> int:
    log = f"{WORKDIR}/calls.jsonl"
    harness.install_fake_review(log, 3.0)
    from app import task_worker
    from app.runs.lifecycle import cancel_run
    from app.store import runs, tasks

    run_id, _, _ = harness.seed_review(8, config={"max_iterations": 1, "max_llm_calls": 400})
    threading.Thread(target=task_worker.run_run_worker_pool_sync, args=(run_id, "baseline"), daemon=True).start()
    while sum(1 for r in harness.read_log(log) if r["event"] == "start") < 4:
        time.sleep(0.05)
    cancelled_at = time.time()
    asyncio.run(cancel_run(run_id))
    time.sleep(8)
    after = [r for r in harness.read_log(log) if r["t"] > cancelled_at]
    print(json.dumps({
        "runtime": "hand-built",
        "calls_started_after_cancel": sum(1 for r in after if r["event"] == "start"),
        "calls_finished_after_cancel": sum(1 for r in after if r["event"] == "end"),
        "calls_cancelled_after_cancel": sum(1 for r in after if r["event"] == "cancelled"),
        "run_status": runs.get_run(run_id).status,  # type: ignore[union-attr]
        "task_statuses": sorted({(t.task_type, t.status) for t in tasks.list_tasks(run_id)}),
    }, indent=2))
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())

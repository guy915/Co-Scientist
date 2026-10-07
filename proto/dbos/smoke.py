"""End-to-end smoke: the review node runs as a DBOS workflow and commits once."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time

import harness


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="dbos-smoke-")
    harness.configure(f"{workdir}/co.db")
    call_log = f"{workdir}/calls.jsonl"
    harness.install_fake_review(call_log, delay=0.2)

    from dbos import DBOS

    from app import dbos_proto, task_worker
    from app.store import tasks

    run_id, node_task_id, seq = harness.seed_review(6)
    dbos_proto.launch()

    async def drive() -> dict:
        assert await task_worker.run_once("proto", run_id=run_id)
        node = tasks.get_task(node_task_id)
        assert node is not None and node.status == "completed", node
        handle = await DBOS.retrieve_workflow_async(node.result["dbos_workflow_id"])
        return await handle.get_result()

    started = time.perf_counter()
    result = asyncio.run(drive())
    elapsed = time.perf_counter() - started
    summary = harness.latest_checkpoint_summary(run_id)
    successor = [t.task_type for t in tasks.list_tasks(run_id) if t.status == "queued"]
    dbos_proto.shutdown()
    print(json.dumps({
        "workflow_result": result,
        "checkpoint": summary,
        "calls": harness.calls_per_hypothesis(call_log),
        "queued_successors": successor,
        "elapsed_s": round(elapsed, 3),
    }, indent=2))
    ok = summary["reviewed"] == 6 and all(v == 1 for v in harness.calls_per_hypothesis(call_log).values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

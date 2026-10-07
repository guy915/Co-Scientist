"""Check 5: DBOS works with the worker cohorts' separate event loops,
sharing no asyncio primitive across them.

Three runs, each driven by its own real cohort (`run_run_worker_pool_sync`,
one thread and one `asyncio.run` loop per run), reach the review node at the
same time. Every provider call records its thread and loop; a ticker on
DBOS's own loop records scheduling lag; every log record mentioning another
event loop is counted.

usage: check5_loops.py [adopt-main-loop]
  adopt-main-loop launches DBOS from inside a running loop (as a lifespan
  hook would without to_thread) to show where workflows then execute.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import threading
import time
from collections import Counter
from typing import Any

import harness

RUNS = 3
ITEMS = 10
DELAY = 0.5


class _LoopErrors(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.hits: list[str] = []
        self.errors: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if record.exc_info:
            text += " " + repr(record.exc_info[1])
        if "different event loop" in text or "attached to a different loop" in text:
            self.hits.append(text[:200])
        if record.levelno >= logging.ERROR:
            self.errors.append(f"{record.name}: {text[:200]}")


def main() -> int:
    adopt = "adopt-main-loop" in sys.argv
    workdir = tempfile.mkdtemp(prefix="dbos-c5-")
    harness.configure(f"{workdir}/co.db")
    os.environ["WORKER_POOL_SIZE"] = "3"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    call_log = f"{workdir}/calls.jsonl"
    harness.install_fake_review(call_log, DELAY)
    handler = _LoopErrors()
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    from dbos._dbos import _get_dbos_instance

    from app import dbos_proto, task_worker
    from app.store import tasks

    seeded = [harness.seed_review(ITEMS, config={"max_iterations": 1, "max_llm_calls": 400}) for _ in range(RUNS)]

    holder: dict[str, Any] = {}
    if adopt:
        ready = threading.Event()

        def api_loop() -> None:
            async def body() -> None:
                holder["api_loop"] = id(asyncio.get_running_loop())
                dbos_proto.launch()  # called on a running loop
                ready.set()
                await asyncio.sleep(3600)

            asyncio.run(body())

        threading.Thread(target=api_loop, name="api-loop", daemon=True).start()
        ready.wait()
    else:
        dbos_proto.launch()

    background = _get_dbos_instance()._background_event_loop
    dbos_loop = background.target_loop()
    lags: list[float] = []

    async def ticker() -> None:
        while True:
            planned = time.perf_counter() + 0.05
            await asyncio.sleep(0.05)
            lags.append(max(0.0, time.perf_counter() - planned))

    assert dbos_loop is not None
    asyncio.run_coroutine_threadsafe(ticker(), dbos_loop)

    cohort_threads = []
    for index, (run_id, _, _) in enumerate(seeded):
        thread = threading.Thread(
            target=task_worker.run_run_worker_pool_sync,
            args=(run_id, f"cohort-{index}"),
            name=f"cohort-{index}",
            daemon=True,
        )
        cohort_threads.append(thread)
    started = time.time()
    for thread in cohort_threads:
        thread.start()

    from app.dbos_proto import review_workflow_id
    from procs import workflow_status

    db = f"{workdir}/co.db"
    ids = [review_workflow_id(run_id, seq) for run_id, _, seq in seeded]
    deadline = time.time() + 120
    while time.time() < deadline and any(workflow_status(db, wid) != "SUCCESS" for wid in ids):
        time.sleep(0.1)
    elapsed = time.time() - started
    statuses = {wid: workflow_status(db, wid) for wid in ids}
    texts = {f"h{i:03d}" for i in range(ITEMS)}
    starts = [r for r in harness.read_log(call_log) if r["event"] == "start" and r["hypothesis"] in texts]
    review_node_threads = Counter(r["thread"] for r in starts)
    loops = Counter(r["loop"] for r in starts)
    committed = [
        sum(1 for t in tasks.list_tasks(run_id) if t.task_type == "engine.node.comprehensive_reflection")
        for run_id, _, _ in seeded
    ]
    lag_sorted = sorted(lags)
    result = {
        "mode": "launched on a running loop" if adopt else "launched off-loop (prototype lifespan)",
        "workflow_statuses": statuses,
        "successor_enqueued_per_run": committed,
        "elapsed_s": round(elapsed, 2),
        "provider_calls": len(starts),
        "call_threads": dict(review_node_threads),
        "distinct_call_loops": len(loops),
        "dbos_loop_id": id(dbos_loop),
        "api_loop_id": holder.get("api_loop"),
        "calls_on_dbos_loop": sum(c for loop, c in loops.items() if loop == id(dbos_loop)),
        "cohort_threads": [t.name for t in cohort_threads],
        "cross_loop_errors": handler.hits,
        "error_records": handler.errors[:10],
        "dbos_loop_lag_ms": {
            "samples": len(lag_sorted),
            "p50": round(lag_sorted[len(lag_sorted) // 2] * 1000, 2) if lag_sorted else None,
            "p99": round(lag_sorted[int(len(lag_sorted) * 0.99)] * 1000, 2) if lag_sorted else None,
            "max": round(lag_sorted[-1] * 1000, 2) if lag_sorted else None,
        },
    }
    print(json.dumps(result, indent=2))
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())

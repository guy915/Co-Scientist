"""Check 7: in-flight runs have a cutover path. New runs start on the new
runtime, old runs drain on the old one, then the old one is deleted.

One server process holds two runs at the review node: a legacy run (no
runtime stamp, as every run created before cutover) and a new run stamped
`durable_runtime: dbos` at creation. Both fan out at once; the process is
SIGKILLed mid-fan-out and restarted; each run must recover on its own
runtime. The drain query an operator would run before deleting the old
runtime is then evaluated.
"""

from __future__ import annotations

import json
import sys
import tempfile
from typing import Any

import harness
import procs

N = 8
DELAY = 2.0
CONFIG = {"max_iterations": 1, "max_llm_calls": 400}

# Legacy work left: runs not stamped for DBOS that still hold live task rows.
DRAIN_QUERY = (
    "SELECT COUNT(*) FROM scientific_tasks t JOIN runs r ON r.id=t.run_id "
    "WHERE t.status IN ('queued','leased') "
    "AND r.status IN ('queued','running','synthesizing','paused') "
    "AND COALESCE(json_extract(r.config_json,'$.durable_runtime'),'') <> 'dbos'"
)


def _first_commit(db: str, run_id: str, seq: int) -> dict[str, Any]:
    rows = procs.query(db, "SELECT seq, state_json FROM checkpoints WHERE run_id=? AND seq>? ORDER BY seq LIMIT 1", (run_id, seq))
    if not rows:
        return {"committed": False}
    hyps = json.loads(rows[0]["state_json"])["state"]["hypotheses"]
    return {
        "committed": True,
        "reviewed": sum(1 for h in hyps if h.get("reviews")),
        "review_failed": sum(1 for h in hyps if h.get("review_disposition") == "review_failed"),
    }


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="dbos-c7-")
    db, log = f"{workdir}/co.db", f"{workdir}/calls.jsonl"
    legacy = procs.seed(workdir, N, config=CONFIG)
    new = procs.seed(workdir, N, config={**CONFIG, "durable_runtime": "dbos"})
    server = procs.Server(workdir, 18900, DELAY, tag="a")
    server.wait_healthy()
    procs.wait_for(lambda: sum(1 for r in harness.read_log(log) if r["event"] == "end") >= 6, 60)
    server.kill9()
    drain_mid = procs.query(db, DRAIN_QUERY)[0][0]
    restarted = procs.Server(workdir, 18901, DELAY, tag="b")
    restarted.wait_healthy()
    procs.wait_for(lambda: _first_commit(db, legacy[0], legacy[2])["committed"]
                   and _first_commit(db, new[0], new[2])["committed"], 420)
    legacy_rows_before_end = procs.query(db, DRAIN_QUERY)[0][0]
    # End the legacy run the way an operator or its own completion would, then
    # the drain query must reach zero.
    import urllib.request

    request = urllib.request.Request(
        f"http://127.0.0.1:18901/api/runs/{legacy[0]}/cancel", method="POST",
        headers={"X-Client-ID": "proto", "Content-Type": "application/json"}, data=b"{}",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        cancel_status = response.status
    restarted.stop()

    def runtime_evidence(run_id: str, seq: int) -> dict[str, Any]:
        items = procs.query(db, "SELECT COUNT(*) FROM scientific_tasks WHERE run_id=? AND task_type='engine.fanout.review.item'", (run_id,))[0][0]
        wf = procs.workflow_status(db, f"review:{run_id}:{seq}")
        return {"review_item_task_rows": items, "dbos_review_workflow": wf}

    starts: dict[str, int] = {}
    for record in harness.read_log(log):
        if record["event"] == "start":
            starts[record["hypothesis"]] = starts.get(record["hypothesis"], 0) + 1
    result = {
        "legacy_run": {**runtime_evidence(legacy[0], legacy[2]), **_first_commit(db, legacy[0], legacy[2])},
        "new_run": {**runtime_evidence(new[0], new[2]), **_first_commit(db, new[0], new[2])},
        "calls_total": sum(starts.values()),
        "legacy_work_rows_mid_cutover": drain_mid,
        "legacy_work_rows_after_commit": legacy_rows_before_end,
        "legacy_run_cancel_http_status": cancel_status,
        "legacy_work_rows_after_legacy_run_ended": procs.query(db, DRAIN_QUERY)[0][0],
        "drain_query": DRAIN_QUERY,
        "workdir": workdir,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

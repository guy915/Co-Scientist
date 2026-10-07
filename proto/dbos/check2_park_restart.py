"""Check 2, future-due work across a restart: a rate-limit park becomes a
durable DBOS sleep; kill the process while it sleeps, restart, and confirm
the parked item is called again only after its reset, exactly once more.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time

import harness
import procs

PARK_SECONDS = 20.0


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="dbos-c2p-")
    db, log = f"{workdir}/co.db", f"{workdir}/calls.jsonl"
    env = {"FAKE_SCRIPT": json.dumps({"h000": [f"park:{PARK_SECONDS}", "ok"]})}
    run_id, _, seq, _ = procs.seed(workdir, 4, config={"max_iterations": 1, "max_llm_calls": 400})
    first = procs.Server(workdir, 18800, 0.5, tag="a", env=env)
    first.wait_healthy()
    assert procs.wait_for(lambda: any(r["event"] == "end" and r["hypothesis"] == "h000" for r in harness.read_log(log)), 60)
    parked_at = next(r["t"] for r in harness.read_log(log) if r["event"] == "end" and r["hypothesis"] == "h000")
    time.sleep(2.0)
    killed_at = first.kill9()
    second = procs.Server(workdir, 18801, 0.5, tag="b", env=env)
    second.wait_healthy()
    done = procs.wait_for(lambda: procs.workflow_status(db, f"review:{run_id}:{seq}") == "SUCCESS", 90)
    second.stop()
    starts = [r for r in harness.read_log(log) if r["event"] == "start" and r["hypothesis"] == "h000"]
    rows = procs.query(db, "SELECT state_json FROM checkpoints WHERE run_id=? AND seq>? ORDER BY seq LIMIT 1", (run_id, seq))
    reviewed = None
    if rows:
        hyps = json.loads(rows[0]["state_json"])["state"]["hypotheses"]
        reviewed = sum(1 for h in hyps if h.get("reviews"))
    print(json.dumps({
        "park_seconds": PARK_SECONDS,
        "jitter_upper_s": 15.0,
        "killed_during_park_s_after_park": round(killed_at - parked_at, 2),
        "h000_calls": len(starts),
        "second_call_after_park_s": round(starts[1]["t"] - parked_at, 2) if len(starts) > 1 else None,
        "second_call_pid_is_restarted_process": len(starts) > 1 and starts[1]["pid"] == second.proc.pid,
        "workflow_done": done,
        "reviewed_after_commit": reviewed,
        "workdir": workdir,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

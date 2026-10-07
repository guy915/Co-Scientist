"""Check 1: kill the worker mid-fan-out; on restart it resumes with no
duplicate model calls and no lost results.

Each trial runs the real app (lifespan, startup recovery, cohorts) on a seeded
run at the review node, SIGKILLs it after K provider calls finished, restarts
it, and waits for the review workflow to finish.

usage: check1_kill.py [baseline] [overlap]
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from collections import Counter
from typing import Any

import harness
import procs

N = 12
DELAY = 2.0
CONFIG = {"max_iterations": 1, "initial_hypotheses_count": 4, "max_llm_calls": 400}


def _ended(log: str, texts: set[str]) -> set[str]:
    return {r["hypothesis"] for r in harness.read_log(log) if r["event"] == "end" and r["hypothesis"] in texts}


def _started(log: str, texts: set[str]) -> Counter[str]:
    return Counter(r["hypothesis"] for r in harness.read_log(log) if r["event"] == "start" and r["hypothesis"] in texts)


def _final_reviews(db: str, run_id: str, ids: dict[str, str], seq: int) -> dict[str, Any]:
    """Reviews held by the checkpoint the review phase committed (the next
    phases may add more checkpoints; take the first one after `seq`)."""
    rows = procs.query(db, "SELECT seq, stage, state_json FROM checkpoints WHERE run_id=? AND seq>? ORDER BY seq LIMIT 1", (run_id, seq))
    if not rows:
        return {"committed": False}
    state = json.loads(rows[0]["state_json"])["state"]
    reviewed = {ids[h["id"]]: len(h.get("reviews") or []) for h in state["hypotheses"] if h["id"] in ids}
    failed = sorted(ids[h["id"]] for h in state["hypotheses"] if h["id"] in ids and h.get("review_disposition") == "review_failed")
    return {"committed": True, "seq": rows[0]["seq"], "stage": rows[0]["stage"], "reviews": reviewed, "review_failed": failed}


def trial(kill_after: int, *, zero_cost: bool = False, dbos: bool = True, overlap: bool = False,
          port: int = 18300, wait: float = 90.0, env: dict[str, str] | None = None, delay: float = DELAY) -> dict[str, Any]:
    workdir = tempfile.mkdtemp(prefix="dbos-c1-")
    db, log = f"{workdir}/co.db", f"{workdir}/calls.jsonl"
    run_id, node_task_id, seq, ids = procs.seed(workdir, N, zero_cost=zero_cost, config=CONFIG)
    texts = set(ids.values())
    parent = f"review:{run_id}:{seq}"
    first = procs.Server(workdir, port, delay, dbos=dbos, tag="a", env=env)
    first.wait_healthy()
    assert procs.wait_for(lambda: len(_ended(log, texts)) >= kill_after, 120), "no progress before kill"
    ended_before = _ended(log, texts)
    started_before = _started(log, texts)
    in_flight = sorted(set(started_before) - ended_before)
    second = None
    if overlap:
        # Deploy overlap: a second process boots on the same file while the
        # first is still executing the fan-out.
        second = procs.Server(workdir, port + 1, delay, dbos=dbos, tag="b", env=env)
        second.wait_healthy()
        killed_at = None
    else:
        killed_at = first.kill9()
    recorded_at_kill = procs.recorded_attempts(db, parent) if dbos else {}
    restart_ready = None
    if second is None:
        second = procs.Server(workdir, port + 1, delay, dbos=dbos, tag="b", env=env)
        restart_ready = second.wait_healthy()
    t0 = time.time()
    if dbos:
        done = procs.wait_for(lambda: procs.workflow_status(db, parent) in {"SUCCESS", "ERROR", "CANCELLED"}, wait)
    else:
        done = procs.wait_for(lambda: bool(procs.query(db, "SELECT 1 FROM checkpoints WHERE run_id=? AND seq>?", (run_id, seq))), wait)
    resumed_in = time.time() - t0
    time.sleep(1.0)
    second.stop()
    first.stop()
    started = _started(log, texts)
    final = _final_reviews(db, run_id, ids, seq)
    recorded_ok = sorted(ids[cid.rsplit(":", 1)[1]] for cid, outs in recorded_at_kill.items() if "ok" in outs)
    lost = sorted(t for t in recorded_ok if final.get("reviews", {}).get(t, 0) == 0)
    node_runs = procs.query(db, "SELECT status, attempt FROM scientific_tasks WHERE run_id=? AND task_type='engine.node.review'", (run_id,))
    return {
        "workdir": workdir,
        "runtime": "dbos" if dbos else "hand-built",
        "env": env or {},
        "zero_cost": zero_cost,
        "overlap": overlap,
        "kill_after_ended": kill_after,
        "provider_delay_s": delay,
        "second_process_healthy_at_rel_s": None,
        "ended_before_kill": len(ended_before),
        "in_flight_at_kill": in_flight,
        "recorded_ok_at_kill": len(recorded_ok),
        "ended_but_unrecorded_at_kill": sorted(ended_before - set(recorded_ok)) if dbos else None,
        "restart_healthy_s": None if restart_ready is None else round(restart_ready, 2),
        "workflow_done": done,
        "resume_to_commit_s": round(resumed_in, 2),
        "calls_total": sum(started.values()),
        "duplicate_calls": {t: c for t, c in started.items() if c > 1},
        "never_called": sorted(texts - set(started)),
        "final": {k: v for k, v in final.items() if k != "reviews"},
        "reviewed_count": sum(1 for v in final.get("reviews", {}).values() if v),
        "lost_recorded_results": lost,
        "review_node_rows": [dict(r) for r in node_runs],
        "killed_at": killed_at,
    }


def main() -> int:
    mode = set(sys.argv[1:])
    results = []
    if "baseline" in mode:
        results.append(trial(6, dbos=False, port=18400, wait=420))
    elif "native" in mode:
        results.append(trial(6, port=18540, env={"COSCIENTIST_DBOS_NO_MARKER": "1"}))
    elif "overlap" in mode:
        results.append(trial(1, overlap=True, port=18500, delay=6.0))
        results.append(trial(1, overlap=True, zero_cost=True, port=18520, delay=6.0))
    else:
        port = 18300
        for kill_after in (1, 4, 6, 9, 11):
            results.append(trial(kill_after, port=port))
            port += 2
        results.append(trial(6, zero_cost=True, port=port))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

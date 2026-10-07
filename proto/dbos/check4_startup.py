"""Check 4: startup stays cheap; recovery runs outside the port-binding path.

Measures spawn-to-healthy for the real app, DBOS on vs off, on:
  fresh      an empty database (DBOS creates and migrates its tables)
  history    DBOS tables holding ~300 completed review phases
  recovery   a SIGKILLed 12-item fan-out with 10 s provider calls pending,
             to show /health answers before the recovered calls finish
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
import uuid
from typing import Any

import harness
import procs

REPEATS = 3


def _launch_seconds(workdir: str, tag: str) -> float | None:
    with open(f"{workdir}/server-{tag}.log", encoding="utf-8") as handle:
        found = re.findall(r"dbos_launch seconds=([0-9.]+)", handle.read())
    return float(found[-1]) if found else None


def boot(workdir: str, dbos: bool, port: int, tag: str) -> dict[str, Any]:
    server = procs.Server(workdir, port, 1.0, dbos=dbos, tag=tag)
    healthy = server.wait_healthy()
    server.stop()
    return {"healthy_s": round(healthy, 3), "dbos_launch_s": _launch_seconds(workdir, tag)}


def _median(samples: list[dict[str, Any]], key: str) -> float | None:
    values = [s[key] for s in samples if s.get(key) is not None]
    return round(statistics.median(values), 3) if values else None


def fresh(dbos: bool, port: int) -> dict[str, Any]:
    samples = []
    for i in range(REPEATS):
        workdir = tempfile.mkdtemp(prefix="dbos-c4-fresh-")
        samples.append(boot(workdir, dbos, port + i, "fresh"))
    return {"dbos": dbos, "samples": samples, "median_healthy_s": _median(samples, "healthy_s"),
            "median_dbos_launch_s": _median(samples, "dbos_launch_s")}


def _review_db() -> str:
    """One database holding a completed DBOS review phase to replicate."""
    workdir = tempfile.mkdtemp(prefix="dbos-c4-src-")
    run_id, _, seq, _ = procs.seed(workdir, 12, config={"max_iterations": 1, "max_llm_calls": 400})
    server = procs.Server(workdir, 18790, 0.05, tag="src")
    server.wait_healthy()
    assert procs.wait_for(lambda: procs.workflow_status(f"{workdir}/co.db", f"review:{run_id}:{seq}") == "SUCCESS", 60)
    server.stop()
    return f"{workdir}/co.db"


def _replicate(db: str, copies: int) -> dict[str, int]:
    conn = sqlite3.connect(db, isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    tables = {"workflow_status": "workflow_uuid", "operation_outputs": "workflow_uuid"}
    base = {t: conn.execute(f"SELECT * FROM {t} WHERE workflow_uuid LIKE 'review:%'").fetchall() for t in tables}
    cols = {t: [c[1] for c in conn.execute(f"PRAGMA table_info({t})")] for t in tables}
    for _ in range(copies):
        fake = str(uuid.uuid4())
        for table, rows in base.items():
            idx = cols[table].index("workflow_uuid")
            for row in rows:
                values = list(row)
                parts = values[idx].split(":")
                parts[1] = fake
                values[idx] = ":".join(parts)
                if table == "operation_outputs" and "child_workflow_id" in cols[table]:
                    ci = cols[table].index("child_workflow_id")
                    if values[ci]:
                        cparts = values[ci].split(":")
                        cparts[1] = fake
                        values[ci] = ":".join(cparts)
                marks = ",".join("?" for _ in values)
                conn.execute(f"INSERT INTO {table} VALUES ({marks})", values)
    conn.execute("COMMIT")
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()
    return counts


def history(port: int) -> dict[str, Any]:
    source = _review_db()
    out: dict[str, Any] = {}
    for dbos in (True, False):
        samples = []
        for i in range(REPEATS):
            workdir = tempfile.mkdtemp(prefix="dbos-c4-hist-")
            shutil.copy(source, f"{workdir}/co.db")
            counts = _replicate(f"{workdir}/co.db", 300)
            samples.append(boot(workdir, dbos, port + i + (0 if dbos else 10), "hist"))
        out["dbos" if dbos else "baseline"] = {
            "rows": counts, "samples": samples,
            "median_healthy_s": _median(samples, "healthy_s"),
            "median_dbos_launch_s": _median(samples, "dbos_launch_s"),
        }
    return out


def recovery(port: int) -> dict[str, Any]:
    workdir = tempfile.mkdtemp(prefix="dbos-c4-rec-")
    db, log = f"{workdir}/co.db", f"{workdir}/calls.jsonl"
    run_id, _, seq, ids = procs.seed(workdir, 12, config={"max_iterations": 1, "max_llm_calls": 400})
    texts = set(ids.values())
    first = procs.Server(workdir, port, 10.0, tag="a")
    first.wait_healthy()
    assert procs.wait_for(lambda: sum(1 for r in harness.read_log(log) if r["event"] == "start" and r["hypothesis"] in texts) >= 4, 60)
    first.kill9()
    second = procs.Server(workdir, port + 1, 10.0, tag="b")
    healthy = second.wait_healthy()
    healthy_at = second.spawned_at + healthy
    procs.wait_for(lambda: procs.workflow_status(db, f"review:{run_id}:{seq}") == "SUCCESS", 120)
    second.stop()
    after = [r for r in harness.read_log(log) if r["t"] > first.spawned_at + 1 and r["pid"] == second.proc.pid and r["hypothesis"] in texts]
    starts = [r["t"] for r in after if r["event"] == "start"]
    ends = [r["t"] for r in after if r["event"] == "end"]
    threads = sorted({r.get("thread", "?") for r in after if r["event"] == "start"})
    return {
        "restart_healthy_s": round(healthy, 3),
        "dbos_launch_s": _launch_seconds(workdir, "b"),
        "first_recovered_call_after_healthy_s": round(min(starts) - healthy_at, 3) if starts else None,
        "last_recovered_call_end_after_healthy_s": round(max(ends) - healthy_at, 3) if ends else None,
        "recovered_calls": len(starts),
        "recovered_call_threads": threads,
    }


def main() -> int:
    results = {
        "fresh_dbos": fresh(True, 18700),
        "fresh_baseline": fresh(False, 18710),
        "history": history(18720),
        "recovery": recovery(18750),
    }
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

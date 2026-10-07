"""Check 3: DBOS shares the one SQLite file safely: one writer, WAL, no write
lock held over network I/O, no write on every poll tick, no VACUUM or
truncating checkpoint from the serving process.

Runs the real app with every app and DBOS statement traced:
  idle      60 s with no runs (DBOS on, then off as the baseline)
  fanout    one 12-item review fan-out, 2 s per provider call, while an
            outside writer probes BEGIN IMMEDIATE latency every 100 ms
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from typing import Any

import harness
import procs

WRITE = re.compile(r"^(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b", re.I)
DANGER = re.compile(r"VACUUM|wal_checkpoint|journal_mode|synchronous", re.I)


def load_trace(path: str, since: float = 0.0, until: float = float("inf")) -> list[tuple[float, str, str, str, str]]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t", 4)
            if len(parts) != 5:
                continue
            t = float(parts[0])
            if since <= t <= until:
                rows.append((t, parts[1], parts[2], parts[3], parts[4]))
    return rows


def analyse(rows: list[tuple[float, str, str, str, str]], window: float) -> dict[str, Any]:
    by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    open_txn: dict[str, tuple[float, str, int]] = {}
    txns: list[tuple[float, str, str, int]] = []  # duration, kind, first statement, writes
    danger: list[str] = []
    for t, kind, conn, thread, stmt in rows:
        head = stmt.split(" ", 1)[0].upper()
        c = by_kind[kind]
        c["statements"] += 1
        if stmt.upper().startswith("BEGIN IMMEDIATE"):
            c["begin_immediate"] += 1
            open_txn[conn] = (t, kind, 0)
            continue
        if head in {"COMMIT", "ROLLBACK"} and conn in open_txn:
            start, k, writes = open_txn.pop(conn)
            txns.append((t - start, k, head, writes))
            c[head.lower()] += 1
            if writes == 0:
                c["write_lock_taken_without_write"] += 1
            continue
        if WRITE.match(stmt):
            c["write_statements"] += 1
            if conn in open_txn:
                s, k, w = open_txn[conn]
                open_txn[conn] = (s, k, w + 1)
        if DANGER.search(stmt):
            danger.append(f"{kind}: {stmt[:100]}")
    out: dict[str, Any] = {"window_s": round(window, 1)}
    for kind, c in by_kind.items():
        out[kind] = dict(c)
        out[kind]["write_lock_acquisitions_per_s"] = round(c["begin_immediate"] / window, 3) if window else None
    for kind in by_kind:
        durations = sorted(d for d, k, _, _ in txns if k == kind)
        if durations:
            out[kind]["write_txn_ms"] = {
                "count": len(durations),
                "p50": round(statistics.median(durations) * 1000, 2),
                "p99": round(durations[int(len(durations) * 0.99) - 1] * 1000, 2) if len(durations) > 1 else round(durations[0] * 1000, 2),
                "max": round(durations[-1] * 1000, 2),
            }
    out["pragma_or_vacuum_statements"] = sorted(set(danger))
    return out


def idle(dbos: bool, port: int, seconds: float = 60.0) -> dict[str, Any]:
    workdir = tempfile.mkdtemp(prefix="dbos-c3-idle-")
    server = procs.Server(workdir, port, 1.0, dbos=dbos, tag="idle")
    server.wait_healthy()
    time.sleep(5.0)  # Let startup recovery, demo seeding and migrations settle.
    start = time.time()
    time.sleep(seconds)
    end = time.time()
    server.stop()
    return {"dbos": dbos, **analyse(load_trace(f"{workdir}/trace.tsv", start, end), end - start)}


class Probe(threading.Thread):
    """An outside writer, like an API request, timing its write lock wait."""

    def __init__(self, db: str) -> None:
        super().__init__(daemon=True)
        self.db = db
        self.waits: list[float] = []
        self.errors = 0
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            conn = sqlite3.connect(self.db, timeout=30, isolation_level=None)
            try:
                started = time.perf_counter()
                conn.execute("BEGIN IMMEDIATE")
                self.waits.append(time.perf_counter() - started)
                conn.execute("CREATE TABLE IF NOT EXISTS proto_probe (t REAL)")
                conn.execute("INSERT INTO proto_probe VALUES (?)", (time.time(),))
                conn.execute("COMMIT")
            except sqlite3.OperationalError:
                self.errors += 1
            finally:
                conn.close()
            self.stop.wait(0.1)


def fanout(dbos: bool, port: int) -> dict[str, Any]:
    workdir = tempfile.mkdtemp(prefix="dbos-c3-fan-")
    db = f"{workdir}/co.db"
    run_id, _, seq, ids = procs.seed(workdir, 12, config={"max_iterations": 1, "max_llm_calls": 400})
    server = procs.Server(workdir, port, 2.0, dbos=dbos, tag="fan")
    server.wait_healthy()
    probe = Probe(db)
    probe.start()
    start = time.time()
    done = procs.wait_for(
        lambda: bool(procs.query(db, "SELECT 1 FROM checkpoints WHERE run_id=? AND seq>?", (run_id, seq))), 120
    )
    end = time.time()
    probe.stop.set()
    probe.join()
    calls = [r for r in harness.read_log(f"{workdir}/calls.jsonl") if r["hypothesis"] in set(ids.values())]
    server.stop()
    journal = procs.query(db, "PRAGMA journal_mode")[0][0]
    rows = load_trace(f"{workdir}/trace.tsv", start, end)
    # Any write transaction open across a provider call boundary on the
    # thread that made the call would show as a txn longer than the call.
    report = analyse(rows, end - start)
    waits = sorted(probe.waits)
    return {
        "dbos": dbos,
        "review_committed": done,
        "provider_calls": sum(1 for r in calls if r["event"] == "start"),
        "journal_mode_after": journal,
        "outside_writer_wait_ms": {
            "samples": len(waits),
            "p50": round(statistics.median(waits) * 1000, 2) if waits else None,
            "p99": round(waits[int(len(waits) * 0.99) - 1] * 1000, 2) if len(waits) > 1 else None,
            "max": round(waits[-1] * 1000, 2) if waits else None,
            "lock_errors": probe.errors,
        },
        **report,
    }


def main() -> int:
    results = {
        "idle_dbos": idle(True, 18600),
        "idle_baseline": idle(False, 18602),
        "fanout_dbos": fanout(True, 18604),
        "fanout_baseline": fanout(False, 18606),
    }
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

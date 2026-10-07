"""Process control and read-only probes shared by the process-level checks."""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PYTHON = str(HERE.parents[1] / ".venv" / "bin" / "python")


class Server:
    def __init__(self, workdir: str, port: int, delay: float, *, dbos: bool = True, tag: str = "a",
                 env: dict[str, str] | None = None) -> None:
        self.workdir = workdir
        self.port = port
        self.tag = tag
        args = [PYTHON, str(HERE / "serve.py"), f"{workdir}/co.db", str(port),
                f"{workdir}/calls.jsonl", f"{workdir}/trace.tsv", str(delay)]
        if not dbos:
            args.append("--no-dbos")
        self.out = open(f"{workdir}/server-{tag}.log", "a", encoding="utf-8")
        self.spawned_at = time.time()
        self.proc = subprocess.Popen(args, cwd=str(HERE), stdout=self.out, stderr=subprocess.STDOUT,
                                     env={**os.environ, **(env or {})})

    def wait_healthy(self, timeout: float = 60.0) -> float:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server {self.tag} exited {self.proc.returncode}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1) as r:
                    if r.status == 200:
                        return time.time() - self.spawned_at
            except Exception:
                pass
            time.sleep(0.02)
        raise TimeoutError(f"server {self.tag} not healthy")

    def kill9(self) -> float:
        at = time.time()
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait()
        return at

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


def query(db: str, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return []
        raise
    finally:
        conn.close()


def workflow_status(db: str, workflow_id: str) -> str | None:
    rows = query(db, "SELECT status FROM workflow_status WHERE workflow_uuid=?", (workflow_id,))
    return str(rows[0]["status"]) if rows else None


def wait_for(predicate, timeout: float, interval: float = 0.05) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def recorded_attempts(db: str, parent_id: str) -> dict[str, list[str]]:
    """Child workflow id -> recorded attempt outcome kinds (DBOS step outputs)."""
    rows = query(
        db,
        "SELECT workflow_uuid, output FROM operation_outputs WHERE function_name=? "
        "AND substr(workflow_uuid,1,?)=?",
        ("coscientist.review.attempt", len(parent_id) + 1, parent_id + ":"),
    )
    import base64
    import pickle

    result: dict[str, list[str]] = {}
    for row in rows:
        kind = "none"
        if row["output"]:
            kind = str(pickle.loads(base64.b64decode(row["output"])).get("kind"))
        result.setdefault(row["workflow_uuid"], []).append(kind)
    return result


def seed(workdir: str, count: int, **kwargs: Any) -> tuple[str, str, int, dict[str, str]]:
    """Seed in a short-lived subprocess so this driver never imports the app."""
    code = (
        "import json, harness, sys; harness.configure(sys.argv[1]);"
        "kw=json.loads(sys.argv[3]); r=harness.seed_review(int(sys.argv[2]), **kw);"
        "from app.store import checkpoints;"
        "cp=checkpoints.get_latest_checkpoint(r[0]);"
        "ids={h['id']:h['text'] for h in cp['state']['state']['hypotheses']};"
        "print(json.dumps([r[0], r[1], r[2], ids]))"
    )
    import json

    out = subprocess.run([PYTHON, "-c", code, f"{workdir}/co.db", str(count), json.dumps(kwargs)],
                         cwd=str(HERE), capture_output=True, text=True, check=True)
    run_id, task_id, seq, ids = json.loads(out.stdout.strip().splitlines()[-1])
    return run_id, task_id, int(seq), ids


if __name__ == "__main__":
    sys.exit(0)

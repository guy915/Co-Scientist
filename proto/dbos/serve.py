"""Serve the real app (lifespan, recovery, cohorts) with the fake reviewer and
an SQL statement trace on every app and DBOS connection.

usage: serve.py DB PORT CALL_LOG TRACE_LOG DELAY [--no-dbos]
"""

from __future__ import annotations

import os
import sys
import threading
import time

import harness

db_path, port, call_log, trace_log, delay = sys.argv[1:6]
use_dbos = "--no-dbos" not in sys.argv
harness.configure(db_path, dbos=use_dbos)
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.setdefault("WORKER_POOL_SIZE", "4")
os.environ["LOG_CAPTURE_ENABLED"] = os.environ.get("LOG_CAPTURE_ENABLED", "false")
harness.install_fake_review(call_log, float(delay))

_trace_lock = threading.Lock()
_trace = open(trace_log, "a", encoding="utf-8", buffering=1) if trace_log != "-" else None


def _tracer(kind: str, conn_id: int):  # type: ignore[no-untyped-def]
    def trace(statement: str) -> None:
        if _trace is None:
            return
        line = " ".join(statement.split())[:160]
        with _trace_lock:
            _trace.write(
                f"{time.time():.6f}\t{kind}\t{conn_id}\t{threading.current_thread().name}\t{line}\n"
            )

    return trace


import app.store.db as store_db  # noqa: E402

_open_raw = store_db._open_raw_connection


def _traced_open(path: str):  # type: ignore[no-untyped-def]
    conn = _open_raw(path)
    conn.set_trace_callback(_tracer("app", id(conn)))
    return conn


store_db._open_raw_connection = _traced_open

from sqlalchemy import event  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402


@event.listens_for(Engine, "connect")
def _trace_dbos(dbapi_conn, _record):  # type: ignore[no-untyped-def]
    dbapi_conn.set_trace_callback(_tracer("dbos", id(dbapi_conn)))


import uvicorn  # noqa: E402

print(f"serve pid={os.getpid()} t={time.time():.6f}", flush=True)
uvicorn.run("app.main:app", host="127.0.0.1", port=int(port), log_level="warning")

"""DBOS durable-runtime prototype (phase 3, branch proto/dbos, never merged).

Only the review fan-out runs on DBOS; every other phase stays on the
hand-built queue. DBOS keeps its tables in the same SQLite file.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

ENABLED_ENV = "COSCIENTIST_DBOS_REVIEW"
# Recovery is scoped by application version; a per-deploy source hash would
# strand every in-flight workflow on each deploy, so the version is pinned and
# bumped only when a workflow's step order changes.
WORKFLOW_VERSION = "review-v1"
REVIEW_WORKFLOW_PREFIX = "review:"

_launch_lock = threading.Lock()
_launched_for: str | None = None


def enabled() -> bool:
    return os.getenv(ENABLED_ENV, "").strip().lower() in {"1", "true", "yes"}


def _db_path(db_path: str | None = None) -> str:
    from app.store.db import _resolved_db_path

    return str(Path(_resolved_db_path(db_path)).resolve())


def review_workflow_id(run_id: str, checkpoint_seq: int) -> str:
    return f"{REVIEW_WORKFLOW_PREFIX}{run_id}:{checkpoint_seq}"


def launch(db_path: str | None = None) -> None:
    """Launch from a thread with no running loop, so recovered and started
    workflows run on DBOS's own loop instead of the API or a cohort loop.
    """
    global _launched_for
    path = _db_path(db_path)
    with _launch_lock:
        if _launched_for == path:
            return
        from dbos import DBOS

        import app.dbos_proto.review as review

        review.ensure_tables(path)
        DBOS(
            config={
                "name": "coscientist",
                "system_database_url": f"sqlite:///{path}",
                "application_version": WORKFLOW_VERSION,
                "executor_id": "api",
                "log_level": "WARNING",
            }
        )
        import time

        started = time.perf_counter()
        DBOS.launch()
        logger.info("dbos_launch seconds=%.3f", time.perf_counter() - started)
        _launched_for = path


def shutdown() -> None:
    global _launched_for
    with _launch_lock:
        if _launched_for is None:
            return
        from dbos import DBOS

        DBOS.destroy(destroy_registry=False)
        _launched_for = None


_PENDING = "('PENDING','ENQUEUED')"


def _pending_rows(query: str, params: tuple[object, ...], db_path: str | None) -> list[str]:
    # Read-only probe over a plain connection: cohorts poll it on their own
    # cadence, so it must never open a write transaction.
    try:
        conn = sqlite3.connect(f"file:{_db_path(db_path)}?mode=ro", uri=True, timeout=30)
    except sqlite3.OperationalError:
        return []
    try:
        return [str(row[0]) for row in conn.execute(query, params).fetchall()]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return []
        raise
    finally:
        conn.close()


def has_pending_review(run_id: str, db_path: str | None = None) -> bool:
    if not enabled():
        return False
    prefix = f"{REVIEW_WORKFLOW_PREFIX}{run_id}:"
    return bool(
        _pending_rows(
            "SELECT workflow_uuid FROM workflow_status WHERE status IN "
            f"{_PENDING} AND substr(workflow_uuid,1,?)=? LIMIT 1",
            (len(prefix), prefix),
            db_path,
        )
    )


def pending_review_run_ids(db_path: str | None = None) -> list[str]:
    if not enabled():
        return []
    rows = _pending_rows(
        "SELECT DISTINCT workflow_uuid FROM workflow_status WHERE status IN "
        f"{_PENDING} AND substr(workflow_uuid,1,?)=?",
        (len(REVIEW_WORKFLOW_PREFIX), REVIEW_WORKFLOW_PREFIX),
        db_path,
    )
    return sorted({row.split(":")[1] for row in rows})


def cancel_run_workflows(run_id: str, db_path: str | None = None) -> int:
    """Run cancellation must also stop DBOS work; call after the cancel
    transaction commits, never inside it (DBOS writes on its own connection).
    """
    if not enabled():
        return 0
    from dbos import DBOS

    prefix = f"{REVIEW_WORKFLOW_PREFIX}{run_id}:"
    pending = _pending_rows(
        "SELECT workflow_uuid FROM workflow_status WHERE status IN "
        f"{_PENDING} AND substr(workflow_uuid,1,?)=?",
        (len(prefix), prefix),
        db_path,
    )
    for workflow_id in pending:
        DBOS.cancel_workflow(workflow_id)
    return len(pending)

from __future__ import annotations

import logging
import os
import time

from app.store import documents as store
from app.store import runs as store_runs
from app.store import runs_views as views

logger = logging.getLogger(__name__)

_DEFAULT_RUN_RETENTION_DAYS = 90
_DEFAULT_DOCUMENT_RETENTION_DAYS = 30
_SECONDS_PER_DAY = 86_400


def _retention_days(env_var: str, default_days: int) -> int:
    """Malformed maintenance settings must not become fatal startup or cron
    work.
    """
    raw = os.getenv(env_var)
    if not raw:
        return default_days
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("Ignoring invalid %s=%r", env_var, raw)
        return default_days


def run_retention_days() -> int:
    return _retention_days("COSCIENTIST_RUN_RETENTION_DAYS", _DEFAULT_RUN_RETENTION_DAYS)


def document_retention_days() -> int:
    return _retention_days(
        "COSCIENTIST_DOCUMENT_RETENTION_DAYS",
        _DEFAULT_DOCUMENT_RETENTION_DAYS,
    )


def sweep_expired_runs(*, now: float | None = None) -> list[str]:
    """Use short per-run transactions rather than holding SQLite's writer
    across the whole retention sweep.
    """
    days = run_retention_days()
    if days == 0:
        return []
    cutoff = (now or time.time()) - days * _SECONDS_PER_DAY
    deleted = []
    for run in views.list_expired_terminal_runs(cutoff):
        store_runs.delete_run(run.id)
        deleted.append(run.id)
        logger.info("Retention swept expired run %s", run.id)
    return deleted


def sweep_expired_documents(*, now: float | None = None) -> int:
    days = document_retention_days()
    if days == 0:
        return 0
    cutoff = (now or time.time()) - days * _SECONDS_PER_DAY
    count = store.delete_staged_documents_older_than(cutoff)
    if count:
        logger.info("Retention swept %d expired staged document(s)", count)
    return count


def sweep_all(*, now: float | None = None) -> dict[str, int]:
    runs = sweep_expired_runs(now=now)
    documents = sweep_expired_documents(now=now)
    return {
        "runs": len(runs),
        "documents": documents,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = sweep_all()
    logger.info(
        "Retention sweep complete: runs=%d documents=%d",
        results["runs"],
        results["documents"],
    )

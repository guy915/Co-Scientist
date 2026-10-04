"""Read windows without Settings so detached maintenance stays independent.

Short per-row deletes avoid holding SQLite's write lock across a sweep.
"""

from __future__ import annotations

import logging
import os
import time

from app import store

logger = logging.getLogger(__name__)

_DEFAULT_RUN_RETENTION_DAYS = 90
_DEFAULT_DOCUMENT_RETENTION_DAYS = 30
_SECONDS_PER_DAY = 86_400


def _retention_days(env_var: str, default_days: int) -> int:
    """Read one retention window from the environment, floored at zero.

    A malformed value falls back to the default rather than raising, since
    this runs ahead of any request and must not become fatal startup work
    (see the "startup work" gotcha in AGENTS.md) or a bad env var in a
    cron invocation.
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
    """Days a terminal run is kept before ``sweep_expired_runs`` deletes it.

    Env: ``COSCIENTIST_RUN_RETENTION_DAYS``. 0 disables the sweep.
    """
    return _retention_days(
        "COSCIENTIST_RUN_RETENTION_DAYS", _DEFAULT_RUN_RETENTION_DAYS
    )


def document_retention_days() -> int:
    """Days a staged document is kept before its sweep deletes it.

    Env: ``COSCIENTIST_DOCUMENT_RETENTION_DAYS``. 0 disables the sweep.
    """
    return _retention_days(
        "COSCIENTIST_DOCUMENT_RETENTION_DAYS",
        _DEFAULT_DOCUMENT_RETENTION_DAYS,
    )


def sweep_expired_runs(*, now: float | None = None) -> list[str]:
    """Delete every terminal run older than the run retention window.

    A run still short of the window, or not yet terminal, is untouched.
    Each deletion is its own short transaction (``store.delete_run``), so
    a sweep over many expired runs never holds one long-lived lock.

    Returns:
        The ids of every run that was deleted.
    """
    days = run_retention_days()
    if days == 0:
        return []
    cutoff = (now or time.time()) - days * _SECONDS_PER_DAY
    deleted = []
    for run in store.list_expired_terminal_runs(cutoff):
        store.delete_run(run.id)
        deleted.append(run.id)
        logger.info("Retention swept expired run %s", run.id)
    return deleted


def sweep_expired_documents(*, now: float | None = None) -> int:
    """Delete every staged document older than the document retention window.

    Returns:
        How many documents were deleted.
    """
    days = document_retention_days()
    if days == 0:
        return 0
    cutoff = (now or time.time()) - days * _SECONDS_PER_DAY
    count = store.delete_staged_documents_older_than(cutoff)
    if count:
        logger.info("Retention swept %d expired staged document(s)", count)
    return count


def sweep_all(*, now: float | None = None) -> dict[str, int]:
    """Run every retention sweep once and return how much each deleted."""
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

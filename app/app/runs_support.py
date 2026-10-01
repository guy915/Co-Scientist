"""Shared existence guards for the run endpoint modules.

``app.runs`` and its sibling endpoint modules (``runs_lifecycle``,
``runs_collections``, ``runs_contrib``) all guard requests on run
existence. The helpers live here, below every router module, so the
siblings never import ``app.runs`` (which includes their routers) and
create an import cycle. ``app.runs`` re-exports ``_run_or_404``, so
``runs._run_or_404`` remains the stable import surface.
"""

from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from app import store
from app.store import RunRow


def _run_or_404(run_id: str, conn: sqlite3.Connection | None = None) -> RunRow:
    """Return the run row or raise a 404 for unknown run ids."""
    run = store.get_run(run_id, conn=conn)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _require_run(run_id: str) -> None:
    """404 if the run does not exist, without materializing the row.

    Use this for endpoints that only need an existence guard; ``_run_or_404``
    is for the few that read the run row itself.
    """
    if not store.run_exists(run_id):
        raise HTTPException(status_code=404, detail="run not found")

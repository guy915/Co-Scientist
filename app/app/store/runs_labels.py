"""Post-create run text setters, filled by background generators.

A run's short session ``title`` and its narrative ``goal_restatement``
(GOAL-RESTATEMENT-001) are both derived from the goal alone, generated off
the create critical path, and written back onto the run row once ready. Split
out of ``app.runs`` to keep that module within the size cap; both are
re-exported through ``app.store`` so callers use ``store.set_run_*``.
"""

from __future__ import annotations

from app.store.db import connect


def set_run_title(run_id: str, title: str, db_path: str | None = None) -> None:
    """Set a run's short session title (idempotent; no-op if the run is gone).

    Args:
        run_id: Identifier of the run to update.
        title: The generated short title to store.
        db_path: Optional override for the SQLite database path.
    """
    with connect(db_path) as conn:
        conn.execute("UPDATE runs SET title = ? WHERE id = ?", (title, run_id))


def set_run_goal_restatement(
    run_id: str, restatement: str, db_path: str | None = None
) -> None:
    """Set a run's narrative goal restatement (idempotent; no-op if gone).

    GOAL-RESTATEMENT-001: a background generator fills this shortly after
    create, and the report reads it from the run row at finalize.

    Args:
        run_id: Identifier of the run to update.
        restatement: The synthesized narrative restatement to store.
        db_path: Optional override for the SQLite database path.
    """
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET goal_restatement = ? WHERE id = ?",
            (restatement, run_id),
        )

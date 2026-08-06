"""Permanent deletion of a run and every row scoped to it.

Almost every run-scoped table declares ``run_id ... REFERENCES runs(id) ON
DELETE CASCADE`` (see ``app.store.schema``), and ``PRAGMA foreign_keys=ON``
is set on every connection this store hands out (``_open_raw_connection``),
so one ``DELETE FROM runs`` is enough to cascade through hypotheses,
hypothesis_state, evidence, citations, reviews, matches, safety_decisions,
reports, messages, checkpoints, run_metrics, claim_evidence,
knowledge_facts, proximity_edges, run_credentials, report_shares,
run_events, and scientific_tasks -- directly or transitively (a hypothesis
cascades away when its run does, and a review/citation/claim_evidence row
cascades away when its hypothesis does).

``staged_documents`` is the one run-scoped table deliberately left without
a foreign key (a document can exist before any run row does -- see
``app.store.documents``), so a deleted run's reference to it is cleared
explicitly rather than left dangling; the document itself survives, since
it may be the caller's only copy and is deletable on its own via
``delete_staged_document``. The on-disk Markdown report copy is removed the
same best-effort way ``app.store.reports`` writes it.

``app_logs`` carries a ``run_id`` column but likewise no foreign key --
log history is app-wide and meant to survive a run's normal lifecycle (see
``app.store.logs``) -- so a run's own log rows are not covered by the
cascade above. A *permanent* deletion is different: it exists so a
scientist can remove a run's data entirely, and the run's stage narrative
(its research goal included -- ``app.store.events`` mirrors every
``run_events`` row here) is exactly the kind of content that purpose
covers. Deletion therefore clears it explicitly, the same way
``app.logs_api``'s scoped ``DELETE /api/logs`` clears one client's rows
without touching the shared id sequence.
"""

from __future__ import annotations

import logging

from app.store.db import _reports_dir, connect
from app.store.logs import count_logs_for_run, delete_logs_for_run

logger = logging.getLogger(__name__)

# Tables cascade-deleted once the run row itself is gone, counted here only
# so a caller can prove the cascade actually ran rather than trusting the
# schema comment. Every one of these carries a ``run_id`` column reachable
# directly or through a FK chain rooted at ``runs``.
_RUN_ID_TABLES: tuple[str, ...] = (
    "run_credentials",
    "report_shares",
    "run_events",
    "scientific_tasks",
    "hypotheses",
    "evidence",
    "citations",
    "reviews",
    "matches",
    "safety_decisions",
    "reports",
    "messages",
    "checkpoints",
    "run_metrics",
    "claim_evidence",
    "knowledge_facts",
    "proximity_edges",
)

# hypothesis_state has no run_id column of its own; it cascades transitively
# once its hypothesis row is deleted, so it is counted through a join.
_HYPOTHESIS_SCOPED_TABLES: tuple[str, ...] = ("hypothesis_state",)


def count_run_rows(
    run_id: str, *, db_path: str | None = None
) -> dict[str, int]:
    """Count every row scoped to ``run_id``, across every affected table.

    Args:
        run_id: Identifier of the run to count rows for.
        db_path: Optional override for the SQLite database path.

    Returns:
        Table name -> row count. All zero (except a present ``runs`` row)
        once the run is gone confirms the cascade reached every table.
    """
    with connect(db_path) as conn:
        counts = {
            "runs": conn.execute(
                "SELECT COUNT(*) FROM runs WHERE id=?", (run_id,)
            ).fetchone()[0]
        }
        for table in _RUN_ID_TABLES:
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)
            ).fetchone()[0]
        for table in _HYPOTHESIS_SCOPED_TABLES:
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE hypothesis_id IN "
                "(SELECT id FROM hypotheses WHERE run_id=?)",
                (run_id,),
            ).fetchone()[0]
        counts["staged_documents"] = conn.execute(
            "SELECT COUNT(*) FROM staged_documents WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        counts["app_logs"] = count_logs_for_run(run_id, conn=conn)
    return counts


def _delete_report_markdown_file(run_id: str) -> None:
    """Best-effort remove the on-disk report Markdown copy, if any."""
    path = _reports_dir() / f"{run_id}.md"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete report markdown at %s", path)


def delete_run(run_id: str, *, db_path: str | None = None) -> dict[str, int]:
    """Permanently delete a run and every row that belongs to it.

    Args:
        run_id: Identifier of the run to delete.
        db_path: Optional override for the SQLite database path.

    Returns:
        The row counts that existed just before deletion (see
        ``count_run_rows``), for the caller to report or verify against.
    """
    before = count_run_rows(run_id, db_path=db_path)
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE staged_documents SET run_id=NULL WHERE run_id=?",
            (run_id,),
        )
        delete_logs_for_run(run_id, conn=conn)
        conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
    _delete_report_markdown_file(run_id)
    return before

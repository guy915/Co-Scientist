"""Atomic run admission and per-client capacity reservation."""

from __future__ import annotations

import sqlite3

from app.store.db import _now, transaction
from app.store.models import RunStatus
from app.store.runs_reconcile import _ACTIVE_RUN_STATUSES


def _count_other_active_runs(
    conn: sqlite3.Connection, run_id: str, client_id: str
) -> int:
    """Count the client's other in-flight runs, whatever tier they are.

    Deliberately blind to ``profile``: the quota is one ceiling per
    identity. Partitioning the count by tier as well made the effective
    allowance ``max_concurrent_runs`` per tier -- four times what is
    advertised, and reachable simply by naming a different tier each time.
    """
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM runs WHERE client_id=? "
            "AND status IN (?,?,?) AND id!=?",
            (client_id, *_ACTIVE_RUN_STATUSES, run_id),
        ).fetchone()[0]
    )


def _queue_run_if_startable(
    conn: sqlite3.Connection, run_id: str, now: float, expected_status: str
) -> int:
    """Move a run to QUEUED only from the status this start request read."""
    if expected_status not in {
        RunStatus.DRAFT.value,
        RunStatus.FAILED.value,
        RunStatus.BLOCKED.value,
        RunStatus.CANCELLED.value,
    }:
        return 0
    return conn.execute(
        "UPDATE runs SET status=?, updated_at=?, completed_at=NULL, "
        "error=NULL WHERE id=? AND status=?",
        (
            RunStatus.QUEUED.value,
            now,
            run_id,
            expected_status,
        ),
    ).rowcount


def reserve_run_capacity_in_transaction(
    conn: sqlite3.Connection,
    run_id: str,
    client_id: str,
    limit: int,
    expected_status: str,
) -> bool:
    """Reserve a client's run slot using the caller's active transaction."""
    count = _count_other_active_runs(conn, run_id, client_id)
    if count >= limit:
        return False
    changed = _queue_run_if_startable(conn, run_id, _now(), expected_status)
    return bool(changed)


def reserve_run_capacity(
    run_id: str,
    *,
    client_id: str,
    limit: int,
    expected_status: str,
    db_path: str | None = None,
) -> bool:
    """Atomically reserve one of the scientist's concurrency slots.

    One ceiling per identity, counted over every tier together: a caller
    that spreads its runs across tiers gets no extra allowance.

    Args:
        run_id: Startable run to transition to queued.
        client_id: Scientist ownership scope.
        limit: Maximum concurrent runs for the scientist.
        expected_status: Startable status observed by the API request.
        db_path: Optional override for the SQLite database path.

    Returns:
        True when the slot was reserved and the run queued; False when the
        quota was already full or the run was no longer startable.
    """
    with transaction(db_path) as active:
        return reserve_run_capacity_in_transaction(
            active, run_id, client_id, limit, expected_status
        )

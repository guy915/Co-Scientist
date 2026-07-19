"""Durable workflow-checkpoint persistence (Milestone 4).

Stores versioned checkpoint envelopes so an interrupted run can resume from its
last committed boundary rather than failing or restarting. One row per saved
checkpoint; :func:`get_latest_checkpoint` returns the newest by per-run
sequence. The envelope shape and its schema version are owned by the provider
(engine ``co_scientist.checkpoint`` or the mock); this module only persists and
retrieves it transactionally.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.store.db import _now, _use_conn


def save_checkpoint(
    run_id: str,
    *,
    stage: str,
    schema_version: int,
    last_event_seq: int,
    state: dict[str, Any],
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Persist one checkpoint for a run and return its per-run sequence.

    Args:
        run_id: Identifier of the run being checkpointed.
        stage: Provider stage/boundary label (e.g. ``"post_ranking"``).
        schema_version: Version of the checkpoint envelope shape.
        last_event_seq: The last durable event sequence at this boundary; a
            resumed run assigns new event seqs strictly above it.
        state: The JSON-serializable checkpoint envelope.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        The newly assigned per-run checkpoint sequence number.
    """
    with _use_conn(conn, db_path) as conn:
        # Assign the next per-run seq and insert in a single statement (the
        # same idiom as run_events' _append_event).
        row = conn.execute(
            "INSERT INTO checkpoints (run_id, seq, stage, schema_version, "
            "last_event_seq, state_json, created_at) VALUES (?, "
            "(SELECT COALESCE(MAX(seq), 0) + 1 FROM checkpoints "
            "WHERE run_id=?), ?, ?, ?, ?, ?) RETURNING seq",
            (
                run_id,
                run_id,
                stage,
                schema_version,
                last_event_seq,
                json.dumps(state),
                _now(),
            ),
        ).fetchone()
    return int(row["seq"])


def get_latest_checkpoint(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Return the newest checkpoint for a run, or None if it has none.

    Returns:
        A dict with ``seq``, ``stage``, ``schema_version``, ``last_event_seq``,
        and ``state`` (the deserialized envelope), or None.
    """
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            "SELECT seq, stage, schema_version, last_event_seq, state_json "
            "FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "seq": row["seq"],
        "stage": row["stage"],
        "schema_version": row["schema_version"],
        "last_event_seq": row["last_event_seq"],
        "state": json.loads(row["state_json"]),
    }


def has_checkpoint(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Return whether a run has any saved checkpoint (i.e. is resumable)."""
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM checkpoints WHERE run_id=? LIMIT 1",
            (run_id,),
        ).fetchone()
    return row is not None


def clear_checkpoints(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Delete all of a run's saved checkpoints.

    Used when a run is re-bootstrapped from scratch rather than resumed from
    a saved boundary (see ``runs._launch_resume``'s legacy-checkpoint
    fallback): the durable bootstrap task asserts it starts from an empty
    checkpoint history (``expected_checkpoint_seq=0``), so a stale envelope
    checkpoint left behind by ``clear_run_derived_data`` (which deliberately
    keeps checkpoints for the true-resume path) must be removed first.

    Args:
        run_id: Identifier of the run whose checkpoints to delete.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute("DELETE FROM checkpoints WHERE run_id=?", (run_id,))

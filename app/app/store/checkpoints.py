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

from app.store.db import _now, _use_conn, checkpoint_wal


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
        seq = int(row["seq"])
        # Drop the checkpoints this one supersedes. get_latest_checkpoint is
        # the only reader in the codebase, so any row below the newest seq is
        # already unreachable -- nothing can load it again. Each envelope is a
        # whole WorkflowState snapshot (hypotheses, reviews, literature, the
        # injected audience context), so keeping the history cost hundreds of
        # kilobytes per boundary crossed: in production it grew this table to
        # 380 MB, 97% of the database, and filled the volume until every
        # write failed with "database or disk is full". Pruning here keeps the
        # table proportional to the number of runs rather than to the number
        # of boundaries they cross. The newest row is always retained, so seq
        # stays monotonic (it is assigned as MAX(seq) + 1) and resume,
        # has_checkpoint, and the bootstrap's expected-seq assertions are all
        # unaffected.
        conn.execute(
            "DELETE FROM checkpoints WHERE run_id=? AND seq<?", (run_id, seq)
        )
    return seq


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


# The sweep exists to relieve a full volume, so it has to run *on* a full
# volume -- where every write, however small, can fail with SQLITE_FULL. Two
# things follow, and neither is about the size of the DELETE itself: dropping
# rows costs little journal space, since freed overflow pages go onto the
# freelist rather than being rewritten.
#
# First, the sweep needs headroom before it can write at all, so it folds the
# write-ahead log into the database and truncates it up front. A checkpoint
# rewrites pages at offsets the file already owns, so it does not need free
# space to succeed, and it hands back however many megabytes the WAL was
# holding.
#
# Second, progress has to be durable in pieces. A single statement across the
# whole history is all-or-nothing: one SQLITE_FULL and the work is rolled back,
# which is exactly how the first version of this sweep achieved nothing on the
# database it was written for. Committing a few rows at a time means whatever
# succeeded stays done and each fold returns more space to the next batch, so
# even a volume with almost nothing free converges over a few restarts.
_PRUNE_BATCH_ROWS = 4


def prune_superseded_checkpoints(
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Delete every checkpoint that a newer one for the same run supersedes.

    ``save_checkpoint`` now prunes as it writes, so this only has work to do
    on a database written before that: it applies the same rule retroactively.
    Each run keeps its newest checkpoint and loses the rest, which is exactly
    the set ``get_latest_checkpoint`` could never return. Runs stay resumable.

    Reclaims the write-ahead log first and then deletes in small committed
    batches, so it still makes progress on a volume with almost no free space
    -- see ``_PRUNE_BATCH_ROWS``. Safe to call on every startup: it is
    idempotent and a no-op once the history is gone.

    Args:
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse. When given, the caller owns
            the transaction and the whole sweep runs as one statement batch
            without WAL checkpoints, since it cannot commit on the caller's
            behalf.

    Returns:
        The number of superseded checkpoint rows deleted.
    """
    superseded = (
        "SELECT stale.rowid FROM checkpoints AS stale WHERE stale.seq < ("
        "SELECT MAX(newer.seq) FROM checkpoints AS newer "
        "WHERE newer.run_id = stale.run_id) LIMIT ?"
    )
    delete = f"DELETE FROM checkpoints WHERE rowid IN ({superseded})"

    if conn is not None:
        cur = conn.execute(delete, (-1,))
        return int(cur.rowcount or 0)

    # Buy headroom before attempting the first write.
    checkpoint_wal(db_path)

    total = 0
    while True:
        with _use_conn(None, db_path) as owned:
            deleted = int(
                (owned.execute(delete, (_PRUNE_BATCH_ROWS,)).rowcount) or 0
            )
        if deleted == 0:
            return total
        total += deleted
        checkpoint_wal(db_path)


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

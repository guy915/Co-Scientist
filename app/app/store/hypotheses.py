"""Hypothesis rows and their mutable tournament state.

The hypotheses table is append-only (`evolve` inserts children with
``parent_id`` set); the mutable fields (Elo, win/loss counts, novelty,
cluster) live in the separate hypothesis_state table and are the only
values updated in place.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from app.elo import INITIAL_ELO
from app.store.db import _now, _use_conn


def add_hypothesis(
    run_id: str,
    title: str,
    statement: str,
    *,
    hypothesis_id: str | None = None,
    parent_id: str | None = None,
    generation: int = 0,
    category: str | None = None,
    mechanism: str = "",
    expected_effect: str = "",
    experimental_context: str = "",
    created_by_agent: str = "generation",
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Insert a hypothesis row and its initial mutable state row.

    Args:
        run_id: Identifier of the run the hypothesis belongs to.
        title: Short title of the hypothesis.
        statement: Full hypothesis statement.
        hypothesis_id: Explicit row id to use. When omitted a fresh uuid4 is
            generated. The engine adapter passes the engine's stable hypothesis
            id here so ids stay consistent end-to-end (engine -> DB -> API ->
            UI); the mock path leaves it unset and gets a generated id.
        parent_id: Identifier of the parent hypothesis, set when evolving.
        generation: Generation number, 0 for originally generated hypotheses.
        category: Short classification label; drives the viewer breadcrumb.
        mechanism: Proposed mechanism underlying the hypothesis.
        expected_effect: Expected effect or outcome of the hypothesis.
        experimental_context: Context describing how to test the hypothesis.
        created_by_agent: Agent that created the row, e.g. 'generation'.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        The identifier of the newly inserted hypothesis.
    """
    hyp_id = hypothesis_id or str(uuid.uuid4())
    now = _now()
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO hypotheses (id, run_id, parent_id, generation, "
            "category, title, statement, mechanism, expected_effect, "
            "experimental_context, created_by_agent, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                hyp_id,
                run_id,
                parent_id,
                generation,
                category,
                title,
                statement,
                mechanism,
                expected_effect,
                experimental_context,
                created_by_agent,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO hypothesis_state (hypothesis_id, elo_rating, "
            "updated_at) VALUES (?,?,?)",
            (hyp_id, INITIAL_ELO, now),
        )
    return hyp_id


def _hypothesis_state_updates(
    *,
    elo_rating: int | None,
    win_delta: int,
    loss_delta: int,
    novelty: float | None,
    cluster_id: str | None,
) -> list[tuple[str, Any]]:
    """Return the (SQL fragment, value) pairs for the provided fields.

    Only fields whose arguments are provided are included. Deltas use
    relative SQL updates (col=col+?) so concurrent writers do not clobber
    counts, so they are included only when non-zero; the rest are included
    whenever explicitly set (not None).
    """
    candidates: tuple[tuple[bool, str, Any], ...] = (
        (elo_rating is not None, "elo_rating=?", elo_rating),
        (bool(win_delta), "win_count=win_count+?", win_delta),
        (bool(loss_delta), "loss_count=loss_count+?", loss_delta),
        (novelty is not None, "novelty_score=?", novelty),
        (cluster_id is not None, "cluster_id=?", cluster_id),
    )
    return [
        (fragment, value) for active, fragment, value in candidates if active
    ]


def update_hypothesis_state(
    hypothesis_id: str,
    *,
    elo_rating: int | None = None,
    win_delta: int = 0,
    loss_delta: int = 0,
    novelty: float | None = None,
    cluster_id: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Update selected mutable-state fields for a hypothesis.

    Only the fields whose arguments are provided are updated; the rest are
    left untouched.

    Args:
        hypothesis_id: Identifier of the hypothesis to update.
        elo_rating: New absolute Elo rating to set.
        win_delta: Amount to add to the win count.
        loss_delta: Amount to add to the loss count.
        novelty: New novelty score to set.
        cluster_id: New proximity cluster identifier to set.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    # Build the SET clause dynamically from trusted literal fragments; user
    # data only ever flows through the bound `params`.
    updates = _hypothesis_state_updates(
        elo_rating=elo_rating,
        win_delta=win_delta,
        loss_delta=loss_delta,
        novelty=novelty,
        cluster_id=cluster_id,
    )
    sets = [fragment for fragment, _ in updates] + ["updated_at=?"]
    params: list[Any] = [value for _, value in updates] + [
        _now(),
        hypothesis_id,
    ]
    set_clause = ", ".join(sets)
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            f"UPDATE hypothesis_state SET {set_clause} WHERE hypothesis_id=?",
            params,
        )


# Shared hypothesis + mutable-state projection. `add_hypothesis` always inserts
# the state row, so the joined columns are COALESCE'd to their column defaults
# and consumers can rely on them being non-null.
_HYP_SELECT = (
    f"SELECT h.*, COALESCE(s.elo_rating, {INITIAL_ELO}) AS elo_rating, "
    "COALESCE(s.win_count, 0) AS win_count, "
    "COALESCE(s.loss_count, 0) AS loss_count, "
    "s.novelty_score, s.plausibility_score, "
    "s.testability_score, s.safety_status, s.status, s.cluster_id "
    "FROM hypotheses h LEFT JOIN hypothesis_state s ON h.id=s.hypothesis_id "
)


def list_hypotheses(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's hypotheses joined with mutable state, best Elo first."""
    with _use_conn(conn, db_path) as conn:
        # Consumers (API, Q&A prompt builder) rely on this Elo-descending
        # order; created_at breaks ties deterministically.
        rows = conn.execute(
            _HYP_SELECT
            + "WHERE h.run_id=? ORDER BY s.elo_rating DESC, h.created_at ASC",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_hypothesis(
    hypothesis_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Return one hypothesis joined with its mutable state, or None."""
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            _HYP_SELECT + "WHERE h.id=?",
            (hypothesis_id,),
        ).fetchone()
        return dict(row) if row else None

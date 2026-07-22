"""Hypothesis rows and their mutable tournament state.

The hypotheses table is append-only (`evolve` inserts children with
``parent_id`` set); the mutable fields (Elo, win/loss counts, novelty,
cluster) live in the separate hypothesis_state table and are the only
values updated in place.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.elo import INITIAL_ELO
from app.store.db import _now, _use_conn


@dataclass(frozen=True)
class _NewHypothesisFields:
    """Fields needed to insert a hypothesis row and its state row."""

    hyp_id: str
    run_id: str
    parent_id: str | None
    generation: int
    category: str | None
    title: str
    statement: str
    mechanism: str
    expected_effect: str
    experimental_context: str
    created_by_agent: str
    author: str
    now: float


def _insert_hypothesis_rows(
    conn: sqlite3.Connection, f: _NewHypothesisFields
) -> None:
    """Insert the hypothesis row and its initial mutable-state row."""
    conn.execute(
        "INSERT INTO hypotheses (id, run_id, parent_id, generation, "
        "category, title, statement, mechanism, expected_effect, "
        "experimental_context, created_by_agent, author, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            f.hyp_id,
            f.run_id,
            f.parent_id,
            f.generation,
            f.category,
            f.title,
            f.statement,
            f.mechanism,
            f.expected_effect,
            f.experimental_context,
            f.created_by_agent,
            f.author,
            f.now,
        ),
    )
    conn.execute(
        "INSERT INTO hypothesis_state (hypothesis_id, elo_rating, "
        "updated_at) VALUES (?,?,?)",
        (f.hyp_id, INITIAL_ELO, f.now),
    )


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
    author: str = "",
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
        author: Authorship provenance for a scientist-contributed hypothesis;
            empty for agent-generated ones.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        The identifier of the newly inserted hypothesis.
    """
    hyp_id = hypothesis_id or str(uuid.uuid4())
    fields = _NewHypothesisFields(
        hyp_id=hyp_id,
        run_id=run_id,
        parent_id=parent_id,
        generation=generation,
        category=category,
        title=title,
        statement=statement,
        mechanism=mechanism,
        expected_effect=expected_effect,
        experimental_context=experimental_context,
        created_by_agent=created_by_agent,
        author=author,
        now=_now(),
    )
    with _use_conn(conn, db_path) as conn:
        _insert_hypothesis_rows(conn, fields)
    return hyp_id


def _hypothesis_state_updates(
    *,
    elo_rating: int | None,
    win_delta: int,
    loss_delta: int,
    novelty: float | None,
    cluster_id: str | None,
    safety_status: str | None,
    status: str | None,
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
        (safety_status is not None, "safety_status=?", safety_status),
        (status is not None, "status=?", status),
    )
    return [
        (fragment, value) for active, fragment, value in candidates if active
    ]


def _persist_hypothesis_state_update(
    conn: sqlite3.Connection,
    hypothesis_id: str,
    updates: list[tuple[str, Any]],
) -> None:
    """Apply a dynamic SET-clause update to hypothesis_state.

    Builds the SET clause from trusted literal fragments only; user data
    flows exclusively through the bound `params`.
    """
    sets = [fragment for fragment, _ in updates] + ["updated_at=?"]
    params: list[Any] = [value for _, value in updates] + [
        _now(),
        hypothesis_id,
    ]
    set_clause = ", ".join(sets)
    conn.execute(
        f"UPDATE hypothesis_state SET {set_clause} WHERE hypothesis_id=?",
        params,
    )


def update_hypothesis_state(
    hypothesis_id: str,
    *,
    elo_rating: int | None = None,
    win_delta: int = 0,
    loss_delta: int = 0,
    novelty: float | None = None,
    cluster_id: str | None = None,
    safety_status: str | None = None,
    status: str | None = None,
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
        safety_status: New per-hypothesis safety status (e.g. 'allow',
            'redact', 'blocked') from the pre-tournament safety review.
        status: New lifecycle status, such as active or review-rejected.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    updates = _hypothesis_state_updates(
        elo_rating=elo_rating,
        win_delta=win_delta,
        loss_delta=loss_delta,
        novelty=novelty,
        cluster_id=cluster_id,
        safety_status=safety_status,
        status=status,
    )
    with _use_conn(conn, db_path) as conn:
        _persist_hypothesis_state_update(conn, hypothesis_id, updates)


# Text columns the safety review may redact in place. The hypotheses table is
# otherwise append-only; redaction is the one sanctioned mutation (safety
# overrides immutability -- see hypothesis_safety.redact_fields).
_REDACTABLE_COLUMNS = frozenset({"mechanism", "experimental_context"})


def redact_hypothesis_fields(
    hypothesis_id: str,
    fields: dict[str, str],
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Overwrite a hypothesis's sensitive text columns with redacted values.

    Args:
        hypothesis_id: Identifier of the hypothesis to redact.
        fields: Mapping of column name to redacted replacement text. Only
            the redactable detail columns are accepted.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Raises:
        ValueError: If ``fields`` names a column that is not redactable.
    """
    unknown = set(fields) - _REDACTABLE_COLUMNS
    if unknown:
        raise ValueError(
            f"non-redactable hypothesis columns: {sorted(unknown)}"
        )
    if not fields:
        return
    # Column names are validated against the literal allowlist above; user
    # data only ever flows through the bound values.
    set_clause = ", ".join(f"{column}=?" for column in sorted(fields))
    params = [fields[column] for column in sorted(fields)]
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            f"UPDATE hypotheses SET {set_clause} WHERE id=?",
            (*params, hypothesis_id),
        )


# Shared hypothesis + mutable-state projection. `add_hypothesis` always
# inserts the state row, and the tournament counters are additionally
# COALESCE'd to their defaults as a guard, so consumers can rely on
# elo_rating/win_count/loss_count being non-null. The remaining state
# columns are selected raw and stay nullable (e.g. novelty_score before
# any review lands), so consumers must handle None for those.
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

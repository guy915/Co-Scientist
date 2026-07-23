"""Hypothesis rows and their mutable tournament state.

The hypotheses table is append-only (`evolve` inserts children with
``parent_id`` set); the mutable fields (Elo, win/loss counts, novelty,
cluster) live in the separate hypothesis_state table and are the only
values updated in place.

Every helper accepts ``db_path`` (override for the SQLite database path)
and ``conn`` (an open connection to reuse, e.g. from ``transaction``).
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.elo import INITIAL_ELO
from app.store.db import _now, _use_conn


@dataclass(frozen=True)
class NewHypothesis:
    """One hypothesis row to insert, mirroring the hypotheses table.

    ``hypothesis_id`` is the engine's stable hypothesis id when the engine
    adapter inserts (so ids stay consistent engine -> DB -> API -> UI) and
    None to have a fresh uuid4 assigned. ``generation`` is 0 for
    originally generated hypotheses; ``category`` is a short
    classification label that drives the viewer breadcrumb;
    ``created_by_agent`` names the creating agent (e.g. 'generation');
    ``author`` records authorship provenance for a scientist-contributed
    hypothesis and stays empty for agent-generated ones.
    """

    run_id: str
    title: str
    statement: str
    hypothesis_id: str | None = None
    parent_id: str | None = None
    generation: int = 0
    category: str | None = None
    mechanism: str = ""
    expected_effect: str = ""
    experimental_context: str = ""
    created_by_agent: str = "generation"
    author: str = ""


def _insert_hypothesis_rows(
    conn: sqlite3.Connection, hyp_id: str, f: NewHypothesis, now: float
) -> None:
    """Insert the hypothesis row and its initial mutable-state row."""
    conn.execute(
        "INSERT INTO hypotheses (id, run_id, parent_id, generation, "
        "category, title, statement, mechanism, expected_effect, "
        "experimental_context, created_by_agent, author, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            hyp_id,
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
            now,
        ),
    )
    conn.execute(
        "INSERT INTO hypothesis_state (hypothesis_id, elo_rating, "
        "updated_at) VALUES (?,?,?)",
        (hyp_id, INITIAL_ELO, now),
    )


def add_hypothesis(
    hypothesis: NewHypothesis,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Insert a hypothesis row and its state row; return the row id.

    Args:
        hypothesis: The hypothesis to insert (see
            :class:`NewHypothesis`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        The identifier of the new hypothesis row.
    """
    hyp_id = hypothesis.hypothesis_id or str(uuid.uuid4())
    with _use_conn(conn, db_path) as conn:
        _insert_hypothesis_rows(conn, hyp_id, hypothesis, _now())
    return hyp_id


@dataclass(frozen=True)
class HypothesisStateChanges:
    """The mutable hypothesis-state fields a caller wants to change.

    Only the fields set here are written. The deltas add to the win/loss
    counts (and are skipped when zero); every other field sets an absolute
    value and is skipped while None. ``safety_status`` is the
    pre-tournament safety review's per-hypothesis status (e.g. 'allow',
    'redact', 'blocked'); ``status`` is the lifecycle status, such as
    active or review-rejected.
    """

    elo_rating: int | None = None
    win_delta: int = 0
    loss_delta: int = 0
    novelty: float | None = None
    cluster_id: str | None = None
    safety_status: str | None = None
    status: str | None = None


def _hypothesis_state_updates(
    changes: HypothesisStateChanges,
) -> list[tuple[str, Any]]:
    """Return the (SQL fragment, value) pairs for the provided fields.

    Only fields whose arguments are provided are included. Deltas use
    relative SQL updates (col=col+?) so concurrent writers do not clobber
    counts, so they are included only when non-zero; the rest are included
    whenever explicitly set (not None).
    """
    c = changes
    candidates: tuple[tuple[bool, str, Any], ...] = (
        (c.elo_rating is not None, "elo_rating=?", c.elo_rating),
        (bool(c.win_delta), "win_count=win_count+?", c.win_delta),
        (bool(c.loss_delta), "loss_count=loss_count+?", c.loss_delta),
        (c.novelty is not None, "novelty_score=?", c.novelty),
        (c.cluster_id is not None, "cluster_id=?", c.cluster_id),
        (c.safety_status is not None, "safety_status=?", c.safety_status),
        (c.status is not None, "status=?", c.status),
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
    changes: HypothesisStateChanges,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Update selected mutable-state fields for a hypothesis.

    Args:
        hypothesis_id: Identifier of the hypothesis to update.
        changes: The fields to write (see
            :class:`HypothesisStateChanges`); everything else is left
            untouched.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    updates = _hypothesis_state_updates(changes)
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

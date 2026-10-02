"""Hypothesis rows and their mutable tournament state.

The hypotheses table is append-only (`evolve` inserts children with
``parent_id`` set); the mutable fields (Elo, win/loss counts, novelty,
cluster) live in the separate hypothesis_state table and are the only
values updated in place.

Every helper accepts ``db_path`` (override for the SQLite database path)
and ``conn`` (an open connection to reuse, e.g. from ``transaction``).
"""

from __future__ import annotations

import json
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
    ``creation_iteration`` is the authoring-cycle ordinal the engine stamps
    at creation (0 for the initial generation, N for a later
    research-expansion/evolution cycle), the run's true timeline axis; it
    stays None for a scientist-contributed hypothesis, which has no cycle.
    ``created_by_agent`` names the creating agent (e.g. 'generation');
    ``author`` records authorship provenance for a scientist-contributed
    hypothesis and stays empty for agent-generated ones. ``parent_ids`` is
    the full multi-parent lineage for combination children (JSON-encoded on
    write); it stays None when ``parent_id`` alone is the whole lineage.
    ``introduction``/``recent_findings`` are the published proposal's
    scene-setting sections (MO-6). ``safety_and_toxicity`` is the
    proposer's own pharmacological safety assessment (MO-10), distinct
    from the reviewer's ethics/dual-use judgement and never consulted by
    the safety gate.
    """

    run_id: str
    title: str
    statement: str
    hypothesis_id: str | None = None
    parent_id: str | None = None
    parent_ids: list[str] | None = None
    generation: int = 0
    creation_iteration: int | None = None
    category: str | None = None
    mechanism: str = ""
    expected_effect: str = ""
    experimental_context: str = ""
    introduction: str = ""
    recent_findings: str = ""
    safety_and_toxicity: str = ""
    created_by_agent: str = "generation"
    author: str = ""


def _parent_ids_json(parent_ids: list[str] | None) -> str | None:
    """Encode a multi-parent lineage list for storage, or None."""
    if not parent_ids:
        return None
    return json.dumps(parent_ids)


# Re-persisting a row the store already holds is normal, not an error: a
# scientist-contributed hypothesis is written at POST time, merged into
# engine state, and then arrives again in the final-state drain -- which
# used to fail the whole finalize with "UNIQUE constraint failed:
# hypotheses.id" and leave the run unable to complete. The row that is
# already there wins on everything that identifies it (id, run, author,
# created_by_agent, generation, parent lineage, title, statement): the
# engine never rewrites a hypothesis in place -- evolution mints a child
# with a new id -- so a conflicting id is the same idea, not a revision of
# it. (The round trip does now carry the author, on the payload's
# ``enrichments``, so an *insert* attributes a contributed hypothesis
# correctly; a conflict still keeps the stored value.) Only the
# engine-derived detail columns are filled, and only where the stored row
# has nothing, so a drain adds what the run learned without overwriting
# what the scientist wrote.
_HYPOTHESIS_UPSERT = (
    "INSERT INTO hypotheses (id, run_id, parent_id, parent_ids, "
    "generation, creation_iteration, category, title, statement, mechanism, "
    "expected_effect, "
    "experimental_context, introduction, recent_findings, "
    "safety_and_toxicity, created_by_agent, author, created_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(id) DO UPDATE SET "
    "creation_iteration=COALESCE("
    "hypotheses.creation_iteration, excluded.creation_iteration), "
    "category=COALESCE(hypotheses.category, excluded.category), "
    "mechanism=COALESCE(NULLIF(hypotheses.mechanism, ''), "
    "excluded.mechanism), "
    "expected_effect=COALESCE(NULLIF(hypotheses.expected_effect, ''), "
    "excluded.expected_effect), "
    "experimental_context=COALESCE("
    "NULLIF(hypotheses.experimental_context, ''), "
    "excluded.experimental_context), "
    "introduction=COALESCE(NULLIF(hypotheses.introduction, ''), "
    "excluded.introduction), "
    "recent_findings=COALESCE(NULLIF(hypotheses.recent_findings, ''), "
    "excluded.recent_findings), "
    "safety_and_toxicity=COALESCE("
    "NULLIF(hypotheses.safety_and_toxicity, ''), "
    "excluded.safety_and_toxicity)"
)

# The mutable-state row is created once and thereafter only updated, so a
# re-persisted hypothesis keeps the safety_status its screening set and the
# tournament counters it has accumulated. The drain writes Elo and status
# immediately afterwards (see drain.hypotheses._persist_hypothesis_state).
_HYPOTHESIS_STATE_INSERT = (
    "INSERT INTO hypothesis_state (hypothesis_id, elo_rating, updated_at) "
    "VALUES (?,?,?) ON CONFLICT(hypothesis_id) DO NOTHING"
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
        now = _now()
        conn.execute(
            _HYPOTHESIS_UPSERT,
            (
                hyp_id,
                hypothesis.run_id,
                hypothesis.parent_id,
                _parent_ids_json(hypothesis.parent_ids),
                hypothesis.generation,
                hypothesis.creation_iteration,
                hypothesis.category,
                hypothesis.title,
                hypothesis.statement,
                hypothesis.mechanism,
                hypothesis.expected_effect,
                hypothesis.experimental_context,
                hypothesis.introduction,
                hypothesis.recent_findings,
                hypothesis.safety_and_toxicity,
                hypothesis.created_by_agent,
                hypothesis.author,
                now,
            ),
        )
        conn.execute(_HYPOTHESIS_STATE_INSERT, (hyp_id, INITIAL_ELO, now))
    return hyp_id


@dataclass(frozen=True)
class HypothesisStateChanges:
    """The mutable hypothesis-state fields a caller wants to change.

    Only the fields set here are written. The deltas add to the win/loss
    counts (and are skipped when zero); every other field sets an absolute
    value and is skipped while None. ``safety_status`` is the
    pre-tournament safety review's per-hypothesis status (e.g. 'allow',
    'redact', 'blocked'); ``status`` is the lifecycle status, such as
    active or review-rejected; ``verification_verdict`` is deep
    verification's own verdict, which no longer decides ``status`` and so
    has to travel on its own.
    """

    elo_rating: int | None = None
    win_delta: int = 0
    loss_delta: int = 0
    novelty: float | None = None
    cluster_id: str | None = None
    safety_status: str | None = None
    status: str | None = None
    verification_verdict: str | None = None


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
        (
            c.verification_verdict is not None,
            "verification_verdict=?",
            c.verification_verdict,
        ),
    )
    return [
        (fragment, value) for active, fragment, value in candidates if active
    ]


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


# Text columns the safety review may redact in place. The hypotheses table is
# otherwise append-only; redaction is the one sanctioned mutation (safety
# overrides immutability -- see hypothesis.safety.redact_fields).
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
    "s.testability_score, s.safety_status, s.status, s.cluster_id, "
    "s.verification_verdict "
    "FROM hypotheses h LEFT JOIN hypothesis_state s ON h.id=s.hypothesis_id "
)


def _decode_parent_ids(row: dict[str, Any]) -> dict[str, Any]:
    """Decode the stored parent_ids JSON into a list (or leave it None).

    The column stores a JSON array for multi-parent combination children and
    NULL otherwise, so a row's lineage reaches API consumers as a real list
    rather than an opaque string. A value that fails to parse degrades to
    None rather than raising on read.
    """
    raw = row.get("parent_ids")
    if raw is None:
        return row
    try:
        row["parent_ids"] = json.loads(raw)
    except (TypeError, ValueError):
        row["parent_ids"] = None
    return row


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
        return [_decode_parent_ids(dict(r)) for r in rows]


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
        return _decode_parent_ids(dict(row)) if row else None

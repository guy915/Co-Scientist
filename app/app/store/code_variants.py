"""Code variants and their evaluation state.

Mirrors ``store/hypotheses.py``: ``code_variants`` is append-only, and
every value that changes after insertion lives in ``code_variant_state``.
Metrics and artifacts hang off the variant in their own tables because
one is charted across hundreds of rows and the other can be a whole
traceback.

Every helper accepts ``db_path`` (override for the SQLite database path)
and ``conn`` (an open connection to reuse, e.g. from ``transaction``).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.store.db import _now, _use_conn

# Status a variant carries between being proposed and being evaluated.
# Every other value comes from code_eval.EvaluationStatus.
PENDING_STATUS = "pending"


@dataclass(frozen=True)
class NewCodeVariant:
    """One variant row to insert, mirroring the code_variants table.

    ``variant_id`` is the engine's stable id when the adapter inserts, and
    None to have a fresh uuid4 assigned. ``parent_id`` is None for the
    seed program only. ``operator`` names the code operator that produced
    this child -- it is what labels the edge in the lineage graph, so a
    child minted without one is legible as a variant but not as a move.
    ``source`` is the whole program at this variant, ``{path: contents}``.
    """

    run_id: str
    source: dict[str, str]
    variant_id: str | None = None
    parent_id: str | None = None
    generation: int = 0
    operator: str | None = None
    rationale: str = ""
    diff: str = ""
    created_by_agent: str = "code_evolve"


@dataclass(frozen=True)
class VariantEvaluation:
    """What one evaluation of a variant produced.

    ``fitness`` is already sign-corrected by the objective, so higher is
    better here whatever the underlying metric measures. It is None when
    nothing usable was reported -- which is not the same as zero, and the
    two must not be collapsed: a variant that failed to run has no
    position in the ordering, while one that scored zero does.

    ``metrics`` holds the raw reported values, uncorrected, so a report
    can still say "latency 0.8s" rather than "-0.8". ``artifacts`` is the
    evidence a failure leaves behind (stderr, the failing stage), which is
    what the next proposal prompt reads.
    """

    status: str
    fitness: float | None = None
    objective_values: list[float | None] = field(default_factory=list)
    behaviour: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float | None = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


_VARIANT_INSERT = (
    "INSERT INTO code_variants (id, run_id, parent_id, generation, "
    "ordinal, operator, rationale, diff, source_json, created_by_agent, "
    "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(id) DO NOTHING"
)

_VARIANT_STATE_INSERT = (
    "INSERT INTO code_variant_state (variant_id, status, updated_at) "
    "VALUES (?,?,?) ON CONFLICT(variant_id) DO NOTHING"
)


def _next_ordinal(conn: sqlite3.Connection, run_id: str) -> int:
    """Allocates the next dense attempt number within a run.

    Safe as a read-then-write because the store has exactly one writer
    (see the single-replica note in AGENTS.md) and callers hold the
    transaction across both statements.
    """
    row = conn.execute(
        "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM code_variants "
        "WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])


def add_code_variant(
    variant: NewCodeVariant,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Inserts a variant row and its pending state row; returns the id.

    Args:
        variant: The variant to insert (see :class:`NewCodeVariant`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        The identifier of the new variant row.
    """
    variant_id = variant.variant_id or str(uuid.uuid4())
    now = _now()
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            _VARIANT_INSERT,
            (
                variant_id,
                variant.run_id,
                variant.parent_id,
                variant.generation,
                _next_ordinal(conn, variant.run_id),
                variant.operator,
                variant.rationale,
                variant.diff,
                json.dumps(variant.source),
                variant.created_by_agent,
                now,
            ),
        )
        conn.execute(_VARIANT_STATE_INSERT, (variant_id, PENDING_STATUS, now))
    return variant_id


def _write_state(
    conn: sqlite3.Connection, variant_id: str, ev: VariantEvaluation
) -> None:
    """Writes the mutable evaluation row for one variant."""
    conn.execute(
        "UPDATE code_variant_state SET status = ?, fitness = ?, "
        "objective_values_json = ?, behaviour_json = ?, "
        "duration_seconds = ?, stages_json = ?, updated_at = ? "
        "WHERE variant_id = ?",
        (
            ev.status,
            ev.fitness,
            json.dumps(ev.objective_values),
            json.dumps(ev.behaviour),
            ev.duration_seconds,
            json.dumps(ev.stages),
            _now(),
            variant_id,
        ),
    )


def _write_side_tables(
    conn: sqlite3.Connection, variant_id: str, ev: VariantEvaluation
) -> None:
    """Replaces the metric and artifact rows for one variant.

    Deleted first rather than upserted so that a re-evaluation reporting
    fewer metrics does not leave the previous run's extras behind, which
    would read as a variant that reports two different metric sets.
    """
    conn.execute(
        "DELETE FROM code_variant_metrics WHERE variant_id = ?", (variant_id,)
    )
    conn.executemany(
        "INSERT INTO code_variant_metrics (variant_id, name, value) "
        "VALUES (?,?,?)",
        [(variant_id, name, value) for name, value in ev.metrics.items()],
    )
    conn.execute(
        "DELETE FROM code_variant_artifacts WHERE variant_id = ?",
        (variant_id,),
    )
    conn.executemany(
        "INSERT INTO code_variant_artifacts (variant_id, kind, content) "
        "VALUES (?,?,?)",
        [(variant_id, kind, text) for kind, text in ev.artifacts.items()],
    )


def _refresh_best_so_far(conn: sqlite3.Connection, run_id: str) -> None:
    """Recomputes the running-best flag across a run, by ordinal.

    Recomputed rather than decided once at evaluation time because
    variants are evaluated concurrently and therefore land out of order:
    a variant that finishes early can only be compared against the
    lower-ordinal siblings that happen to have finished already, and when
    a slower one lands the earlier answer becomes wrong. Since the flag
    exists to spare the breakthrough plot a running maximum on every
    read, it has to be right for every prefix, not just the newest one.

    Only rows whose flag actually changes are written -- a variant landing
    late in a long run otherwise rewrites hundreds of unchanged rows, and
    this is the single-writer store.
    """
    rows = conn.execute(
        "SELECT v.id, s.fitness, s.is_best_so_far FROM code_variants v "
        "JOIN code_variant_state s ON s.variant_id = v.id "
        "WHERE v.run_id = ? ORDER BY v.ordinal",
        (run_id,),
    ).fetchall()
    best: float | None = None
    for variant_id, fitness, was_best in rows:
        is_best = fitness is not None and (best is None or fitness > best)
        if is_best:
            best = fitness
        if int(was_best) != int(is_best):
            conn.execute(
                "UPDATE code_variant_state SET is_best_so_far = ? "
                "WHERE variant_id = ?",
                (int(is_best), variant_id),
            )


def record_variant_evaluation(
    variant_id: str,
    evaluation: VariantEvaluation,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Records the outcome of evaluating one variant.

    Args:
        variant_id: The variant that was evaluated.
        evaluation: Its outcome (see :class:`VariantEvaluation`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.
    """
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            "SELECT run_id FROM code_variants WHERE id = ?", (variant_id,)
        ).fetchone()
        if row is None:
            return
        _write_state(conn, variant_id, evaluation)
        _write_side_tables(conn, variant_id, evaluation)
        _refresh_best_so_far(conn, str(row[0]))


_VARIANT_SELECT = (
    "SELECT v.id, v.run_id, v.parent_id, v.generation, v.ordinal, "
    "v.operator, v.rationale, v.diff, v.source_json, v.created_by_agent, "
    "v.created_at, s.status, s.fitness, s.is_best_so_far, "
    "s.duration_seconds, s.stages_json, s.objective_values_json, "
    "s.behaviour_json FROM code_variants v "
    "JOIN code_variant_state s ON s.variant_id = v.id"
)


def _variant_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Shapes one joined variant row for the API layer."""
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "parent_id": row["parent_id"],
        "generation": row["generation"],
        "ordinal": row["ordinal"],
        "operator": row["operator"],
        "rationale": row["rationale"],
        "diff": row["diff"],
        "source": json.loads(row["source_json"]),
        "created_by_agent": row["created_by_agent"],
        "created_at": row["created_at"],
        "status": row["status"],
        "fitness": row["fitness"],
        "is_best_so_far": bool(row["is_best_so_far"]),
        "duration_seconds": row["duration_seconds"],
        "stages": json.loads(row["stages_json"] or "[]"),
        "objective_values": json.loads(row["objective_values_json"] or "[]"),
        "behaviour": json.loads(row["behaviour_json"] or "{}"),
    }


def list_code_variants(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Lists a run's variants in attempt order, failures included.

    Ordered by ordinal rather than by fitness because the sequence is
    itself the finding: how many attempts a breakthrough took is only
    readable if the attempts that went nowhere are still in the list.
    """
    with _use_conn(conn, db_path) as conn:
        rows = conn.execute(
            f"{_VARIANT_SELECT} WHERE v.run_id = ? ORDER BY v.ordinal",
            (run_id,),
        ).fetchall()
    return [_variant_row_to_dict(row) for row in rows]


def get_code_variant(
    variant_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Returns one variant with its metrics and artifacts, or None."""
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            f"{_VARIANT_SELECT} WHERE v.id = ?", (variant_id,)
        ).fetchone()
        if row is None:
            return None
        variant = _variant_row_to_dict(row)
        variant["metrics"] = dict(
            conn.execute(
                "SELECT name, value FROM code_variant_metrics "
                "WHERE variant_id = ? ORDER BY name",
                (variant_id,),
            )
        )
        variant["artifacts"] = dict(
            conn.execute(
                "SELECT kind, content FROM code_variant_artifacts "
                "WHERE variant_id = ? ORDER BY kind",
                (variant_id,),
            )
        )
    return variant


def best_code_variant(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Returns the run's highest-fitness variant, or None if none scored.

    Ties break toward the earlier attempt: when two variants reach the
    same score, the one that got there first is the result, and the later
    one is a reproduction of it.
    """
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            f"{_VARIANT_SELECT} WHERE v.run_id = ? AND s.fitness IS NOT NULL "
            "ORDER BY s.fitness DESC, v.ordinal ASC LIMIT 1",
            (run_id,),
        ).fetchone()
    return None if row is None else _variant_row_to_dict(row)


def save_code_dataset(
    run_id: str,
    files: dict[str, str],
    *,
    db_path: str | None = None,
    conn: Any = None,
) -> None:
    """Stores a run's read-only dataset, replacing anything there.

    Written once at creation. Kept out of ``code_variants`` because the
    proposal agent rewrites every file it is handed, and out of the run
    config because that row is read by every task of every type.
    """
    with _use_conn(conn, db_path) as active:
        active.execute("DELETE FROM code_datasets WHERE run_id = ?", (run_id,))
        active.executemany(
            "INSERT INTO code_datasets (run_id, path, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            [(run_id, path, text, _now()) for path, text in files.items()],
        )


def get_code_dataset(
    run_id: str, *, db_path: str | None = None, conn: Any = None
) -> dict[str, str]:
    """Returns a run's dataset as ``{path: contents}``."""
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT path, content FROM code_datasets WHERE run_id = ? "
            "ORDER BY path",
            (run_id,),
        ).fetchall()
    return {str(row["path"]): str(row["content"]) for row in rows}

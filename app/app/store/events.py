"""Append-only run event log."""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from typing import Any, cast

from app.store.db import _now, _use_conn, connect

logger = logging.getLogger(__name__)

ACTIVITY_PLANNING = "planning"
ACTIVITY_LITERATURE_SEARCH = "literature_search"
ACTIVITY_DRAFTING = "drafting"
ACTIVITY_REVIEW = "review"
ACTIVITY_TOURNAMENT = "tournament"
ACTIVITY_EVOLUTION = "evolution"
ACTIVITY_DEDUPLICATION = "deduplication"
ACTIVITY_SAFETY = "safety"
ACTIVITY_SYNTHESIS = "synthesis"
ACTIVITY_OTHER = "other"

ACTIVITY_VALUES: frozenset[str] = frozenset(
    {
        ACTIVITY_PLANNING,
        ACTIVITY_LITERATURE_SEARCH,
        ACTIVITY_DRAFTING,
        ACTIVITY_REVIEW,
        ACTIVITY_TOURNAMENT,
        ACTIVITY_EVOLUTION,
        ACTIVITY_DEDUPLICATION,
        ACTIVITY_SAFETY,
        ACTIVITY_SYNTHESIS,
        ACTIVITY_OTHER,
    }
)

# Engine agent name (a NODE_TO_AGENT value) -> activity. Covers every node
# whose whole owning agent shares one activity.
_AGENT_ACTIVITY: dict[str, str] = {
    "supervisor": ACTIVITY_PLANNING,
    "reflection": ACTIVITY_REVIEW,
    "ranking": ACTIVITY_TOURNAMENT,
    "evolution": ACTIVITY_EVOLUTION,
    "proximity": ACTIVITY_DEDUPLICATION,
    "meta_review": ACTIVITY_SYNTHESIS,
    "safety": ACTIVITY_SAFETY,
}

# Node-level overrides: the ``generation`` agent owns both the literature
# search and the drafting node, which are two different activities, so the
# agent-level table above cannot resolve them on its own.
_NODE_ACTIVITY_OVERRIDES: dict[str, str] = {
    "literature_review": ACTIVITY_LITERATURE_SEARCH,
    "generate": ACTIVITY_DRAFTING,
}

# The canonical event vocabulary (app.engine_adapter.events) renames the
# ``supervisor`` node to ``supervisor.plan`` wherever it appears as a run
# event's own type (the demo/seed path writes canonical node names
# directly). Resolved back to the node name before the lookup below.
_TYPE_TO_NODE_ALIASES: dict[str, str] = {"supervisor.plan": "supervisor"}


def _node_to_agent() -> dict[str, str]:
    """Return the engine's node -> agent table.

    Imported lazily so this lightweight, store-layer module never forces an
    eager import of the engine package at ``app.store`` import time. The
    engine package is exempted from mypy's ``follow_imports`` here (see
    ``app/pyproject.toml``), so the cast restates the type its own
    annotation already declares.
    """
    from co_scientist.agents import NODE_TO_AGENT

    return cast("dict[str, str]", NODE_TO_AGENT)


def _activity_for_node(node_name: str) -> str:
    """Resolve one engine node name to its activity, or the catch-all."""
    override = _NODE_ACTIVITY_OVERRIDES.get(node_name)
    if override is not None:
        return override
    agent = _node_to_agent().get(node_name)
    if agent is None:
        return ACTIVITY_OTHER
    return _AGENT_ACTIVITY.get(agent, ACTIVITY_OTHER)


def activity_for_event(type_: str, payload: dict[str, Any]) -> str:
    """Resolve a run_events row's ``type``/payload to its activity.

    Args:
        type_: The event's ``type`` column value.
        payload: The event's payload, consulted only for the durable path's
            ``scientific_task`` completions, whose actual node name lives
            in ``payload["task"]`` rather than in ``type_`` itself.

    Returns:
        One of ``ACTIVITY_VALUES``; ``ACTIVITY_OTHER`` for any event type
        or node this module does not recognize -- never raises.
    """
    if type_ == "scientific_task":
        task = payload.get("task")
        return _activity_for_node(str(task)) if task else ACTIVITY_OTHER
    if type_.startswith("safety"):
        return ACTIVITY_SAFETY
    node_name = _TYPE_TO_NODE_ALIASES.get(type_, type_)
    return _activity_for_node(node_name)


_stage_logger = logging.getLogger("app.run_stage")

# Caps for the mirrored line: bulk collections become their size, long
# strings are clipped, and the whole message is bounded.
_STAGE_MAX_CHARS = 200
_STAGE_VALUE_MAX_CHARS = 60


def _summarize_string_value(key: str, value: str) -> str | None:
    """Render a string payload entry compactly, or None to omit it."""
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > _STAGE_VALUE_MAX_CHARS:
        text = text[:_STAGE_VALUE_MAX_CHARS] + "..."
    return f"{key}={text}"


def _summarize_value(key: str, value: Any) -> str | None:
    """Render one payload entry compactly, or None to omit it."""
    if isinstance(value, (bool, int, float)):
        return f"{key}={value}"
    if isinstance(value, str):
        return _summarize_string_value(key, value)
    if isinstance(value, (list, dict)):
        # Size, never contents: payloads carry whole hypothesis and
        # match collections.
        return f"{key}={len(value)}"
    return None


def summarize_stage_payload(payload: dict[str, Any]) -> str:
    """Summarize an event payload as a short ``key=value`` string.

    Whole pairs are dropped once the budget is spent rather than cutting
    mid-pair, which would read as a key whose value went missing.
    """
    parts: list[str] = []
    used = 0
    for key, value in payload.items():
        rendered = _summarize_value(key, value)
        if rendered is None:
            continue
        cost = len(rendered) + (1 if parts else 0)
        if used + cost > _STAGE_MAX_CHARS:
            parts.append("...")
            break
        parts.append(rendered)
        used += cost
    return " ".join(parts)


def _log_stage(run_id: str, type_: str, payload: dict[str, Any]) -> None:
    """Mirror one event into the app log as an ``app.run_stage`` record.

    Imported lazily because ``app.logging_setup`` imports ``app.store``;
    binding the run id through ``run_log_context`` keeps the record
    run-scoped even when the caller is outside a run context.
    """
    from app.logging_setup import run_log_context

    summary = summarize_stage_payload(payload)
    message = f"{type_} {summary}".strip()
    # Both bindings are needed: `extra` makes the record self-describing
    # for any handler, while the context satisfies the RunIdFilter that
    # handlers attach (it would otherwise overwrite run_id with None).
    with run_log_context(run_id):
        _stage_logger.info("%s", message, extra={"run_id": run_id})


def _append_event(  # noqa: PLR0913 -- connection, timestamp, and mirror mode are store state.
    conn: sqlite3.Connection,
    run_id: str,
    type_: str,
    payload: dict[str, Any],
    created_at: float,
    mirror_log: bool = True,
) -> int:
    """Insert an event row on an open connection and return its seq.

    Assigns the next per-run sequence number and inserts in a single statement,
    so the run's hottest write path makes one round-trip instead of a separate
    SELECT then INSERT. The sequence floor also covers the checkpoints table's
    ``last_event_seq`` high-water mark: a resume clears ``run_events``, so
    without it a resumed run would restart at seq 1 and break clients
    reconnecting with ``?after=`` (both indexed lookups; the scalar ``MAX(a,
    b)`` picks the higher floor).
    """
    # The activity discriminator is merged into the payload rather than a
    # new column, so replay/SSE/the schema are untouched.
    payload = {**payload, "activity": activity_for_event(type_, payload)}
    row = conn.execute(
        "INSERT INTO run_events (run_id, seq, type, payload_json, created_at) "
        "VALUES (?, 1 + MAX("
        "(SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE run_id=?), "
        "(SELECT COALESCE(MAX(last_event_seq), 0) FROM checkpoints "
        "WHERE run_id=?)), ?, ?, ?) RETURNING seq",
        (run_id, run_id, run_id, type_, json.dumps(payload), created_at),
    ).fetchone()
    if mirror_log:
        log_event_stage(run_id, type_, payload)
    return int(row["seq"])


def log_event_stage(run_id: str, type_: str, payload: dict[str, Any]) -> None:
    """Best-effort mirror of a persisted event to the application log."""
    effective_payload = {
        **payload,
        "activity": activity_for_event(type_, payload),
    }
    with contextlib.suppress(Exception):
        _log_stage(run_id, type_, effective_payload)


def append_event(
    run_id: str,
    type_: str,
    payload: dict[str, Any],
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Append an event to a run's append-only event log.

    Args:
        run_id: Identifier of the run the event belongs to.
        type_: Event type, e.g. an agent name, 'status', or 'log'.
        payload: Event payload serialized to JSON.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to join an existing transaction.

    Returns:
        The monotonically increasing sequence number assigned to the event.
    """
    with _use_conn(conn, db_path) as active:
        return _append_event(active, run_id, type_, payload, _now())


def append_event_deferred_log(
    run_id: str,
    type_: str,
    payload: dict[str, Any],
    conn: sqlite3.Connection,
) -> int:
    """Append inside a transaction and leave log mirroring to its owner."""
    return _append_event(conn, run_id, type_, payload, _now(), mirror_log=False)


def latest_event_seq(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Return the highest event sequence for a run, or 0 if it has none.

    Used as the ``last_event_seq`` high-water mark when checkpointing a run,
    so a resumed run assigns new event seqs strictly above it.
    """
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE run_id=?",
            (run_id,),
        ).fetchone()
    return int(row[0])


def latest_status_event(
    run_id: str,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    """Return the newest persisted status payload for a run, if any."""
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT payload_json FROM run_events "
            "WHERE run_id=? AND type='status' ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    return json.loads(row["payload_json"]) if row is not None else None


def list_events(
    run_id: str,
    after_seq: int = 0,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return a run's events ordered by sequence number.

    Args:
        run_id: Identifier of the run whose events to list.
        after_seq: Only return events with a sequence number greater than this.
        db_path: Optional override for the SQLite database path.

    Returns:
        A list of event dicts with seq, type, payload, and created_at keys.
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT seq, type, payload_json, created_at FROM run_events "
            "WHERE run_id=? AND seq > ? ORDER BY seq ASC",
            (run_id, after_seq),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "seq": r["seq"],
                    "type": r["type"],
                    "payload": json.loads(r["payload_json"]),
                    "created_at": r["created_at"],
                }
            )
        return out


def recent_events(
    run_id: str,
    limit: int,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return a run's most recent events, oldest-first within the window.

    Bounded counterpart to :func:`list_events`, which returns every event a
    run ever emitted. A long run emits thousands, and the Q&A prompt only
    ever renders the tail, so reading (and JSON-decoding) the whole log per
    question is work with nowhere to go.

    Args:
        run_id: Identifier of the run whose events to read.
        limit: Maximum number of events to return, counted from the newest.
        conn: Optional open connection to reuse.
        db_path: Optional override for the SQLite database path.

    Returns:
        Up to ``limit`` event dicts (seq, type, payload, created_at),
        ordered oldest-first so callers read them as a narrative.
    """
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT seq, type, payload_json, created_at FROM run_events "
            "WHERE run_id=? ORDER BY seq DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()
    return [
        {
            "seq": r["seq"],
            "type": r["type"],
            "payload": json.loads(r["payload_json"]),
            "created_at": r["created_at"],
        }
        for r in reversed(rows)
    ]


def run_execution_started_at(
    run_id: str,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> float | None:
    """Return when a run began executing, or None if it never started.

    The run row's ``created_at`` is when the *draft* was created, which can
    precede the start by any amount -- a plan reviewed over lunch and then
    started reports hours of "elapsed" that nothing was working for. The
    first ``lifecycle`` event is appended by the start endpoint (``queued``),
    so its timestamp is the honest clock start.

    Args:
        run_id: Identifier of the run.
        conn: Optional open connection to reuse.
        db_path: Optional override for the SQLite database path.

    Returns:
        The epoch seconds the run was queued for execution, or None.
    """
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT MIN(created_at) AS started FROM run_events "
            "WHERE run_id=? AND type='lifecycle'",
            (run_id,),
        ).fetchone()
    started = row["started"] if row is not None else None
    return float(started) if started is not None else None

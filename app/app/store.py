"""SQLite-backed persistence for runs, hypotheses, evidence, and reports.

Design choices:

- Pure stdlib `sqlite3` so the app picks up no new runtime deps.
- WAL mode + per-thread connections via a context manager.
- The event log is append-only and is the canonical timeline reopened on
  refresh / restart.
- Hypotheses are append-only: `evolve` writes new rows with `parent_id` set;
  no row is ever mutated in place. Updates that *are* allowed (Elo, status,
  scores) live in `hypothesis_state`, keyed by hypothesis id, leaving the
  original row untouched.
- Reports are stored both as a structured JSON blob and a rendered Markdown
  artifact on disk (path tracked in the row).
"""

from __future__ import annotations

import contextlib
import enum
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.citations import CitationState

logger = logging.getLogger(__name__)


class RunStatus(str, enum.Enum):
    """Lifecycle states of a run, persisted in the runs.status column."""

    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BLOCKED = "blocked"


# Statuses that mark a run as finished; reaching one sets `completed_at`.
TERMINAL_STATUSES: tuple[RunStatus, ...] = (
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.BLOCKED,
    RunStatus.CANCELLED,
)

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_initialized: set[str] = set()


def _now() -> float:
    return time.time()


def _resolved_db_path(path: str | None = None) -> str:
    # Read env on every call so test fixtures and runtime overrides are picked up.  # pylint: disable=line-too-long
    return path or os.getenv("COSCIENTIST_DB_PATH") or "./coscientist.db"


def _reports_dir() -> Path:
    p = Path(os.getenv("COSCIENTIST_REPORTS_DIR") or "./reports")
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextlib.contextmanager
def connect(
        path: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Yield a sqlite3 connection with WAL + row factory enabled."""
    db_path = _resolved_db_path(path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path,
                           timeout=30,
                           isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        if db_path not in _initialized:
            with _lock:
                if db_path not in _initialized:
                    _init_schema(conn)
                    _initialized.add(db_path)
        yield conn
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _run_migrations(conn)


def _run_migrations(conn: sqlite3.Connection) -> None:
    cols = {
        row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()
    }
    if "client_id" not in cols:
        conn.execute(
            "ALTER TABLE runs ADD COLUMN client_id TEXT NOT NULL DEFAULT ''")
        logger.info("migration: added client_id column to runs")
    # Remove runs that predate client isolation (no client_id assigned).
    conn.execute("DELETE FROM runs WHERE client_id = ''")

    report_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(reports)").fetchall()
    }
    if "markdown_text" not in report_cols:
        conn.execute("ALTER TABLE reports ADD COLUMN markdown_text TEXT")
        logger.info("migration: added markdown_text column to reports")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    research_goal TEXT NOT NULL,
    profile TEXT NOT NULL,           -- 'advanced'; legacy 'standard' is coerced before execution
    status TEXT NOT NULL,            -- draft|queued|running|synthesizing|completed|failed|blocked|cancelled
    provider TEXT NOT NULL,          -- 'mock' | 'engine'
    config_json TEXT NOT NULL,       -- JSON: initial_count, iterations, evolution_count, k_factor, ...
    client_id TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,              -- agent name, 'status', 'log', 'metric', ...
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON run_events(run_id, seq);

CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_id TEXT,                  -- NULL for generation-0; set by evolve
    generation INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    mechanism TEXT,
    expected_effect TEXT,
    experimental_context TEXT,
    created_by_agent TEXT NOT NULL,  -- 'generation' | 'evolution'
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES hypotheses(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_hyp_run ON hypotheses(run_id);
CREATE INDEX IF NOT EXISTS idx_hyp_parent ON hypotheses(parent_id);

-- Mutable state for a hypothesis (Elo, scores, status). Kept separate from the
-- append-only `hypotheses` table so the original record is never overwritten.
CREATE TABLE IF NOT EXISTS hypothesis_state (
    hypothesis_id TEXT PRIMARY KEY,
    elo_rating INTEGER NOT NULL DEFAULT 1200,
    win_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0,
    novelty_score REAL,
    plausibility_score REAL,
    testability_score REAL,
    safety_status TEXT DEFAULT 'pending',
    status TEXT NOT NULL DEFAULT 'active',
    cluster_id TEXT,
    updated_at REAL NOT NULL,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT,                     -- 'pubmed' | 'arxiv' | 'mock' | ...
    url TEXT,
    authors_json TEXT,
    year INTEGER,
    abstract TEXT,
    available INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ev_run ON evidence(run_id);

CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    state TEXT NOT NULL,             -- verified | partial | unsupported | unavailable
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cit_hyp ON citations(hypothesis_id);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    reviewer_agent TEXT NOT NULL,    -- 'reflection' | 'review' | 'meta_review'
    summary TEXT NOT NULL,
    critique TEXT NOT NULL,
    novelty REAL,
    plausibility REAL,
    testability REAL,
    overall REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rv_hyp ON reviews(hypothesis_id);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    winner_id TEXT NOT NULL,
    loser_id TEXT NOT NULL,
    winner_elo_before INTEGER NOT NULL,
    winner_elo_after INTEGER NOT NULL,
    loser_elo_before INTEGER NOT NULL,
    loser_elo_after INTEGER NOT NULL,
    rationale TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_match_run ON matches(run_id);

CREATE TABLE IF NOT EXISTS safety_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,             -- 'intake' | 'final'
    decision TEXT NOT NULL,          -- 'allow' | 'redact' | 'block'
    reason TEXT,
    matches_json TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,      -- structured report (Overview, Ideas, Tournament, Citations, Safety)
    markdown_path TEXT,
    markdown_text TEXT,              -- full markdown stored in DB for durability across restarts
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reports_run ON reports(run_id);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    sender     TEXT NOT NULL,
    content    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    created_at REAL NOT NULL,
    applied    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id, id);
"""

# ---------------------------------------------------------------------------
# Run CRUD
# ---------------------------------------------------------------------------


@dataclass
class RunRow:
    """Represents a single run row from the runs table."""

    id: str
    research_goal: str
    profile: str
    status: str
    provider: str
    config: dict[str, Any]
    client_id: str
    created_at: float
    updated_at: float
    completed_at: float | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "research_goal": self.research_goal,
            "profile": self.profile,
            "status": self.status,
            "provider": self.provider,
            "config": self.config,
            "is_demo": self.client_id == "__demo__",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


@dataclass
class MessageRow:
    """Represents a single message row from the messages table."""

    id: int
    run_id: str
    sender: str
    content: str
    kind: str
    created_at: float
    applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "sender": self.sender,
            "content": self.content,
            "kind": self.kind,
            "created_at": self.created_at,
            "applied": self.applied,
        }


def _row_to_run(row: sqlite3.Row) -> RunRow:
    return RunRow(
        id=row["id"],
        research_goal=row["research_goal"],
        profile=row["profile"],
        status=row["status"],
        provider=row["provider"],
        config=json.loads(row["config_json"]),
        client_id=row["client_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        error=row["error"],
    )


def create_run(
    research_goal: str,
    profile: str,
    provider: str,
    config: dict[str, Any],
    client_id: str = "",
    db_path: str | None = None,
) -> RunRow:
    """Insert a new run row in the DRAFT state and return it.

    Args:
        research_goal: The natural-language research goal for the run.
        profile: The run profile, e.g. 'standard' or 'advanced'.
        provider: The execution provider, e.g. 'mock' or 'engine'.
        config: Run configuration values serialized to JSON.
        client_id: Owning client identifier used for run isolation.
        db_path: Optional override for the SQLite database path.

    Returns:
        The newly created run as a RunRow.
    """
    run_id = str(uuid.uuid4())
    now = _now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (id, research_goal, profile, status, provider, config_json, client_id, created_at, updated_at) "  # pylint: disable=line-too-long
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, research_goal, profile, RunStatus.DRAFT.value, provider,
             json.dumps(config), client_id, now, now),
        )
    logger.info("created run %s profile=%s provider=%s client_id=%s", run_id,
                profile, provider, client_id)
    return RunRow(
        id=run_id,
        research_goal=research_goal,
        profile=profile,
        status=RunStatus.DRAFT.value,
        provider=provider,
        config=config,
        client_id=client_id,
        created_at=now,
        updated_at=now,
        completed_at=None,
        error=None,
    )


def get_run(run_id: str, db_path: str | None = None) -> RunRow | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?",
                           (run_id,)).fetchone()
        return _row_to_run(row) if row else None


def list_runs(client_id: str = "",
              limit: int = 100,
              db_path: str | None = None) -> list[RunRow]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE client_id = ? ORDER BY created_at DESC LIMIT ?",  # pylint: disable=line-too-long
            (client_id, limit),
        ).fetchall()
        return [_row_to_run(r) for r in rows]


def update_run_status(
    run_id: str,
    status: RunStatus,
    error: str | None = None,
    db_path: str | None = None,
) -> None:
    """Update a run's status, timestamps, and optional error message.

    Args:
        run_id: Identifier of the run to update.
        status: The new lifecycle status to persist.
        error: Optional error message to store when the run failed.
        db_path: Optional override for the SQLite database path.
    """
    now = _now()
    completed_at = now if status in TERMINAL_STATUSES else None
    with connect(db_path) as conn:
        if completed_at is not None:
            conn.execute(
                "UPDATE runs SET status=?, error=?, updated_at=?, completed_at=? WHERE id=?",  # pylint: disable=line-too-long
                (status.value, error, now, completed_at, run_id),
            )
        else:
            conn.execute(
                "UPDATE runs SET status=?, error=?, updated_at=? WHERE id=?",
                (status.value, error, now, run_id),
            )


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


def append_event(
    run_id: str,
    type_: str,
    payload: dict[str, Any],
    db_path: str | None = None,
) -> int:
    """Append an event to a run's append-only event log.

    Args:
        run_id: Identifier of the run the event belongs to.
        type_: Event type, e.g. an agent name, 'status', or 'log'.
        payload: Event payload serialized to JSON.
        db_path: Optional override for the SQLite database path.

    Returns:
        The monotonically increasing sequence number assigned to the event.
    """
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS s FROM run_events WHERE run_id=?",
            (run_id,)).fetchone()
        seq = (row["s"] if row else 0) + 1
        conn.execute(
            "INSERT INTO run_events (run_id, seq, type, payload_json, created_at) VALUES (?,?,?,?,?)",  # pylint: disable=line-too-long
            (run_id, seq, type_, json.dumps(payload), _now()),
        )
    return seq


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
            out.append({
                "seq": r["seq"],
                "type": r["type"],
                "payload": json.loads(r["payload_json"]),
                "created_at": r["created_at"],
            })
        return out


# ---------------------------------------------------------------------------
# Hypotheses (append-only)
# ---------------------------------------------------------------------------


def add_hypothesis(
    run_id: str,
    title: str,
    statement: str,
    *,
    parent_id: str | None = None,
    generation: int = 0,
    mechanism: str = "",
    expected_effect: str = "",
    experimental_context: str = "",
    created_by_agent: str = "generation",
    db_path: str | None = None,
) -> str:
    """Insert a hypothesis row and its initial mutable state row.

    Args:
        run_id: Identifier of the run the hypothesis belongs to.
        title: Short title of the hypothesis.
        statement: Full hypothesis statement.
        parent_id: Identifier of the parent hypothesis, set when evolving.
        generation: Generation number, 0 for originally generated hypotheses.
        mechanism: Proposed mechanism underlying the hypothesis.
        expected_effect: Expected effect or outcome of the hypothesis.
        experimental_context: Context describing how to test the hypothesis.
        created_by_agent: Agent that created the row, e.g. 'generation'.
        db_path: Optional override for the SQLite database path.

    Returns:
        The identifier of the newly inserted hypothesis.
    """
    hyp_id = str(uuid.uuid4())
    now = _now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO hypotheses (id, run_id, parent_id, generation, title, statement, mechanism, "  # pylint: disable=line-too-long
            "expected_effect, experimental_context, created_by_agent, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                hyp_id,
                run_id,
                parent_id,
                generation,
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
            "INSERT INTO hypothesis_state (hypothesis_id, elo_rating, updated_at) VALUES (?,?,?)",  # pylint: disable=line-too-long
            (hyp_id, int(os.getenv("ELO_INITIAL", "1200")), now),
        )
    return hyp_id


def update_hypothesis_state(
    hypothesis_id: str,
    *,
    elo_rating: int | None = None,
    win_delta: int = 0,
    loss_delta: int = 0,
    novelty: float | None = None,
    plausibility: float | None = None,
    testability: float | None = None,
    safety_status: str | None = None,
    status: str | None = None,
    cluster_id: str | None = None,
    db_path: str | None = None,
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
        plausibility: New plausibility score to set.
        testability: New testability score to set.
        safety_status: New safety status to set.
        status: New lifecycle status for the hypothesis.
        cluster_id: New proximity cluster identifier to set.
        db_path: Optional override for the SQLite database path.
    """
    sets: list[str] = []
    params: list[Any] = []
    if elo_rating is not None:
        sets.append("elo_rating=?")
        params.append(elo_rating)
    if win_delta:
        sets.append("win_count=win_count+?")
        params.append(win_delta)
    if loss_delta:
        sets.append("loss_count=loss_count+?")
        params.append(loss_delta)
    if novelty is not None:
        sets.append("novelty_score=?")
        params.append(novelty)
    if plausibility is not None:
        sets.append("plausibility_score=?")
        params.append(plausibility)
    if testability is not None:
        sets.append("testability_score=?")
        params.append(testability)
    if safety_status is not None:
        sets.append("safety_status=?")
        params.append(safety_status)
    if status is not None:
        sets.append("status=?")
        params.append(status)
    if cluster_id is not None:
        sets.append("cluster_id=?")
        params.append(cluster_id)
    sets.append("updated_at=?")
    params.append(_now())
    params.append(hypothesis_id)
    set_clause = ", ".join(sets)
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE hypothesis_state SET {set_clause} WHERE hypothesis_id=?",  # pylint: disable=line-too-long
            params,
        )


def list_hypotheses(run_id: str,
                    db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT h.*, s.elo_rating, s.win_count, s.loss_count, s.novelty_score, s.plausibility_score, "  # pylint: disable=line-too-long
            "s.testability_score, s.safety_status, s.status, s.cluster_id "
            "FROM hypotheses h LEFT JOIN hypothesis_state s ON h.id=s.hypothesis_id "  # pylint: disable=line-too-long
            "WHERE h.run_id=? ORDER BY s.elo_rating DESC, h.created_at ASC",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_hypothesis(hypothesis_id: str,
                   db_path: str | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT h.*, s.elo_rating, s.win_count, s.loss_count, s.novelty_score, s.plausibility_score, "  # pylint: disable=line-too-long
            "s.testability_score, s.safety_status, s.status, s.cluster_id "
            "FROM hypotheses h LEFT JOIN hypothesis_state s ON h.id=s.hypothesis_id "  # pylint: disable=line-too-long
            "WHERE h.id=?",
            (hypothesis_id,),
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Evidence / citations
# ---------------------------------------------------------------------------


def add_evidence(
    run_id: str,
    title: str,
    *,
    source: str = "mock",
    url: str = "",
    authors: Iterable[str] | None = None,
    year: int | None = None,
    abstract: str = "",
    available: bool = True,
    db_path: str | None = None,
) -> str:
    """Insert an evidence row for a run and return its identifier.

    Args:
        run_id: Identifier of the run the evidence belongs to.
        title: Title of the evidence item.
        source: Evidence source, e.g. 'pubmed', 'arxiv', or 'mock'.
        url: Optional URL pointing to the evidence.
        authors: Optional iterable of author names.
        year: Optional publication year.
        abstract: Optional abstract text for the evidence.
        available: Whether the evidence full text is available.
        db_path: Optional override for the SQLite database path.

    Returns:
        The identifier of the newly inserted evidence row.
    """
    ev_id = str(uuid.uuid4())
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO evidence (id, run_id, title, source, url, authors_json, year, abstract, available, created_at) "  # pylint: disable=line-too-long
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                ev_id,
                run_id,
                title,
                source,
                url,
                json.dumps(list(authors or [])),
                year,
                abstract,
                1 if available else 0,
                _now(),
            ),
        )
    return ev_id


def list_evidence(run_id: str,
                  db_path: str | None = None) -> list[dict[str, Any]]:
    """Return a run's evidence rows ordered by creation time.

    Args:
        run_id: Identifier of the run whose evidence to list.
        db_path: Optional override for the SQLite database path.

    Returns:
        A list of evidence dicts with decoded authors and available fields.
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM evidence WHERE run_id=? ORDER BY created_at ASC",
            (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["authors"] = json.loads(d.pop("authors_json") or "[]")
            d["available"] = bool(d["available"])
            out.append(d)
        return out


def add_citation(
    run_id: str,
    hypothesis_id: str,
    evidence_id: str,
    claim: str,
    state: CitationState,
    db_path: str | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO citations (run_id, hypothesis_id, evidence_id, claim, state, created_at) "  # pylint: disable=line-too-long
            "VALUES (?,?,?,?,?,?)",
            (run_id, hypothesis_id, evidence_id, claim, state.value, _now()),
        )


def list_citations(run_id: str,
                   db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM citations WHERE run_id=? ORDER BY created_at ASC",
            (run_id,)).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


def add_review(
    run_id: str,
    hypothesis_id: str,
    reviewer_agent: str,
    summary: str,
    critique: str,
    *,
    novelty: float | None = None,
    plausibility: float | None = None,
    testability: float | None = None,
    overall: float | None = None,
    db_path: str | None = None,
) -> None:
    """Insert a reviewer's assessment of a hypothesis.

    Args:
        run_id: Identifier of the run the review belongs to.
        hypothesis_id: Identifier of the reviewed hypothesis.
        reviewer_agent: Agent that produced the review, e.g. 'reflection'.
        summary: Short summary of the review.
        critique: Full critique text.
        novelty: Optional novelty score assigned by the reviewer.
        plausibility: Optional plausibility score assigned by the reviewer.
        testability: Optional testability score assigned by the reviewer.
        overall: Optional overall score assigned by the reviewer.
        db_path: Optional override for the SQLite database path.
    """
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO reviews (run_id, hypothesis_id, reviewer_agent, summary, critique, "  # pylint: disable=line-too-long
            "novelty, plausibility, testability, overall, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",  # pylint: disable=line-too-long
            (
                run_id,
                hypothesis_id,
                reviewer_agent,
                summary,
                critique,
                novelty,
                plausibility,
                testability,
                overall,
                _now(),
            ),
        )


def list_reviews(run_id: str,
                 db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM reviews WHERE run_id=? ORDER BY created_at ASC",
            (run_id,)).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


def add_match(
    run_id: str,
    iteration: int,
    winner_id: str,
    loser_id: str,
    winner_before: int,
    winner_after: int,
    loser_before: int,
    loser_after: int,
    rationale: str,
    db_path: str | None = None,
) -> None:
    """Record the outcome of a pairwise tournament match.

    Args:
        run_id: Identifier of the run the match belongs to.
        iteration: Tournament iteration in which the match occurred.
        winner_id: Identifier of the winning hypothesis.
        loser_id: Identifier of the losing hypothesis.
        winner_before: Winner's Elo rating before the match.
        winner_after: Winner's Elo rating after the match.
        loser_before: Loser's Elo rating before the match.
        loser_after: Loser's Elo rating after the match.
        rationale: Explanation of why the winner prevailed.
        db_path: Optional override for the SQLite database path.
    """
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO matches (run_id, iteration, winner_id, loser_id, winner_elo_before, "  # pylint: disable=line-too-long
            "winner_elo_after, loser_elo_before, loser_elo_after, rationale, created_at) "  # pylint: disable=line-too-long
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                iteration,
                winner_id,
                loser_id,
                winner_before,
                winner_after,
                loser_before,
                loser_after,
                rationale,
                _now(),
            ),
        )


def list_matches(run_id: str,
                 db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM matches WHERE run_id=? ORDER BY created_at ASC",
            (run_id,)).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def add_safety_decision(
    run_id: str,
    stage: str,
    decision: str,
    reason: str,
    matches: list[str],
    db_path: str | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO safety_decisions (run_id, stage, decision, reason, matches_json, created_at) "  # pylint: disable=line-too-long
            "VALUES (?,?,?,?,?,?)",
            (run_id, stage, decision, reason, json.dumps(matches), _now()),
        )


def list_safety_decisions(run_id: str,
                          db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM safety_decisions WHERE run_id=? ORDER BY created_at ASC",  # pylint: disable=line-too-long
            (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["matches"] = json.loads(d.pop("matches_json") or "[]")
            out.append(d)
        return out


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def save_report(
    run_id: str,
    payload: dict[str, Any],
    markdown: str,
    db_path: str | None = None,
) -> dict[str, str]:
    """Persist a report as a JSON row plus a rendered Markdown file.

    The markdown is stored in both the database (markdown_text column, for
    durability across container restarts) and on disk (markdown_path, kept
    for backwards-compatibility and local dev convenience).

    Args:
        run_id: Identifier of the run the report belongs to.
        payload: Structured report payload serialized to JSON.
        markdown: Rendered Markdown report written to disk.
        db_path: Optional override for the SQLite database path.

    Returns:
        A dict with the new report 'id' and the 'markdown_path' on disk.
    """
    report_id = str(uuid.uuid4())
    md_path = _reports_dir() / f"{run_id}.md"
    try:
        md_path.write_text(markdown, encoding="utf-8")
    except OSError:
        logger.warning("Could not write report markdown to disk at %s", md_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO reports "
            "(id, run_id, payload_json, markdown_path, markdown_text, created_at) "  # pylint: disable=line-too-long
            "VALUES (?,?,?,?,?,?)",
            (report_id, run_id, json.dumps(payload), str(md_path), markdown,
             _now()),
        )
    return {"id": report_id, "markdown_path": str(md_path)}


def get_latest_report(run_id: str,
                      db_path: str | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE run_id=? ORDER BY created_at DESC LIMIT 1",  # pylint: disable=line-too-long
            (run_id,)).fetchone()
        if not row:
            return None
        keys = row.keys()
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "payload": json.loads(row["payload_json"]),
            "markdown_path": row["markdown_path"],
            "markdown_text": row["markdown_text"] if "markdown_text" in keys else None,  # pylint: disable=line-too-long
            "created_at": row["created_at"],
        }


def read_report_markdown(run_id: str, db_path: str | None = None) -> str | None:
    """Return the markdown text for the latest report of a run.

    Prefers the markdown_text column stored in the database (durable across
    container restarts). Falls back to reading the on-disk file for rows that
    predate the markdown_text column.

    Args:
        run_id: Identifier of the run.
        db_path: Optional override for the SQLite database path.

    Returns:
        The markdown string, or None if no report exists.
    """
    latest = get_latest_report(run_id, db_path=db_path)
    if not latest:
        return None
    # Prefer the DB-stored text (resilient to filesystem loss).
    if latest.get("markdown_text"):
        return latest["markdown_text"]
    # Fallback: read from disk for rows written before the markdown_text column.
    md_path = latest.get("markdown_path")
    if not md_path:
        return None
    path = Path(md_path)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def append_message(
    run_id: str,
    sender: str,
    content: str,
    kind: str,
    db_path: str | None = None,
) -> MessageRow:
    """Append a message to a run and return the stored row.

    Args:
        run_id: Identifier of the run the message belongs to.
        sender: Identifier of the message sender.
        content: Message body text.
        kind: Message kind, e.g. 'steering'.
        db_path: Optional override for the SQLite database path.

    Returns:
        The newly inserted message as a MessageRow.
    """
    now = _now()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO messages (run_id, sender, content, kind, created_at, applied) VALUES (?,?,?,?,?,0)",  # pylint: disable=line-too-long
            (run_id, sender, content, kind, now),
        )
        msg_id = cur.lastrowid or 0
    return MessageRow(id=msg_id,
                      run_id=run_id,
                      sender=sender,
                      content=content,
                      kind=kind,
                      created_at=now,
                      applied=False)


def list_messages(run_id: str, db_path: str | None = None) -> list[MessageRow]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_id, sender, content, kind, created_at, applied FROM messages "  # pylint: disable=line-too-long
            "WHERE run_id=? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        return [
            MessageRow(
                id=r["id"],
                run_id=r["run_id"],
                sender=r["sender"],
                content=r["content"],
                kind=r["kind"],
                created_at=r["created_at"],
                applied=bool(r["applied"]),
            ) for r in rows
        ]


def get_pending_steering(run_id: str,
                         db_path: str | None = None) -> list[MessageRow]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_id, sender, content, kind, created_at, applied FROM messages "  # pylint: disable=line-too-long
            "WHERE run_id=? AND kind='steering' AND applied=0 ORDER BY id ASC",  # pylint: disable=line-too-long
            (run_id,),
        ).fetchall()
        return [
            MessageRow(
                id=r["id"],
                run_id=r["run_id"],
                sender=r["sender"],
                content=r["content"],
                kind=r["kind"],
                created_at=r["created_at"],
                applied=bool(r["applied"]),
            ) for r in rows
        ]


def mark_steering_applied(ids: list[int], db_path: str | None = None) -> None:
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE messages SET applied=1 WHERE id IN ({placeholders})", ids)

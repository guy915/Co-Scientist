"""Row dataclasses, run-status enum, and sqlite3.Row decoding helpers.

Pure data definitions shared across the ``app.store`` submodules: the
run lifecycle enum, the RunRow/MessageRow dataclasses returned by the
query helpers, and the row decoders that build them. This module keeps
no connection state and imports no other store submodule.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import sqlite3
from dataclasses import dataclass
from typing import Any


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
    # Cooperatively paused mid-run (Milestone 4); resumable from its last
    # checkpoint. Not terminal — a paused run can be resumed or cancelled.
    PAUSED = "paused"


# Statuses that mark a run as finished; reaching one sets `completed_at`.
TERMINAL_STATUSES: tuple[RunStatus, ...] = (
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.BLOCKED,
    RunStatus.CANCELLED,
)

# Client identifier for the seeded demo runs newcomers can browse. Owns the
# single source of truth for the sentinel; seed.py and runs.py import it.
DEMO_CLIENT_ID = "__demo__"


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
    # Highest Elo across the run's hypotheses. Populated by ``list_runs`` (via a
    # single aggregate query) so list surfaces avoid fetching every hypothesis;
    # None on single-run reads and runs with no hypotheses yet.
    top_elo: int | None = None
    # Titles of the run's top hypotheses by Elo (capped), populated by
    # ``list_runs`` so home surfaces show real winning ideas without fetching
    # every hypothesis. None on single-run reads; ``[]`` for a listed run with
    # no hypotheses yet.
    top_hypotheses: list[str] | None = None
    # Type of the run's most recent pipeline-stage event (e.g. ``generate``,
    # ``ranking``), populated by ``list_runs`` to drive the live progress
    # indicator. None on single-run reads and runs with no stage events yet.
    latest_stage: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the row to the JSON shape the API returns to clients."""
        return {
            "id": self.id,
            "research_goal": self.research_goal,
            # run_mode and profile are duplicate keys: run_mode is the newer
            # name, profile is retained for clients still reading the old key.
            "run_mode": self.profile,
            "profile": self.profile,
            "status": self.status,
            "provider": self.provider,
            "config": self.config,
            "is_demo": self.client_id == DEMO_CLIENT_ID,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "top_elo": self.top_elo,
            "top_hypotheses": self.top_hypotheses,
            "latest_stage": self.latest_stage,
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
    meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the row to the JSON shape the API returns to clients."""
        return dataclasses.asdict(self)


def _row_to_run(row: sqlite3.Row) -> RunRow:
    """Build a RunRow from a runs table row, tolerating a missing top_elo."""
    keys = row.keys()
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
        top_elo=row["top_elo"] if "top_elo" in keys else None,
    )


def _parse_message_meta(row: sqlite3.Row) -> dict[str, Any] | None:
    """Decode the optional meta_json column into a dict."""
    raw = row["meta_json"]
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _row_to_message(row: sqlite3.Row) -> MessageRow:
    """Build a MessageRow from a messages table row."""
    return MessageRow(
        id=row["id"],
        run_id=row["run_id"],
        sender=row["sender"],
        content=row["content"],
        kind=row["kind"],
        created_at=row["created_at"],
        applied=bool(row["applied"]),
        meta=_parse_message_meta(row),
    )

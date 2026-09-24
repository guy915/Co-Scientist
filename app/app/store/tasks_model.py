"""The durable task's row <-> dataclass mapping.

Split out of ``app.store.tasks`` to keep that module within the size cap,
and to give ``app.store.tasks_attempts`` a way to decode a task row
without importing back from ``app.store.tasks`` (which imports from
``tasks_attempts`` and would otherwise cycle). Every name is re-exported
from ``app.store.tasks``, so callers and monkeypatching tests are
unaffected.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from typing import Any

UNKNOWN_PROVIDER_OUTCOME_ERROR = (
    "The provider may have accepted the request; acceptance and any charge "
    "are unconfirmed. Automatic replay was stopped."
)


@dataclasses.dataclass(frozen=True)
class TaskFailure:
    """Raw task failure plus an optional exact provider failure kind."""

    error: str
    failure_kind: str | None = None


@dataclasses.dataclass(frozen=True)
class ScientificTask:
    """One durable unit of specialist work."""

    id: str
    run_id: str
    task_type: str
    status: str
    priority: int
    inputs: dict[str, Any]
    dependencies: tuple[str, ...]
    provenance: dict[str, Any]
    idempotency_key: str
    budget: dict[str, Any]
    attempt: int
    max_attempts: int
    lease_owner: str | None
    lease_expires_at: float | None
    result: dict[str, Any] | None
    error: str | None
    created_at: float
    updated_at: float
    started_at: float | None
    completed_at: float | None
    # Bounded history of failed attempts only -- see _record_failed_attempt.
    # A row written before attempts_json existed reads back as (), the
    # only state such a row could represent.
    attempts: tuple[dict[str, Any], ...] = ()
    # When the current lease's attempt was claimed; see schema_tasks.py.
    attempt_started_at: float | None = None
    # Not-before instant (epoch seconds) for an otherwise-queued row; see
    # schema_tasks.py. NULL for every ordinarily-enqueued row.
    available_at: float | None = None


def _decode(row: sqlite3.Row) -> ScientificTask:
    """Decode a SQLite task row into its typed representation."""
    return ScientificTask(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        task_type=str(row["task_type"]),
        status=str(row["status"]),
        priority=int(row["priority"]),
        inputs=json.loads(row["inputs_json"]),
        dependencies=tuple(json.loads(row["dependencies_json"])),
        provenance=json.loads(row["provenance_json"]),
        idempotency_key=str(row["idempotency_key"]),
        budget=json.loads(row["budget_json"]),
        attempt=int(row["attempt"]),
        max_attempts=int(row["max_attempts"]),
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        error=row["error"],
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        attempts=tuple(json.loads(row["attempts_json"])),
        attempt_started_at=row["attempt_started_at"],
        available_at=row["available_at"],
    )

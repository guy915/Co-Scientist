"""Persistence helpers for creating new runs."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn
from app.store.models import RunRow, RunStatus

logger = logging.getLogger("app.store.runs")


def _resolve_llm_backend(provider: str, llm_backend: str | None) -> str:
    """Resolve the backend to persist, defaulting it from the provider."""
    if llm_backend is not None:
        return llm_backend
    return "offline" if provider == "mock" else "real"


@dataclass(frozen=True)
class _NewRunFields:
    """Fields needed to insert a run row and build its RunRow."""

    run_id: str
    research_goal: str
    title: str | None
    profile: str
    provider: str
    config: dict[str, Any]
    client_id: str
    execution_policy: str
    now: float
    backend: str


def _insert_run_row(conn: sqlite3.Connection, fields: _NewRunFields) -> None:
    """Insert a new run row in the DRAFT state on an open connection."""
    conn.execute(
        "INSERT INTO runs (id, research_goal, title, profile, status, "
        "provider, config_json, client_id, created_at, updated_at, "
        "llm_backend, execution_policy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            fields.run_id,
            fields.research_goal,
            fields.title,
            fields.profile,
            RunStatus.DRAFT.value,
            fields.provider,
            json.dumps(fields.config),
            fields.client_id,
            fields.now,
            fields.now,
            fields.backend,
            fields.execution_policy,
        ),
    )


def _run_row_from_insert(fields: _NewRunFields) -> RunRow:
    """Build the RunRow for a just-inserted run."""
    return RunRow(
        id=fields.run_id,
        research_goal=fields.research_goal,
        title=fields.title,
        profile=fields.profile,
        status=RunStatus.DRAFT.value,
        provider=fields.provider,
        config=fields.config,
        client_id=fields.client_id,
        created_at=fields.now,
        updated_at=fields.now,
        completed_at=None,
        error=None,
        llm_backend=fields.backend,
        execution_policy=fields.execution_policy,
    )


def _log_run_created(fields: _NewRunFields) -> None:
    """Log creation of a new run at info level."""
    logger.info(
        "created run %s run_mode=%s provider=%s llm_backend=%s client_id=%s",
        fields.run_id,
        fields.profile,
        fields.provider,
        fields.backend,
        fields.client_id,
    )


@dataclass(frozen=True)
class RunCreateOptions:
    """Optional run creation inputs and database override."""

    client_id: str = ""
    title: str | None = None
    llm_backend: str | None = None
    execution_policy: str = "standard"
    db_path: str | None = None
    conn: sqlite3.Connection | None = None
    log_created: bool | None = None


def _create_run_impl(
    fields: _NewRunFields,
    db_path: str | None,
    *,
    conn: sqlite3.Connection | None = None,
    log_created: bool = True,
) -> RunRow:
    """Persist a new DRAFT row and return it as a RunRow."""
    with _use_conn(conn, db_path) as active:
        _insert_run_row(active, fields)
    if log_created:
        _log_run_created(fields)
    return _run_row_from_insert(fields)


def log_run_created(run: RunRow) -> None:
    """Mirror a committed run creation in the application log."""
    logger.info(
        "created run %s run_mode=%s provider=%s llm_backend=%s client_id=%s",
        run.id,
        run.profile,
        run.provider,
        run.llm_backend,
        run.client_id,
    )


def create_run(
    research_goal: str,
    profile: str,
    provider: str,
    config: dict[str, Any],
    options: RunCreateOptions | None = None,
) -> RunRow:
    """Insert a new DRAFT row and return it."""
    opts = options or RunCreateOptions()
    fields = _NewRunFields(
        run_id=str(uuid.uuid4()),
        research_goal=research_goal,
        title=opts.title,
        profile=profile,
        provider=provider,
        config=config,
        client_id=opts.client_id,
        execution_policy=opts.execution_policy,
        now=_now(),
        backend=_resolve_llm_backend(provider, opts.llm_backend),
    )
    should_log = (
        opts.conn is None if opts.log_created is None else opts.log_created
    )
    return _create_run_impl(
        fields, opts.db_path, conn=opts.conn, log_created=should_log
    )

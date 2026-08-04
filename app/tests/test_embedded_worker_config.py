"""Tests for the ``COSCIENTIST_EMBEDDED_WORKER`` deployment knob.

Whether this process drains the durable task queue itself is one fact, read
at three launch sites: run start, resume, and startup recovery. Each used to
call ``os.getenv`` with its own restated ``"1"`` default and compared it
inconsistently (``== "1"`` twice, ``!= "1"`` once), so any value other than
exactly ``"1"`` or ``"0"`` meant different things to different sites. It is
now a ``Settings`` field, which is what these tests pin.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import BackgroundTasks

from app import main, runs_lifecycle, store, task_worker
from app.config import Settings, settings


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("1", True), ("true", True), ("0", False), ("false", False)],
)
def test_embedded_worker_parses_from_its_env_var(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    """The knob keeps its name and its default-on behavior after the move.

    Settings sets no ``env_prefix`` and is case-insensitive, so the field
    picks ``COSCIENTIST_EMBEDDED_WORKER`` up exactly as the removed
    ``os.getenv`` calls did -- no deployment has to change a variable.
    ``_env_file=None`` keeps a developer's local .env out of the answer.
    """
    monkeypatch.delenv("COSCIENTIST_EMBEDDED_WORKER", raising=False)
    if value is not None:
        monkeypatch.setenv("COSCIENTIST_EMBEDDED_WORKER", value)

    parsed = Settings(_env_file=None)

    assert parsed.coscientist_embedded_worker is expected


@pytest.mark.parametrize(("embedded", "expected"), [(True, 1), (False, 0)])
def test_start_launches_an_embedded_worker_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, embedded: bool, expected: int
) -> None:
    """A worker-service deployment leaves the queued task for its own worker."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", embedded)
    monkeypatch.setattr(store, "append_event", lambda *a, **k: None)
    monkeypatch.setattr(
        task_worker,
        "enqueue_run_workflow",
        lambda run_id, **_: run_id,
    )
    background = BackgroundTasks()

    runs_lifecycle._enqueue_workflow_and_maybe_launch_worker(
        "run-1", background
    )

    assert len(background.tasks) == expected


async def test_recovery_launches_no_embedded_workers_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup recovery reads the same setting as the two run-launch sites.

    The recovery site is the one that phrased the check as ``!= "1"``. It
    must agree with the others, or a deployment that meant to hand every
    task to a worker service still leases them in the API process at boot.
    """
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(
        store, "list_active_engine_task_run_ids", lambda: ["run-1"]
    )
    workers: list[asyncio.Task[Any]] = []

    main._launch_embedded_recovery_workers(workers)

    assert workers == []

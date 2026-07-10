"""Shared workflow boundary: intake safety gate and provider dispatch.

`run_workflow` is the single entry point both providers pass through: it
runs the intake safety gate, then dispatches to the mock workflow stream or
the real-engine stream for the resolved provider.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.engine_adapter.engine_stream import _real_engine_stream
from app.engine_adapter.events import _format_milestone
from app.engine_adapter.opts import _drain_pre_run_steering
from app.engine_adapter.provider import select_provider
from app.mock_workflow import run_mock_workflow
from app.report_render import EmitFn, make_emitter
from app.run_modes import CANONICAL_RUN_MODE, resolved_run_config
from app.safety import apply_safety_gate, screen_intake

logger = logging.getLogger(__name__)


def _emit_mock_milestone(
    run_id: str, event: dict[str, Any], db_path: str | None
) -> None:
    """Surface a mock event's milestone, if any, as a user-facing message."""
    milestone = _format_milestone(
        event.get("type", ""), event.get("payload", {})
    )
    if milestone:
        store.append_message(
            run_id, "system", milestone, "milestone", db_path=db_path
        )


async def _stream_mock_provider(
    run_id: str,
    research_goal: str,
    cfg: dict[str, Any],
    *,
    db_path: str | None,
    cancelled: asyncio.Event | None,
    sleep_seconds: float,
) -> AsyncIterator[dict[str, Any]]:
    """Drain pre-run steering, then stream the mock workflow with milestones.

    Forwards every mock event on the SSE stream, additionally surfacing
    select event types as a user-facing chat message.
    """
    _drain_pre_run_steering(run_id, db_path)

    async for event in run_mock_workflow(
        run_id=run_id,
        research_goal=research_goal,
        config=cfg,
        db_path=db_path,
        cancelled=cancelled,
        sleep_seconds=sleep_seconds,
    ):
        _emit_mock_milestone(run_id, event, db_path)
        yield event


async def _select_provider_stream(
    provider: str,
    research_goal: str,
    run_id: str,
    run_mode: str,
    cfg: dict[str, Any],
    *,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    sleep_seconds: float,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Return the event stream for the resolved provider, choosing a fallback.

    Falls back to the mock workflow if the real engine cannot be imported
    even though `provider` resolved to "engine" (e.g. a partial install).
    """
    if provider == "mock":
        return _stream_mock_provider(
            run_id,
            research_goal,
            cfg,
            db_path=db_path,
            cancelled=cancelled,
            sleep_seconds=sleep_seconds,
        )

    return _real_engine_stream(
        research_goal,
        run_id,
        run_mode,
        cfg,
        cancelled=cancelled,
        db_path=db_path,
        sleep_seconds=sleep_seconds,
        emit=emit,
    )


async def _dispatch_provider(
    provider: str,
    research_goal: str,
    run_id: str,
    run_mode: str,
    cfg: dict[str, Any],
    *,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    sleep_seconds: float,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Dispatch to the mock or real-engine workflow after the intake gate."""
    stream = await _select_provider_stream(
        provider,
        research_goal,
        run_id,
        run_mode,
        cfg,
        cancelled=cancelled,
        db_path=db_path,
        sleep_seconds=sleep_seconds,
        emit=emit,
    )
    async for event in stream:
        yield event


async def run_workflow(
    run_id: str,
    research_goal: str,
    config: dict[str, Any],
    *,
    db_path: str | None = None,
    cancelled: asyncio.Event | None = None,
    sleep_seconds: float = 0.05,
    force_provider: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive the chosen workflow and yield events as the store records them.

    Intake safety screening runs here, at the shared boundary both providers
    pass through, so every run (engine or mock) is gated before any work.
    """
    # force_provider lets a caller (e.g. seed.py's demo seeding) pin the
    # provider explicitly, bypassing select_provider()'s env/import probes.
    provider = force_provider or select_provider()
    run_mode = CANONICAL_RUN_MODE
    cfg = resolved_run_config(config)

    logger.info(
        "starting workflow run=%s provider=%s run_mode=%s",
        run_id,
        provider,
        run_mode,
    )

    emit = make_emitter(run_id, db_path=db_path)

    # Intake safety gate, shared by every provider. A hard block short-circuits
    # the run before any hypotheses are generated.
    intake = screen_intake(research_goal)
    async for event in apply_safety_gate(run_id, intake, emit, db_path=db_path):
        yield event
    if intake.decision == "block":
        return

    async for event in _dispatch_provider(
        provider,
        research_goal,
        run_id,
        run_mode,
        cfg,
        cancelled=cancelled,
        db_path=db_path,
        sleep_seconds=sleep_seconds,
        emit=emit,
    ):
        yield event

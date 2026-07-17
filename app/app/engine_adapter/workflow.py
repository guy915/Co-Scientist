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
from app.engine_adapter.provider import offline_mode, select_provider
from app.mock_workflow import run_mock_workflow
from app.report_render import EmitFn, make_emitter
from app.run_modes import normalize_run_tier, resolved_run_config
from app.safety import (
    apply_safety_gate,
    screen_intake,
    screen_with_escalation,
)

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
    resume: bool,
) -> AsyncIterator[dict[str, Any]]:
    """Return the event stream for the explicitly resolved provider."""
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
        resume=resume,
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
    resume: bool,
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
        resume=resume,
    )
    async for event in stream:
        yield event


def _resolve_offline_backend(cfg: dict[str, Any]) -> bool:
    """Return whether this run's engine execution should be offline-backed.

    The resolved config's ``llm_backend`` key wins when a caller pinned it
    explicitly ("offline" or "real"); otherwise falls back to the
    process-level ``offline_mode()`` predicate, matching prior behavior for
    any run that does not set the override.
    """
    backend = cfg.get("llm_backend")
    if backend == "offline":
        return True
    if backend == "real":
        return False
    return offline_mode()


def _sync_engine_llm_backend(
    run_id: str, cfg: dict[str, Any], db_path: str | None
) -> None:
    """Persist the resolved offline/real backend for an engine-provider run.

    Written before the engine stream is dispatched, so every later reader
    (``run_used_offline``, used by report finalization and hypothesis
    badging) reflects the resolved config's override rather than whatever
    was derived when the run row was created.
    """
    backend = "offline" if _resolve_offline_backend(cfg) else "real"
    store.set_run_llm_backend(run_id, backend, db_path=db_path)


async def run_workflow(
    run_id: str,
    research_goal: str,
    config: dict[str, Any],
    *,
    db_path: str | None = None,
    cancelled: asyncio.Event | None = None,
    sleep_seconds: float = 0.05,
    force_provider: str | None = None,
    resume: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Drive the chosen workflow and yield events as the store records them.

    Intake safety screening runs here, at the shared boundary both providers
    pass through, so every run (engine or mock) is gated before any work. On
    ``resume``, the engine provider restores its persisted WorkflowState and
    continues from the last checkpoint instead of running from the goal; the
    mock re-derives deterministically and ignores the flag. Intake screening
    is skipped on resume — the goal was already gated on the original run.

    ``sleep_seconds`` paces every event emitted through this boundary's
    emitter -- intake plus the real-engine node stream -- so both providers
    trickle out events on the same clock. The mock builds its own emitter
    downstream (also fed the same ``sleep_seconds``), since its scripted
    stages need pacing independent of this boundary.
    """
    # force_provider lets a caller (e.g. seed.py's demo seeding) pin the
    # provider explicitly, bypassing select_provider()'s env/import probes.
    provider = force_provider or select_provider()
    cfg = resolved_run_config(config)
    run_mode = normalize_run_tier(str(cfg.get("tier") or ""))

    # Only the engine provider selects a model from the offline/real split;
    # sync the run row before dispatch so the generator built downstream
    # (which re-reads the row via run_used_offline) sees the resolved value.
    if provider == "engine":
        _sync_engine_llm_backend(run_id, cfg, db_path)

    logger.info(
        "starting workflow run=%s provider=%s run_mode=%s",
        run_id,
        provider,
        run_mode,
    )

    emit = make_emitter(run_id, db_path=db_path, sleep_seconds=sleep_seconds)

    # Intake safety gate, shared by every provider. A hard block short-circuits
    # the run before any hypotheses are generated. On resume the original goal
    # was already screened, so re-gating would only duplicate the intake event.
    if not resume:
        intake = await screen_with_escalation(
            run_id,
            "intake",
            research_goal,
            screen_intake(research_goal),
            provider=provider,
            db_path=db_path,
        )
        async for event in apply_safety_gate(
            run_id, intake, emit, db_path=db_path
        ):
            yield event
        if intake.decision in {"block", "hold"}:
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
        resume=resume,
    ):
        yield event

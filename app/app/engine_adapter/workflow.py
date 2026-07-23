"""Shared workflow boundary: intake safety gate and provider dispatch.

`run_workflow` is the single entry point both providers pass through: it
runs the intake safety gate, then dispatches to the real-engine stream for
the resolved provider (the retired mock workflow's stream is gone; every run
now executes on the engine, offline-backed or real per `offline_mode`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.engine_adapter.engine_stream import (
    _EngineRunRequest,
    _EngineStreamControls,
    _real_engine_stream,
)
from app.engine_adapter.provider import (
    select_provider,
    sync_engine_llm_backend,
)
from app.report_render import EmitFn, make_emitter
from app.run_modes import normalize_run_tier, resolved_run_config
from app.safety import (
    ScreenSubject,
    apply_safety_gate,
    screen_intake,
    screen_with_escalation,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowOptions:
    """Execution controls for one ``run_workflow`` dispatch.

    Attributes:
        db_path: Optional override for the SQLite database path.
        cancelled: Cooperative cancellation signal, if the caller has one.
        sleep_seconds: Pacing applied to every event this boundary emits.
        force_provider: Pin the provider, bypassing ``select_provider``.
        resume: Continue from the run's last checkpoint instead of the goal.
    """

    db_path: str | None = None
    cancelled: asyncio.Event | None = None
    sleep_seconds: float = 0.05
    force_provider: str | None = None
    resume: bool = False


def _resolve_workflow_run(
    run_id: str,
    config: dict[str, Any],
    force_provider: str | None,
    db_path: str | None,
) -> tuple[str, dict[str, Any], str]:
    """Resolve a run's provider, tier config, and run mode; sync the row.

    Syncs the resolved config back onto the run row before dispatch so the
    generator built downstream (which re-reads the row via
    ``run_used_offline``) sees the resolved value.

    Returns:
        A tuple of (provider, resolved config, run mode).
    """
    # force_provider lets a caller (e.g. seed.py's demo seeding) pin the
    # provider explicitly, bypassing select_provider()'s env/import probes.
    provider = force_provider or select_provider()
    cfg = resolved_run_config(config)
    run_mode = normalize_run_tier(str(cfg.get("tier") or ""))
    sync_engine_llm_backend(run_id, cfg, db_path)
    logger.info(
        "starting workflow run=%s provider=%s run_mode=%s",
        run_id,
        provider,
        run_mode,
    )
    return provider, cfg, run_mode


async def _screen_workflow_intake(
    run_id: str, research_goal: str, provider: str, db_path: str | None
) -> Any:
    """Run intake safety screening and return the screening result."""
    return await screen_with_escalation(
        run_id,
        ScreenSubject("intake", research_goal, screen_intake(research_goal)),
        provider=provider,
        db_path=db_path,
    )


async def _run_intake_gate(
    run_id: str,
    research_goal: str,
    provider: str,
    emit: EmitFn,
    db_path: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Screen intake and apply the safety gate.

    Returns:
        A tuple of (events the gate emitted, whether the run is blocked --
        a "block" or "hold" decision -- and should stop here).
    """
    intake = await _screen_workflow_intake(
        run_id, research_goal, provider, db_path
    )
    events = [
        event
        async for event in apply_safety_gate(
            run_id, intake, emit, db_path=db_path
        )
    ]
    return events, intake.decision in {"block", "hold"}


async def _dispatch_workflow(
    request: _EngineRunRequest,
    provider: str,
    emit: EmitFn,
    options: WorkflowOptions,
) -> AsyncIterator[dict[str, Any]]:
    """Run the intake gate (unless resuming), then stream the real engine.

    The intake gate is shared by every provider. A hard block short-circuits
    the run before any hypotheses are generated. On resume the original goal
    was already screened, so re-gating would only duplicate the intake event.

    Args:
        request: The run's goal, identity, tier, and resolved config.
        provider: The resolved provider, recorded on safety decisions.
        emit: Event sink every event is emitted through.
        options: This dispatch's execution controls.

    Yields:
        The intake gate's events, then the engine's event stream.
    """
    if not options.resume:
        events, blocked = await _run_intake_gate(
            request.run_id,
            request.research_goal,
            provider,
            emit,
            options.db_path,
        )
        for event in events:
            yield event
        if blocked:
            return

    controls = _EngineStreamControls(
        cancelled=options.cancelled,
        db_path=options.db_path,
        emit=emit,
        resume=options.resume,
    )
    async for event in _real_engine_stream(request, controls):
        yield event


async def run_workflow(
    run_id: str,
    research_goal: str,
    config: dict[str, Any],
    options: WorkflowOptions | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive the engine workflow and yield events as the store records them.

    Intake safety screening runs at the shared boundary every run passes
    through, before any work starts (see ``_dispatch_workflow``). On
    ``options.resume``, the engine restores its persisted WorkflowState and
    continues from the last checkpoint instead of running from the goal.

    ``options.sleep_seconds`` paces every event emitted through this
    boundary's emitter -- intake plus the real-engine node stream.

    Args:
        run_id: Run to drive.
        research_goal: The run's research goal.
        config: The run's raw config, resolved against its tier.
        options: Execution controls; defaults apply when omitted.

    Yields:
        Every event the workflow records, in order.
    """
    options = options or WorkflowOptions()
    provider, cfg, run_mode = _resolve_workflow_run(
        run_id, config, options.force_provider, options.db_path
    )
    emit = make_emitter(
        run_id, db_path=options.db_path, sleep_seconds=options.sleep_seconds
    )
    request = _EngineRunRequest(research_goal, run_id, run_mode, cfg)
    async for event in _dispatch_workflow(request, provider, emit, options):
        yield event

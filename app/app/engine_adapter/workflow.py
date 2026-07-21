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
from typing import Any

from app.engine_adapter.engine_stream import _real_engine_stream
from app.engine_adapter.provider import (
    select_provider,
    sync_engine_llm_backend,
)
from app.report_render import make_emitter
from app.run_modes import normalize_run_tier, resolved_run_config
from app.safety import (
    apply_safety_gate,
    screen_intake,
    screen_with_escalation,
)

logger = logging.getLogger(__name__)


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
    """Drive the engine workflow and yield events as the store records them.

    Intake safety screening runs here, at the shared boundary every run
    passes through, before any work starts. On ``resume``, the engine
    restores its persisted WorkflowState and continues from the last
    checkpoint instead of running from the goal. Intake screening is skipped
    on resume — the goal was already gated on the original run.

    ``sleep_seconds`` paces every event emitted through this boundary's
    emitter -- intake plus the real-engine node stream.
    """
    # force_provider lets a caller (e.g. seed.py's demo seeding) pin the
    # provider explicitly, bypassing select_provider()'s env/import probes.
    provider = force_provider or select_provider()
    cfg = resolved_run_config(config)
    run_mode = normalize_run_tier(str(cfg.get("tier") or ""))

    # Sync the run row before dispatch so the generator built downstream
    # (which re-reads the row via run_used_offline) sees the resolved value.
    sync_engine_llm_backend(run_id, cfg, db_path)

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

    async for event in _real_engine_stream(
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

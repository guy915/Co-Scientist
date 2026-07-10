"""Real-engine streaming loop: node events, cancellation, drain, report.

Streams the engine's per-node events in the canonical vocabulary, tracks
the cumulative final state, and — once the stream finishes — drains that
state into the store and emits the report through the shared finalize path.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.engine_adapter.drain import _persist_final_state
from app.engine_adapter.events import (
    _canonical_engine_payload,
    _canonical_event_type,
    _format_milestone,
)
from app.engine_adapter.opts import _build_engine_opts, _build_generator
from app.engine_adapter.provider import _import_hypothesis_generator
from app.mock_workflow import run_mock_workflow
from app.report_render import EmitFn, finalize_report
from app.store import RunStatus

logger = logging.getLogger(__name__)


def _merge_engine_state(
    final_state: dict[str, Any], state: dict[str, Any]
) -> None:
    """Merge one streamed engine snapshot's known keys into `final_state`.

    Mutates `final_state` in place with any of the tracked keys present in
    `state` (a node may omit keys it doesn't touch).
    """
    for key in (
        "hypotheses",
        "articles",
        "tournament_matchups",
        "meta_review",
        "research_overview",
    ):
        if state.get(key) is not None:
            final_state[key] = state[key]


async def _emit_cancelled_event(
    run_id: str, db_path: str | None, emit: EmitFn
) -> dict[str, Any]:
    """Persist a CANCELLED status and return the terminal event to yield."""
    store.update_run_status(run_id, RunStatus.CANCELLED, db_path=db_path)
    return await emit("status", {"status": "cancelled"})


async def _emit_engine_node_event(
    run_id: str,
    node_name: str,
    state: dict[str, Any],
    db_path: str | None,
    emit: EmitFn,
) -> dict[str, Any]:
    """Normalize an engine node to the canonical event vocabulary and emit it.

    Normalizes the node to the canonical mock event vocabulary so every
    downstream consumer reads one shape (no engine.* types), surfaces a
    milestone side-message for key events, and returns the emitted event.
    """
    node_type = _canonical_event_type(node_name)
    payload = _canonical_engine_payload(node_name, node_type, state)
    milestone = _format_milestone(node_type, payload)
    if milestone:
        store.append_message(
            run_id, "system", milestone, "milestone", db_path=db_path
        )
    return await emit(node_type, payload)


async def _stream_engine_nodes(
    generator: Any,
    research_goal: str,
    run_id: str,
    initial_opts: dict[str, Any] | None,
    final_state: dict[str, Any],
    *,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Stream the engine's per-node events, updating `final_state` in place.

    Normalizes each node to the canonical mock event vocabulary, emits it
    (with a milestone side-message for key events), and yields the streamed
    event. On cancellation, yields a final "cancelled" status event and
    returns early; the caller checks `cancelled.is_set()` once this generator
    is exhausted to distinguish that from a natural finish.
    """
    async for node_name, state in generator.generate_hypotheses(
        research_goal=research_goal,
        stream=True,
        run_id=run_id,
        opts=initial_opts,
    ):
        if cancelled and cancelled.is_set():
            yield await _emit_cancelled_event(run_id, db_path, emit)
            return

        # Update final_state from each yielded cumulative snapshot.
        _merge_engine_state(final_state, state)
        yield await _emit_engine_node_event(
            run_id, node_name, state, db_path, emit
        )


def _new_engine_final_state() -> dict[str, Any]:
    """Return an empty accumulator for a streamed engine run's final state."""
    return {
        "hypotheses": [],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }


async def _persist_and_report(
    run_id: str,
    research_goal: str,
    run_mode: str,
    final_state: dict[str, Any],
    *,
    start: float,
    db_path: str | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Drain `final_state` into the store, then build and emit the report.

    Builds, screens, persists, and emits the report through the shared
    finalize path (final safety gate included), so the engine is gated and
    reported on exactly the same terms as the mock.
    """
    report_inputs = _persist_final_state(
        run_id=run_id,
        final_state=final_state,
        db_path=db_path,
    )
    async for event in finalize_report(
        run_id=run_id,
        research_goal=research_goal,
        run_mode=run_mode,
        provider="engine",
        emit=emit,
        execution_time=time.time() - start,
        db_path=db_path,
        **report_inputs,
    ):
        yield event


async def _run_engine_and_report(
    generator: Any,
    research_goal: str,
    run_id: str,
    run_mode: str,
    initial_opts: dict[str, Any] | None,
    *,
    start: float,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Stream the engine's nodes, then drain final state and emit the report.

    Yields every streamed event. On cancellation, `_stream_engine_nodes` has
    already emitted the terminal "cancelled" status event, so this returns
    early and skips draining/reporting.
    """
    final_state = _new_engine_final_state()
    async for event in _stream_engine_nodes(
        generator,
        research_goal,
        run_id,
        initial_opts,
        final_state,
        cancelled=cancelled,
        db_path=db_path,
        emit=emit,
    ):
        yield event
    if cancelled and cancelled.is_set():
        return

    async for event in _persist_and_report(
        run_id,
        research_goal,
        run_mode,
        final_state,
        start=start,
        db_path=db_path,
        emit=emit,
    ):
        yield event


async def _emit_engine_running(
    run_id: str, db_path: str | None, emit: EmitFn
) -> dict[str, Any]:
    """Persist RUNNING status and return the status event to yield.

    Persists the running state, not just emits it. The mock path sets this;
    the engine path previously only emitted the event, leaving the run row
    stuck at "queued" for the entire run (misleading status pill in the UI).
    """
    store.update_run_status(run_id, RunStatus.RUNNING, db_path=db_path)
    return await emit("status", {"status": "running"})


async def _emit_engine_failure(
    run_id: str, error: Exception, db_path: str | None, emit: EmitFn
) -> dict[str, Any]:
    """Log an engine-run crash, mark the run FAILED, and return the event."""
    logger.exception("engine run failed: %s", error)
    store.update_run_status(
        run_id, RunStatus.FAILED, error=str(error), db_path=db_path
    )
    return await emit("status", {"status": "failed", "error": str(error)})


async def _run_engine_provider(
    generator_cls: Any,
    research_goal: str,
    run_id: str,
    run_mode: str,
    cfg: dict[str, Any],
    *,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Run the real engine end to end: stream nodes, drain state, report.

    Persists the running status, then delegates streaming/draining/reporting
    to `_run_engine_and_report`. On any exception, marks the run failed and
    yields a terminal "failed" status event.
    """
    yield await _emit_engine_running(run_id, db_path, emit)

    initial_opts = _build_engine_opts(cfg, run_id, db_path)
    generator = _build_generator(generator_cls, cfg)
    start = time.time()

    try:
        async for event in _run_engine_and_report(
            generator,
            research_goal,
            run_id,
            run_mode,
            initial_opts if initial_opts else None,
            start=start,
            cancelled=cancelled,
            db_path=db_path,
            emit=emit,
        ):
            yield event
    except Exception as e:  # pylint: disable=broad-exception-caught
        yield await _emit_engine_failure(run_id, e, db_path, emit)


def _real_engine_stream(
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
    """Return the real-engine event stream, bridging it into our event log.

    Falls back to the mock workflow if the real engine cannot be imported
    even though the caller resolved to "engine" (e.g. a partial install).
    """
    generator_cls = _import_hypothesis_generator()
    if generator_cls is None:
        return run_mock_workflow(
            run_id=run_id,
            research_goal=research_goal,
            config=cfg,
            db_path=db_path,
            cancelled=cancelled,
            sleep_seconds=sleep_seconds,
        )

    return _run_engine_provider(
        generator_cls,
        research_goal,
        run_id,
        run_mode,
        cfg,
        cancelled=cancelled,
        db_path=db_path,
        emit=emit,
    )

"""Real-engine streaming loop: node events, cancellation, drain, report.

Streams the engine's per-node events in the canonical vocabulary, tracks
the cumulative final state, and — once the stream finishes — drains that
state into the store and emits the report through the shared finalize path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

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
from app.report_render import EmitFn, emit_cancel_or_pause, finalize_report
from app.store import RunStatus

logger = logging.getLogger(__name__)

# Provider tag written on an engine checkpoint's envelope so the resume path
# can tell a real serialized WorkflowState apart from the mock's lightweight
# {provider, run_mode, iteration, config} envelope.
_ENGINE_CHECKPOINT_PROVIDER = "engine"


def _make_engine_checkpoint_callback(
    run_id: str, db_path: str | None
) -> Callable[[str, dict[str, Any]], Awaitable[None]]:
    """Return an async hook that persists the engine's full WorkflowState.

    The engine invokes this after each node completes (and before the node's
    event is yielded), handing over the complete post-node ``WorkflowState``.
    We serialize it with the engine's own versioned serializer and store it as
    a durable checkpoint, tagged as an engine checkpoint so resume restores it
    (rather than re-running from the goal). ``last_event_seq`` records the
    run's event high-water mark so a resumed run assigns new seqs above it.

    The engine import is deferred into the hook body: it runs only when the
    real engine actually checkpoints, so fake-generator tests (which stub
    ``co_scientist`` with a non-package) never trigger it.
    """

    async def _checkpoint(node_name: str, full_state: dict[str, Any]) -> None:
        from co_scientist.checkpoint import (
            CHECKPOINT_VERSION,
            serialize_workflow_state,
        )

        envelope = serialize_workflow_state(
            full_state,
            last_event_seq=store.latest_event_seq(run_id, db_path=db_path),
        )
        store.save_checkpoint(
            run_id,
            stage=f"engine:{node_name}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={"provider": _ENGINE_CHECKPOINT_PROVIDER, **envelope},
            db_path=db_path,
        )

    return _checkpoint


def is_engine_checkpoint(checkpoint: dict[str, Any] | None) -> bool:
    """Whether a stored checkpoint carries a serialized engine WorkflowState."""
    if not checkpoint:
        return False
    state = checkpoint.get("state")
    return (
        isinstance(state, dict)
        and state.get("provider") == _ENGINE_CHECKPOINT_PROVIDER
    )


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
        # Cumulative ExecutionMetrics dict; each snapshot's copy is already
        # merged across nodes by the engine, so last-write-wins is correct.
        "metrics",
    ):
        if state.get(key) is not None:
            final_state[key] = state[key]


_emit_cancelled_event = emit_cancel_or_pause


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


def _engine_node_stream(
    generator: Any,
    research_goal: str,
    run_id: str,
    initial_opts: dict[str, Any] | None,
    checkpoint_callback: Callable[[str, dict[str, Any]], Awaitable[None]],
    *,
    resume: bool,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Return the engine's raw (node_name, snapshot) stream, fresh or resumed.

    A fresh run streams from the goal, checkpointing its full state after each
    node. A resume restores the latest engine checkpoint and re-enters the
    graph at the orchestrator via ``resume_hypotheses`` — completed nodes are
    not re-run — while still checkpointing so a re-interruption is recoverable.
    """
    if not resume:
        return cast(
            "AsyncIterator[tuple[str, dict[str, Any]]]",
            generator.generate_hypotheses(
                research_goal=research_goal,
                stream=True,
                run_id=run_id,
                opts=initial_opts,
                checkpoint_callback=checkpoint_callback,
            ),
        )

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run_id)
    if not is_engine_checkpoint(checkpoint):
        raise RuntimeError(
            f"run {run_id} has no engine checkpoint to resume from"
        )
    assert checkpoint is not None
    restored_state = restore_workflow_state(checkpoint["state"])
    return cast(
        "AsyncIterator[tuple[str, dict[str, Any]]]",
        generator.resume_hypotheses(
            restored_state,
            opts=initial_opts,
            checkpoint_callback=checkpoint_callback,
        ),
    )


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
    resume: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Stream the engine's per-node events, updating `final_state` in place.

    Normalizes each node to the canonical mock event vocabulary, emits it
    (with a milestone side-message for key events), and yields the streamed
    event. Each node's full ``WorkflowState`` is checkpointed (before its
    event is emitted) so the run can resume without re-running completed work.
    On cancellation, yields a final "cancelled" status event and returns
    early; the caller checks `cancelled.is_set()` once this generator is
    exhausted to distinguish that from a natural finish.
    """
    checkpoint_callback = _make_engine_checkpoint_callback(run_id, db_path)
    async for node_name, state in _engine_node_stream(
        generator,
        research_goal,
        run_id,
        initial_opts,
        checkpoint_callback,
        resume=resume,
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
        "metrics": {},
    }


def _persist_run_metrics(
    run_id: str,
    metrics: dict[str, Any] | None,
    execution_time: float,
    db_path: str | None,
) -> None:
    """Persist the run's final ExecutionMetrics dict from streamed state.

    The engine's streamed metrics carry per-node deltas already merged by
    the engine; ``total_time`` is filled from the adapter's own wall clock
    when the stream did not measure one (it only does on the non-streaming
    path).

    Args:
        run_id: Identifier of the run the metrics belong to.
        metrics: The last streamed cumulative metrics dict, if any.
        execution_time: Wall-clock seconds the adapter measured.
        db_path: Optional override for the SQLite database path.
    """
    persisted = dict(metrics or {})
    if not persisted.get("total_time"):
        persisted["total_time"] = round(execution_time, 3)
    store.save_run_metrics(run_id, persisted, db_path=db_path)


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
    _persist_run_metrics(
        run_id,
        final_state.get("metrics"),
        execution_time=time.time() - start,
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
    resume: bool = False,
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
        resume=resume,
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
    resume: bool = False,
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
            resume=resume,
        ):
            yield event
    except Exception as e:
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
    resume: bool = False,
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
        resume=resume,
    )

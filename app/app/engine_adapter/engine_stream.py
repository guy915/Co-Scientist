"""Real-engine streaming loop: node events, cancellation, drain, report.

Streams the engine's per-node events in the canonical vocabulary, tracks
the cumulative final state, and — once the stream finishes — drains that
state into the store and emits the report through the shared finalize path.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

from app import store

# The dispatch value objects and the post-stream drain/report stage moved
# verbatim to sibling modules; every moved name is re-exported so this
# module's namespace (the seam tests and callers import against) keeps
# resolving.
from app.engine_adapter.engine_stream_context import (
    _EngineRunInputs as _EngineRunInputs,
)
from app.engine_adapter.engine_stream_context import (
    _EngineRunRequest as _EngineRunRequest,
)
from app.engine_adapter.engine_stream_context import (
    _EngineStreamControls as _EngineStreamControls,
)
from app.engine_adapter.engine_stream_report import (
    _drain_and_stage_events as _drain_and_stage_events,
)
from app.engine_adapter.engine_stream_report import (
    _new_engine_final_state,
    _persist_and_report,
)
from app.engine_adapter.engine_stream_report import (
    _persist_run_metrics as _persist_run_metrics,
)
from app.engine_adapter.events import (
    _canonical_engine_payload,
    _canonical_event_type,
    append_node_milestone,
)
from app.engine_adapter.opts import _build_engine_opts, _build_generator
from app.engine_adapter.provider import _import_hypothesis_generator
from app.report_render import EmitFn, emit_cancel_or_pause
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
            store.NewCheckpoint(
                stage=f"engine:{node_name}",
                schema_version=CHECKPOINT_VERSION,
                last_event_seq=envelope["last_event_seq"],
                state={"provider": _ENGINE_CHECKPOINT_PROVIDER, **envelope},
            ),
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
        "proximity_graph",
        # Cumulative ExecutionMetrics dict; each snapshot's copy is already
        # merged across nodes by the engine, so last-write-wins is correct.
        "metrics",
    ):
        if state.get(key) is not None:
            final_state[key] = state[key]


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
    append_node_milestone(run_id, node_type, payload, db_path=db_path)
    return await emit(node_type, payload)


def _fresh_engine_node_stream(
    run: _EngineRunInputs,
    checkpoint_callback: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Return a fresh engine run's raw (node_name, snapshot) stream.

    Streams from the goal, checkpointing the full state after each node.
    """
    from co_scientist import RunCallbacks

    return cast(
        "AsyncIterator[tuple[str, dict[str, Any]]]",
        run.generator.generate_hypotheses(
            research_goal=run.research_goal,
            stream=True,
            run_id=run.run_id,
            opts=run.initial_opts,
            callbacks=RunCallbacks(checkpoint=checkpoint_callback),
        ),
    )


def _resumed_engine_node_stream(
    run: _EngineRunInputs,
    checkpoint_callback: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Return a resumed engine run's raw (node_name, snapshot) stream.

    Restores the latest engine checkpoint and re-enters the graph at the
    orchestrator via ``resume_hypotheses`` -- completed nodes are not
    re-run -- while still checkpointing so a re-interruption is recoverable.
    """
    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run.run_id)
    if not is_engine_checkpoint(checkpoint):
        raise RuntimeError(
            f"run {run.run_id} has no engine checkpoint to resume from"
        )
    assert checkpoint is not None
    restored_state = restore_workflow_state(checkpoint["state"])
    return cast(
        "AsyncIterator[tuple[str, dict[str, Any]]]",
        run.generator.resume_hypotheses(
            restored_state,
            opts=run.initial_opts,
            checkpoint_callback=checkpoint_callback,
        ),
    )


def _engine_node_stream(
    run: _EngineRunInputs,
    checkpoint_callback: Callable[[str, dict[str, Any]], Awaitable[None]],
    *,
    resume: bool,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Return the engine's raw (node, snapshot) stream, fresh or resumed."""
    if not resume:
        return _fresh_engine_node_stream(run, checkpoint_callback)
    return _resumed_engine_node_stream(run, checkpoint_callback)


async def _stream_engine_nodes(
    run: _EngineRunInputs,
    final_state: dict[str, Any],
    controls: _EngineStreamControls,
) -> AsyncIterator[dict[str, Any]]:
    """Stream the engine's per-node events, updating `final_state` in place.

    Normalizes each node to the canonical mock event vocabulary, emits it
    (with a milestone side-message for key events), and yields the streamed
    event. Each node's full ``WorkflowState`` is checkpointed (before its
    event is emitted) so the run can resume without re-running completed work.
    On cancellation, yields a final "cancelled" status event and returns
    early; the caller checks `cancelled.is_set()` once this generator is
    exhausted to distinguish that from a natural finish.

    Args:
        run: The engine dispatch's generator, goal, and run identity.
        final_state: Accumulator updated in place from each snapshot.
        controls: Cancellation, db path, event sink, and resume flag.

    Yields:
        Each streamed node event, in canonical vocabulary.
    """
    db_path, emit = controls.db_path, controls.emit
    cancelled = controls.cancelled
    checkpoint_callback = _make_engine_checkpoint_callback(run.run_id, db_path)
    async for node_name, state in _engine_node_stream(
        run, checkpoint_callback, resume=controls.resume
    ):
        if cancelled and cancelled.is_set():
            yield await emit_cancel_or_pause(run.run_id, db_path, emit)
            return

        # Update final_state from each yielded cumulative snapshot.
        _merge_engine_state(final_state, state)
        yield await _emit_engine_node_event(
            run.run_id, node_name, state, db_path, emit
        )


async def _run_engine_and_report(
    run: _EngineRunInputs,
    controls: _EngineStreamControls,
    *,
    start: float,
) -> AsyncIterator[dict[str, Any]]:
    """Stream the engine's nodes, then drain final state and emit the report.

    Yields every streamed event. On cancellation, `_stream_engine_nodes` has
    already emitted the terminal "cancelled" status event, so this returns
    early and skips draining/reporting.

    Args:
        run: The engine dispatch's generator, goal, and run identity.
        controls: Cancellation, db path, event sink, and resume flag.
        start: Wall-clock start of the dispatch, for execution time.

    Yields:
        Every streamed node event, then the drain and report events.
    """
    final_state = _new_engine_final_state()
    async for event in _stream_engine_nodes(run, final_state, controls):
        yield event
    if controls.cancelled and controls.cancelled.is_set():
        return

    async for event in _persist_and_report(
        run, final_state, controls, start=start
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
    request: _EngineRunRequest,
    controls: _EngineStreamControls,
) -> AsyncIterator[dict[str, Any]]:
    """Run the real engine end to end: stream nodes, drain state, report.

    Persists the running status, then delegates streaming/draining/reporting
    to `_run_engine_and_report`. On any exception, marks the run failed and
    yields a terminal "failed" status event.

    Args:
        generator_cls: The resolved ``HypothesisGenerator`` class.
        request: The run's goal, identity, tier, and resolved config.
        controls: Cancellation, db path, event sink, and resume flag.

    Yields:
        Every event the dispatch produces, ending in a terminal status.
    """
    db_path, emit = controls.db_path, controls.emit
    run_id = request.run_id
    yield await _emit_engine_running(run_id, db_path, emit)

    initial_opts = _build_engine_opts(request.cfg, run_id, db_path)
    run_row = store.get_run(run_id, db_path=db_path)
    offline = run_row is not None and store.run_used_offline(run_row)
    generator = _build_generator(generator_cls, request.cfg, offline=offline)
    run = _EngineRunInputs(
        generator,
        request.research_goal,
        run_id,
        request.run_mode,
        initial_opts,
    )

    try:
        async for event in _run_engine_and_report(
            run, controls, start=time.time()
        ):
            yield event
    except Exception as e:
        yield await _emit_engine_failure(run_id, e, db_path, emit)


def _real_engine_stream(
    request: _EngineRunRequest,
    controls: _EngineStreamControls,
) -> AsyncIterator[dict[str, Any]]:
    """Return the real-engine event stream, bridging it into our event log.

    Args:
        request: The run's goal, identity, tier, and resolved config.
        controls: Cancellation, db path, event sink, and resume flag.

    Returns:
        The dispatch's event stream.

    Raises:
        RuntimeError: When the engine is unavailable. Raised here, before
            the async generator is entered, so a missing engine fails the
            call rather than the first iteration.
    """
    generator_cls = _import_hypothesis_generator()
    if generator_cls is None:
        raise RuntimeError(
            "real engine is unavailable; refusing to substitute mock science"
        )

    return _run_engine_provider(generator_cls, request, controls)

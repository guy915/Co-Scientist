"""Post-stream stage: drain a streamed run's final state and report it.

Everything the streaming path does once the engine's node stream is
exhausted -- the final-state accumulator it filled, the run metrics it
persists, the post-drain stage events, and the shared finalize path that
builds and emits the report. Split from ``app.engine_adapter.engine_stream``,
which re-exports every name here so its namespace keeps resolving.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.engine_adapter.drain import _persist_final_state
from app.engine_adapter.engine_stream_context import (
    _EngineRunInputs,
    _EngineStreamControls,
)
from app.report_render import EmitFn, ReportRequest, finalize_report


def _new_engine_final_state() -> dict[str, Any]:
    """Return an empty accumulator for a streamed engine run's final state."""
    return {
        "hypotheses": [],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
        "proximity_graph": {},
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


async def _drain_and_stage_events(
    run_id: str,
    final_state: dict[str, Any],
    db_path: str | None,
    emit: EmitFn,
) -> tuple[Any, list[dict[str, Any]]]:
    """Drain `final_state` into the store, emitting the post-drain stage events.

    Emits the ``safety.hypothesis``, ``citation.grounding``, and
    ``citation_audit`` stage events from counts the drain already computed,
    so the engine path carries the same per-stage fidelity the mock's
    scripted stages do.

    Returns:
        A tuple of (drain result, the stage events emitted, in order).
    """
    drained = _persist_final_state(
        run_id=run_id,
        final_state=final_state,
        db_path=db_path,
    )
    events = [
        await emit("safety.hypothesis", drained.safety_counts),
        await emit("citation.grounding", drained.grounding_counts),
        await emit(
            "citation_audit", dict(drained.report_inputs["citation_summary"])
        ),
    ]
    return drained, events


async def _persist_and_report(
    run: _EngineRunInputs,
    final_state: dict[str, Any],
    controls: _EngineStreamControls,
    *,
    start: float,
) -> AsyncIterator[dict[str, Any]]:
    """Drain `final_state` into the store, then build and emit the report.

    Builds, screens, persists, and emits the report through the shared
    finalize path (final safety gate included), so the engine is gated and
    reported on exactly the same terms as the mock.

    Args:
        run: The engine dispatch's generator, goal, and run identity.
        final_state: The streamed run's accumulated final state.
        controls: Cancellation, db path, event sink, and resume flag.
        start: Wall-clock start of the dispatch, for execution time.

    Yields:
        The post-drain stage events, then the report events.
    """
    db_path, emit = controls.db_path, controls.emit
    drained, stage_events = await _drain_and_stage_events(
        run.run_id, final_state, db_path, emit
    )
    for event in stage_events:
        yield event
    _persist_run_metrics(
        run.run_id,
        final_state.get("metrics"),
        execution_time=time.time() - start,
        db_path=db_path,
    )
    async for event in finalize_report(
        run.run_id,
        ReportRequest(
            research_goal=run.research_goal,
            run_mode=run.run_mode,
            provider="engine",
            execution_time=time.time() - start,
            db_path=db_path,
            **drained.report_inputs,
        ),
        emit,
    ):
        yield event

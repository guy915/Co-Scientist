"""Recording of fallback-served schema degradations (L7).

When a non-critical enhancement node's LLM output cannot be parsed after
all retries, ``get_fallback_response`` serves a placeholder so the run
continues. These tests pin the visibility half of that behavior: the
degradation is appended to the active workflow state's ``degraded_nodes``
and emitted as a ``schema_degraded`` progress event, the state key is
initialized for every run shape, and it survives a checkpoint round trip
into the durable path.
"""

import asyncio
from typing import Any, cast

from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.generator.initial_state import (
    RunCapabilities,
    RunIdentity,
    _build_initial_state,
)
from co_scientist.generator.streaming import (
    _build_generation_result,
    _initial_cumulative_stream_state,
)
from co_scientist.llm_json import get_fallback_response
from co_scientist.models import ExecutionMetrics
from co_scientist.progress import (
    _ACTIVE_WORKFLOW_STATE,
    emit_progress,
)
from co_scientist.state import WorkflowState


def _fresh_state(**extra: Any) -> WorkflowState:
    """Build a minimal workflow-state dict for recorder tests."""
    state: dict[str, Any] = {"degraded_nodes": []}
    state.update(extra)
    return cast(WorkflowState, state)


async def test_fallback_records_degradation_into_active_state() -> None:
    """A served fallback appends its schema name to the active state."""
    state = _fresh_state()
    await emit_progress(state, "meta_review_start", "working", 45)

    fallback = get_fallback_response({"name": "meta_review"})

    assert fallback is not None
    assert state["degraded_nodes"] == ["meta_review"]


async def test_degradations_accumulate_in_serve_order() -> None:
    """Repeated degradations append, keeping the order they happened in."""
    state = _fresh_state()
    await emit_progress(state, "phase", "working", 10)

    get_fallback_response({"name": "meta_review"})
    get_fallback_response({"name": "research_overview"})

    assert state["degraded_nodes"] == ["meta_review", "research_overview"]


async def test_fallback_without_active_state_still_serves() -> None:
    """No active state: the fallback is served, nothing is recorded."""
    _ACTIVE_WORKFLOW_STATE.set(None)

    fallback = get_fallback_response({"name": "hypothesis_batch_review"})

    assert fallback == {"reviews": []}


async def test_fallback_records_into_restored_state_lacking_key() -> None:
    """A checkpoint-restored state predating the key still records."""
    state = cast(WorkflowState, {})
    await emit_progress(state, "phase", "working", 10)

    get_fallback_response({"name": "deep_verification"})

    assert state["degraded_nodes"] == ["deep_verification"]


async def test_degradation_emits_progress_event() -> None:
    """A listening progress callback receives a schema_degraded event."""
    events: list[tuple[str, dict[str, Any]]] = []

    async def callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    state = _fresh_state(progress_callback=callback)
    await emit_progress(state, "phase", "working", 10)

    get_fallback_response({"name": "research_overview"})
    await asyncio.sleep(0)

    degraded_events = [e for e in events if e[0] == "schema_degraded"]
    assert len(degraded_events) == 1
    payload = degraded_events[0][1]
    assert payload["schema"] == "research_overview"
    assert "research_overview" in payload["message"]


async def test_degradation_event_failure_cannot_break_the_run() -> None:
    """A raising progress callback does not disturb fallback service."""

    async def callback(event: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("listener exploded")

    state = _fresh_state()
    await emit_progress(state, "phase", "working", 10)
    # Installed after the stash so the raising listener only hears the
    # degradation event under test.
    state["progress_callback"] = callback

    fallback = get_fallback_response({"name": "meta_review"})
    await asyncio.sleep(0)

    assert fallback is not None
    assert state["degraded_nodes"] == ["meta_review"]


def test_critical_node_fallback_records_nothing() -> None:
    """Foundational nodes raise instead of degrading; nothing records."""
    state = _fresh_state()
    _ACTIVE_WORKFLOW_STATE.set(state)

    assert get_fallback_response({"name": "hypothesis_generation"}) is None
    assert state["degraded_nodes"] == []


def test_initial_state_seeds_empty_degraded_nodes() -> None:
    """Every fresh run starts with an empty degraded_nodes list."""
    state = _build_initial_state(
        config_fields={},
        identity=RunIdentity(
            research_goal="goal", start_time=0.0, run_id="run-1"
        ),
        capabilities=RunCapabilities(),
        opts={},
        user_inputs={},
    )

    assert state["degraded_nodes"] == []


def test_streaming_cumulative_state_seeds_degraded_nodes() -> None:
    """The streamed snapshot shape carries the key from the first node."""
    assert _initial_cumulative_stream_state()["degraded_nodes"] == []


def test_generation_result_carries_degraded_nodes() -> None:
    """The non-streaming result dict surfaces the run's degraded nodes."""
    final_state = cast(
        WorkflowState,
        {
            "hypotheses": [],
            "metrics": ExecutionMetrics(),
            "degraded_nodes": ["proximity_analysis"],
        },
    )

    result = _build_generation_result(final_state, execution_time=1.0)

    assert result["degraded_nodes"] == ["proximity_analysis"]


def test_generation_result_defaults_to_empty_degraded_nodes() -> None:
    """A final state without the key yields an empty list, not a KeyError."""
    final_state = cast(
        WorkflowState, {"hypotheses": [], "metrics": ExecutionMetrics()}
    )

    result = _build_generation_result(final_state, execution_time=1.0)

    assert result["degraded_nodes"] == []


def test_durable_commit_captures_recorded_degradation() -> None:
    """The durable path's commit keeps a mid-node fallback recording.

    Mirrors ``task_runtime.execute_task_node``: the node reports progress
    (stashing its state), its LLM call degrades, and the commit copies the
    whole state dict -- so the in-place ``degraded_nodes`` append survives
    into the checkpointed state without the node returning it.
    """
    from co_scientist.task_runtime import apply_task_update

    state = _fresh_state()
    _ACTIVE_WORKFLOW_STATE.set(state)

    get_fallback_response({"name": "meta_review"})
    committed = apply_task_update(state, {"meta_review": {}})

    assert committed["degraded_nodes"] == ["meta_review"]


def test_checkpoint_round_trips_degraded_nodes() -> None:
    """The durable path persists degraded nodes across a checkpoint."""
    state: dict[str, Any] = {
        "hypotheses": [],
        "articles": None,
        "messages": [],
        "metrics": ExecutionMetrics(),
        "degraded_nodes": ["meta_review", "research_overview"],
    }

    envelope = serialize_workflow_state(state, last_event_seq=3)
    assert envelope["state"]["degraded_nodes"] == [
        "meta_review",
        "research_overview",
    ]

    restored = restore_workflow_state(envelope)
    assert restored["degraded_nodes"] == [
        "meta_review",
        "research_overview",
    ]

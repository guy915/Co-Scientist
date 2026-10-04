import asyncio
import contextvars
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# Avoid importing state and LangGraph at runtime for a lightweight progress
# helper.
if TYPE_CHECKING:
    from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Task-local state keeps concurrent runs' fallback records isolated.
_ACTIVE_WORKFLOW_STATE: contextvars.ContextVar["WorkflowState | None"] = (
    contextvars.ContextVar("co_scientist_active_workflow_state", default=None)
)

# Keep strong references until asynchronous delivery completes; loops may
# otherwise drop tasks.
_BACKGROUND_TASKS: set["asyncio.Task[None]"] = set()


async def emit_progress(
    state: "WorkflowState",
    event: str,
    message: str,
    progress: float,
    **extra: Any,
) -> None:
    _ACTIVE_WORKFLOW_STATE.set(state)
    callback = state.get("progress_callback")
    if callback:
        await callback(
            event,
            {
                "message": message,
                "progress": progress,
                **extra,
            },
        )


def record_schema_degradation(
    schema_name: str, state: "WorkflowState | None" = None
) -> None:
    """Prefer losing a degradation label to recording it in another run.
    Explicit state avoids depending on whether the node emitted progress
    first.
    """
    if state is None:
        state = _ACTIVE_WORKFLOW_STATE.get()
    if state is None or not isinstance(state, dict):
        return
    # Restored checkpoints may carry None, so setdefault would silently lose
    # degradation records.
    degraded = state.get("degraded_nodes")
    if not isinstance(degraded, list):
        degraded = []
        state["degraded_nodes"] = degraded
    degraded.append(schema_name)
    _emit_degradation_event(state, schema_name)


def _emit_degradation_event(state: "WorkflowState", schema_name: str) -> None:
    """A synchronous fallback schedules delivery; missing loops or callback
    failures cannot fail science.
    """
    callback = state.get("progress_callback")
    if callback is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_safe_degradation_callback(callback, schema_name))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _safe_degradation_callback(
    callback: "Callable[[str, dict[str, Any]], Awaitable[None]]",
    schema_name: str,
) -> None:
    """Progress is observational: listener failure must not fail a gracefully
    degraded node.
    """
    try:
        await callback(
            "schema_degraded",
            {
                "message": (
                    f"Node '{schema_name}' returned no parseable output; "
                    "continuing with a placeholder"
                ),
                "schema": schema_name,
            },
        )
    except Exception:
        logger.debug(
            "progress callback failed for schema_degraded (%s)",
            schema_name,
            exc_info=True,
        )

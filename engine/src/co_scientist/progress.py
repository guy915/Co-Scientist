"""Progress emission helper shared by workflow agents.

Also home to the schema-degradation recorder: when a non-critical node's
LLM output cannot be parsed after all retries and a fallback is served
(see ``llm.structured.validate.get_fallback_response``), the degradation is
recorded here so the run's report can say a section is blank because generation
failed, rather than showing silence.
"""

import asyncio
import contextvars
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# WorkflowState is only needed for the type hint below, so import it under
# TYPE_CHECKING to avoid a runtime dependency on the state module (and its
# langgraph import) from this lightweight, widely-imported helper.
if TYPE_CHECKING:
    from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# The workflow state dict the currently executing node reports progress
# against. Every agent node calls emit_progress with its own state, so this
# is refreshed at each phase boundary; the fallback path in
# ``llm.structured.validate.get_fallback_response`` -- which runs deep below any
# node and receives no state of its own -- reads it to record a served fallback
# into the run's ``degraded_nodes`` state key. ContextVar-scoped, like the
# run-scoped id factory in ``models``: each durable task runs in its own
# asyncio task context, so concurrent runs never see each other's state. A stale
# value is harmless -- see ``record_schema_degradation``.
_ACTIVE_WORKFLOW_STATE: contextvars.ContextVar["WorkflowState | None"] = (
    contextvars.ContextVar("co_scientist_active_workflow_state", default=None)
)

# Strong references to in-flight schema_degraded deliveries; a fire-and-
# forget create_task can be dropped by the loop mid-shutdown, and the
# callback's completion discards the reference.
_BACKGROUND_TASKS: set["asyncio.Task[None]"] = set()


async def emit_progress(
    state: "WorkflowState",
    event: str,
    message: str,
    progress: float,
    **extra: Any,
) -> None:
    """Emit progress callback if configured.

    Args:
        state: Current workflow state holding the optional callback.
        event: Progress event name.
        message: Human-readable progress message.
        progress: Progress fraction or percentage for the event.
        **extra: Additional scalar fields merged into the payload.
    """
    # Refresh the fallback path's handle on the live state (see the module
    # comment); a no-op for callers that only want the emission.
    _ACTIVE_WORKFLOW_STATE.set(state)
    # progress_callback is optional (e.g. wired up by the FastAPI app to
    # stream SSE progress events to the frontend); when absent this is a
    # silent no-op so agents can call emit_progress unconditionally at every
    # phase boundary without checking whether a caller is listening.
    callback = state.get("progress_callback")
    if callback:
        await callback(
            event,
            {
                "message": message,
                "progress": progress,
                # Extra fields (e.g. key_areas, hypotheses_count) are merged
                # flat into the payload alongside message/progress.
                **extra,
            },
        )


def record_schema_degradation(
    schema_name: str, state: "WorkflowState | None" = None
) -> None:
    """Record that a fallback replaced an enhancement node's LLM output.

    Appends the schema name to the workflow state's ``degraded_nodes`` and
    emits a ``schema_degraded`` progress event when a callback is
    listening. Called by ``llm.structured.validate.get_fallback_response`` the
    moment a fallback is served; the run-continues behavior is decided there,
    this only makes the degradation durable and visible.

    Best-effort by design: without an active workflow state in this context
    (no node has reported progress yet, or the call happens outside a
    workflow) the degradation stays logged but unrecorded. A lost label is
    acceptable; writing into the wrong run's state never is.

    Args:
        schema_name: The failed schema's name, which names its node.
        state: The state to record into. Omitted by the fallback path,
            which runs deep below any node and has none of its own, so it
            reads the contextvar instead. A node degrading its *own* call
            passes its state: the contextvar is a side effect of whether
            that node happened to emit progress first, which is not a
            dependency a degradation should acquire.
    """
    if state is None:
        state = _ACTIVE_WORKFLOW_STATE.get()
    if state is None or not isinstance(state, dict):
        return
    # Replace anything that is not a list rather than skipping the record:
    # a state restored from a checkpoint whose payload never held this key
    # carries it as None (``checkpoint._PLAIN_STATE_KEYS`` writes
    # ``state.get(key)`` for every declared field), and `setdefault` then
    # hands back that None -- which silently dropped every degradation on
    # such a state instead of starting the list.
    degraded = state.get("degraded_nodes")
    if not isinstance(degraded, list):
        degraded = []
        state["degraded_nodes"] = degraded
    degraded.append(schema_name)
    _emit_degradation_event(state, schema_name)


def _emit_degradation_event(state: "WorkflowState", schema_name: str) -> None:
    """Schedule the schema_degraded progress event when a callback listens.

    The caller is synchronous (the fallback path), so the async callback is
    scheduled on the running loop rather than awaited; a missing loop or a
    failing callback cannot disturb the run.
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
    """Deliver one schema_degraded event, swallowing callback errors.

    Progress emission is observational; a listener's failure must not
    convert a gracefully degraded node into a failed run.
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

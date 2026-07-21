"""Progress emission helper shared by workflow agents."""

from typing import TYPE_CHECKING, Any

# WorkflowState is only needed for the type hint below, so import it under
# TYPE_CHECKING to avoid a runtime dependency on the state module (and its
# langgraph import) from this lightweight, widely-imported helper.
if TYPE_CHECKING:
    from co_scientist.state import WorkflowState


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

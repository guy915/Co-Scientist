"""Progress emission helper shared by workflow nodes."""

from typing import Any, TYPE_CHECKING

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
    callback = state.get("progress_callback")
    if callback:
        await callback(event, {
            "message": message,
            "progress": progress,
            **extra
        })

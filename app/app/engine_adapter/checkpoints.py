"""Engine checkpoint tagging shared across run paths.

Both the durable node executor (``engine_tasks.support``) and the resume
launcher (``runs.lifecycle``) agree on a single provider tag written onto an
engine checkpoint's envelope, so a stored ``WorkflowState`` can be told apart
from any lighter-weight envelope. ``is_engine_checkpoint`` is the reader half,
re-exported through the ``engine_adapter`` package namespace.
"""

from __future__ import annotations

from typing import Any, cast

# Provider tag written on an engine checkpoint's envelope so the resume path
# can recognize a serialized WorkflowState (rather than re-running from goal).
ENGINE_CHECKPOINT_PROVIDER = "engine"


def is_engine_checkpoint(checkpoint: dict[str, Any] | None) -> bool:
    """Whether a stored checkpoint carries a serialized engine WorkflowState."""
    if not checkpoint:
        return False
    state = checkpoint.get("state")
    return (
        isinstance(state, dict)
        and state.get("provider") == ENGINE_CHECKPOINT_PROVIDER
    )


def restore_workflow_state(
    serialized: dict[str, Any], *, tool_registry: Any = None
) -> dict[str, Any]:
    """Restore state and reapply a campaign route across task recovery."""
    from co_scientist.checkpoint import (
        restore_workflow_state as restore_engine_state,
    )

    from app.execution_policy import effective_execution_model

    state = cast(
        dict[str, Any],
        restore_engine_state(serialized, tool_registry=tool_registry),
    )
    campaign_model = effective_execution_model(None)
    if campaign_model is not None:
        state["model_name"] = campaign_model
        state["supervisor_model_name"] = campaign_model
    return state

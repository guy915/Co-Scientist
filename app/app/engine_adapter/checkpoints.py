"""Engine checkpoint tagging shared across run paths.

Both the durable node executor (``engine_tasks_support``) and the resume
launcher (``runs_lifecycle``) agree on a single provider tag written onto an
engine checkpoint's envelope, so a stored ``WorkflowState`` can be told apart
from any lighter-weight envelope. ``is_engine_checkpoint`` is the reader half,
re-exported through the ``engine_adapter`` package namespace.
"""

from __future__ import annotations

from typing import Any

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

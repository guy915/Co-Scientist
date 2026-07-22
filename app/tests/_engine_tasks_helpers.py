"""Shared fixtures and stand-ins for the durable engine-task test suite.

Leading underscore so pytest does not collect this module. The split
``test_engine_tasks*.py`` files import these builders, which were extracted
verbatim from the original single ``test_engine_tasks.py``.
"""

import time
from typing import Any

from co_scientist.models import ExecutionMetrics

from app import store
from app.safety import screen_intake


def _task_state(run_id: str) -> dict[str, Any]:
    """Build the minimal serializable state used by task-runtime fixtures."""
    return {
        "run_id": run_id,
        "research_goal": "Task-level science",
        "model_name": "fixture",
        "supervisor_model_name": "fixture",
        "hypotheses": [],
        "articles": [],
        "messages": [],
        "metrics": ExecutionMetrics(),
        "mcp_available": False,
        "current_iteration": 0,
        "start_time": time.time(),
    }


def _seed_checkpoint(
    run_id: str,
    state: dict[str, Any],
    *,
    stage: str = "fixture",
    db_path: str | None = None,
) -> int:
    """Serialize ``state`` and commit it as an engine checkpoint, return seq."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(state, last_event_seq=0)
    return store.save_checkpoint(
        run_id,
        stage=stage,
        schema_version=CHECKPOINT_VERSION,
        last_event_seq=0,
        state={"provider": "engine", **envelope},
        db_path=db_path,
    )


class _Generator:
    tool_registry = None

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def prepare_task_state(self, *_: Any, **__: Any) -> dict[str, Any]:
        return self.state


async def _deterministic_screen(
    _run_id: str, _stage: str, text: str, *_: Any, **__: Any
) -> Any:
    """Stand in for the intake escalation with its deterministic verdict.

    Matches ``screen_with_escalation``'s signature (run id, stage, then the
    screened text) and returns what that wrapper returns for any run these
    tests create: the deterministic decision, with no contextual model call.
    """
    return screen_intake(text)

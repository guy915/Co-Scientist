"""Single-item Reflection adaptation below graph and durable scheduling."""

import asyncio
from collections.abc import Mapping
from typing import Any

from co_scientist.agents.reflection.verification import (
    _verification_evidence_context,
    _VerificationContext,
    _verify_one,
)
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState

_VALID_VERDICTS = frozenset({"holds", "weakened", "undermined"})


def has_valid_verification(result: Mapping[str, Any] | None) -> bool:
    """Whether a result carries one of the verifier's usable verdicts."""
    verdict = result.get("verdict") if result is not None else None
    return isinstance(verdict, str) and verdict in _VALID_VERDICTS


async def verify_hypothesis(
    state: WorkflowState, hypothesis: Hypothesis
) -> dict[str, Any] | None:
    """Verify one idea with a fresh call-local concurrency guard.

    Graph batches call the same leaf with their shared batch semaphore;
    durable items have no shared event-loop primitives or context assembly.
    The leaf preserves ordinary failures as None and task-control errors.
    """
    context = _VerificationContext(
        research_goal=state["research_goal"],
        model_name=state["model_name"],
        tool_registry=state.get("tool_registry"),
        state=state,
    )
    return await _verify_one(
        hypothesis,
        context,
        asyncio.Semaphore(1),
        _verification_evidence_context(state),
    )

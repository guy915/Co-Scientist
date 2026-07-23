"""Evolution round lifecycle: pool selection, progress, and finalization.

Owns the round-level scaffolding around the per-hypothesis evolution
calls: choosing the top-k pool to evolve, emitting the start/complete
progress events, and assembling the node's state delta. ``evolve.py``
re-exports these names so the original
``co_scientist.agents.evolution.evolve`` import path is unaffected.
"""

import logging
from typing import Any

from co_scientist.agents.evolution.evolve_results import (
    _build_evolve_state_delta,
)
from co_scientist.constants import (
    PROGRESS_EVOLVE_COMPLETE,
    PROGRESS_EVOLVE_START,
)
from co_scientist.models import Hypothesis
from co_scientist.progress import emit_progress
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _select_evolution_pool(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
) -> list[Hypothesis]:
    """Selects the top-k hypotheses to evolve.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool entering evolution; assumed already
            sorted by descending Elo rating (set by ranking_node).

    Returns:
        The top_k hypotheses to evolve. ``len(top_k)`` is the real attempt
        count (which may be below the configured maximum when fewer
        hypotheses are available), so callers report progress off it.
    """
    evolution_max_count = state.get("evolution_max_count", 10)

    # hypotheses arrives already sorted by descending Elo rating (set by
    # ranking_node's return), so a plain slice selects the top performers
    # without needing to re-sort here.
    return hypotheses[:evolution_max_count]


async def _emit_evolution_start(
    state: WorkflowState, actual_count: int
) -> None:
    """Logs and emits the start-of-phase progress for this evolution round."""
    logger.info("Evolving top %s hypotheses", actual_count)

    await emit_progress(
        state,
        "evolve_start",
        f"Evolving top {actual_count} hypotheses...",
        PROGRESS_EVOLVE_START,
    )

    logger.info(
        "Evolving %s hypotheses with strategic context sampling "
        "(max 15 context hypotheses per evolution)",
        actual_count,
    )


async def _prepare_evolution_round(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
) -> tuple[list[Hypothesis], list[str], dict[str, Any] | None]:
    """Selects the evolution pool and emits the start-of-phase progress.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool entering evolution; assumed already
            sorted by descending Elo rating (set by ranking_node).

    Returns:
        Tuple of (top_k hypotheses to evolve, flattened previously removed
        duplicate texts, supervisor guidance for the evolution phase).
    """
    top_k = _select_evolution_pool(state, hypotheses)
    await _emit_evolution_start(state, len(top_k))

    # Flatten proximity.py's removed_duplicates dicts down to bare text;
    # used below to steer evolution away from recreating hypotheses that
    # were already pruned as duplicates in an earlier iteration.
    removed_duplicates = [
        dup.get("text", "") for dup in state.get("removed_duplicates", [])
    ]
    supervisor_guidance = state.get("supervisor_guidance")

    return top_k, removed_duplicates, supervisor_guidance


async def _finalize_evolve_result(
    state: WorkflowState,
    children: list[Hypothesis],
    evolution_details: list[dict[str, Any]],
    attempt_count: int,
) -> dict[str, Any]:
    """Appends the evolution children and builds the evolve_node state delta.

    Also emits the completion progress event for the evolution phase.

    Args:
        state: Current workflow state.
        children: New immutable children produced by this round's evolution.
        evolution_details: Evolution detail entries, one per created child.
        attempt_count: Number of parents evolution attempted this round.

    Returns:
        The evolve_node state delta dictionary.
    """
    # Children are ADDED to the pool; parents and every other hypothesis stay
    # active so both compete in the next tournament (paper invariant). The
    # pool no longer shrinks to the evolved subset.
    logger.info(
        "Evolution produced %s new children from %s attempts",
        len(children),
        attempt_count,
    )

    # Emit progress
    await emit_progress(
        state,
        "evolve_complete",
        f"Evolved {len(children)} new child hypotheses",
        PROGRESS_EVOLVE_COMPLETE,
        evolved_count=len(children),
    )

    return _build_evolve_state_delta(children, evolution_details, attempt_count)

"""What the terminal synthesis publishes when the provider is unreachable.

Split from ``research_overview.py`` (at its 500-line ceiling) rather than
inlined there. The distinction this module owns is which of the node's two
firings failed: the terminal one publishes the document, so its failure is
a blank report section the reader must be told about; the periodic one
only drafts guidance for the next generate cycle and publishes nothing, so
its failure labels no section at all.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from co_scientist.agents.node_degradation import (
    durable_retries_remain,
    run_or_degrade,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS, short_error_text
from co_scientist.models import phase_message
from co_scientist.scheduling.models import TaskType, stacked_task_values
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# The node's key in ``llm.structured.validate._ENHANCEMENT_NODE_FALLBACKS``, and
# the label the report reads back as a degraded section.
_OVERVIEW_SCHEMA = "research_overview"

_LOST = (
    "publishing the report without the overview, Specific Aims, knowledge "
    "base and research contacts"
)


def is_interim_firing(state: WorkflowState) -> bool:
    """Whether this is a periodic firing rather than the terminal one.

    The scheduler's own recorded decision is what tells them apart, the
    same value the graph and the durable route table both read: SYNTHESIZE
    returns to the loop point (FIX-6), TERMINATE ends the run.

    Read from ``next_task`` alone this is wrong for the periodic branch's
    *stacked* form (``scheduling.policy.stack_companions``), where the
    primary keeps that field and the overview rides the pass's queue
    actions. A stacked firing read as terminal would buy the accuracy
    review and the knowledge-base calls, emit the run's 95% progress
    marker from the middle of a cycle, and publish a ``research_overview``
    the finished report would then carry -- so the queue actions are part
    of the question, exactly as they are for the routers.
    """
    if str(state.get("next_task") or "") == TaskType.SYNTHESIZE.value:
        return True
    actions = state.get("supervisor_queue_actions") or []
    return TaskType.SYNTHESIZE.value in stacked_task_values(actions)


async def synthesize_or_degrade(
    state: WorkflowState,
    synthesize: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run the overview synthesis, degrading it if the provider fails.

    Args:
        state: The node's workflow state.
        synthesize: The node's own synthesis, called once.

    Returns:
        The synthesis result, or the empty overview the report renders
        without.
    """
    if is_interim_firing(state):
        return await _interim_or_degrade(state, synthesize)
    return await run_or_degrade(
        state,
        synthesize,
        schema_name=_OVERVIEW_SCHEMA,
        fallback=_degraded_overview_result,
        lost=_LOST,
    )


async def _interim_or_degrade(
    state: WorkflowState,
    synthesize: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Draft the interim overview, or leave the next cycle without one.

    Deliberately records no degradation: ``degraded_nodes`` names a blank
    section of the finished report, and this firing writes no document --
    the terminal firing still can, so labelling the section here would
    mark an overview that came out fine.

    It shares the task's retry budget with the terminal firing, so it
    spends it the same way (``node_degradation.durable_retries_remain``):
    a retry declined here is one the run does not get back.
    """
    try:
        return await synthesize()
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as exc:
        if durable_retries_remain(state):
            raise
        logger.error(
            "Interim research overview could not reach the provider (%s); "
            "the next generate cycle runs without one",
            short_error_text(exc),
        )
        return {}


def _degraded_overview_result() -> dict[str, Any]:
    """The state delta a failed terminal synthesis publishes instead.

    The same empty ``research_overview`` the node already returns when the
    publication gates withhold every hypothesis, so the report renderer
    needs no new branch. No metrics delta: the requests that failed were
    already counted by ``llm.admission.call_budget.record_provider_request``,
    and this produced no overview to attribute a successful call to.
    """
    return {
        "research_overview": {},
        "messages": phase_message(
            "research_overview",
            "Research overview synthesis could not reach the provider; "
            "the report is published without it",
        ),
    }

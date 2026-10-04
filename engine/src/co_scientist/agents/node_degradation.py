"""Only exhausted durable retries may degrade optional science sections;
control-flow errors must propagate to the worker."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS, short_error_text
from co_scientist.progress import record_schema_degradation
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def durable_retries_remain(state: WorkflowState) -> bool:
    """Whether the durable task running this node can still retry it.

    Read, not computed: the flag is set per attempt on the durable path
    (``app.engine_tasks.restore``) and is absent everywhere else, so the
    falsy answer -- degrade -- is the one an unset state gets. It assumes
    the failure is retryable, which holds because the two failures the
    worker refuses to retry are ``TASK_CONTROL_FLOW_ERRORS``, re-raised
    before this is consulted.
    """
    return bool(state.get("durable_retries_remain"))


async def run_or_degrade(
    state: WorkflowState,
    synthesize: Callable[[], Awaitable[dict[str, Any]]],
    *,
    schema_name: str,
    fallback: Callable[[], dict[str, Any]],
    lost: str,
) -> dict[str, Any]:
    """Run one node's synthesis, degrading it if the provider fails.

    Args:
        state: The node's own workflow state, recorded into rather than
            the progress contextvar -- see ``record_schema_degradation``.
        synthesize: The node's synthesis, called once.
        schema_name: The node's key in ``_ENHANCEMENT_NODE_FALLBACKS``,
            which is also the label the report reads back as a degraded
            section.
        fallback: Builds the state delta to return instead, matching what
            the node returns when it has nothing to synthesize.
        lost: What the run gives up by degrading, named in the one ERROR
            line this emits -- the only record of it besides the report's
            own degraded-section label.

    Returns:
        The synthesis result, or ``fallback()`` when the provider failed
        with no durable attempt left to answer it.

    Raises:
        Exception: Re-raises ``TASK_CONTROL_FLOW_ERRORS`` unchanged, and
            any other failure while ``durable_retries_remain`` is set.
    """
    try:
        return await synthesize()
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as exc:
        if durable_retries_remain(state):
            raise
        # short_error_text, not exc_info: a litellm provider error appends
        # the whole completion to its message, and this log store's single
        # writer has already been starved by log volume once.
        # Worded for what this actually catches. The provider is the case
        # this exists for, but the guarded region also holds formatting,
        # validation and progress emission, so naming the provider here
        # would report a formatting bug as an outage; short_error_text
        # names the real cause.
        logger.error(
            "Node '%s' failed and published nothing (%s); %s",
            schema_name,
            short_error_text(exc),
            lost,
        )
        record_schema_degradation(schema_name, state)
        return fallback()

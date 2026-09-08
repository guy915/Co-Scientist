"""Degrading one node when its provider cannot be reached at all.

``llm_json._ENHANCEMENT_NODE_FALLBACKS`` already declares which nodes may
publish nothing rather than stop a run -- but only
``_handle_json_retries_exhausted`` serves those fallbacks, so they cover a
model that answers unparseably and not a provider that does not answer.
The other door out of ``call_llm_json`` is a raise: ``LLMTimeoutError``
(never retried, since a stalled provider will not answer the same request
faster) and a provider error on the final in-call attempt both leave by
it, carrying past the fallback table entirely.

That gap cost production run 49a509b0 its whole output. 146 tasks
committed, then the terminal ``research_overview`` node hit a provider
that stalled twice for 600s and then reported an upstream overload; its
three durable attempts spent, the task failed, and ``engine.finalize`` --
enqueued only ever as that node's ``None`` successor -- was never created,
so a run with 22 hypotheses and a full tournament published no report at
all.

This is the missing half: a node whose own synthesis is optional catches
an unreachable provider, records the degradation where the report can
read it, and returns the same empty result the parse path would have
served. The two errors the durable worker answers itself
(``TASK_CONTROL_FLOW_ERRORS``) are re-raised first, as at every other
degrade site -- a rate-limit park is not "this call failed", it is "no
call succeeds until the cap resets", and a spent call ceiling must stop
the run rather than be absorbed into a blank section.

Degrading is the *last* answer, not the first. A durable task carries
its own retry budget, and spending it is what recovers a provider that
comes back: extended run bc77950f met the same trouble as 49a509b0 and
published a full overview on its third durable attempt. So a provider
failure with a retry left propagates, exactly as it did before this
module existed, and only a failure with nothing left behind it degrades
-- the state flag ``durable_retries_remain`` is how the node learns
which it is, set per attempt by ``app.engine_tasks_restore`` from the
same ``attempt >= max_attempts`` formula
``app.task_worker_outcomes._is_terminal_failure`` uses. Its absence
means degrade, which is the whole graph/streaming path (no durable task,
so no retry to spend) and any caller that does not set it: a blank
section is a bad outcome, but re-raising where nothing retries is the
outage that produced no report at all.
"""

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
    (``app.engine_tasks_restore``) and is absent everywhere else, so the
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

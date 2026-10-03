"""Dispatch leased engine tasks with run-scoped credentials and call budgets."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app import store
from app.engine_tasks import runtime as engine_tasks_runtime
from app.engine_tasks.fanout import (
    execute_generation_strategy,
    execute_mature_reflection_item,
    execute_review_item,
    execute_verification_item,
)
from app.engine_tasks.fanout_aggregates import (
    execute_generation_aggregate,
    execute_mature_reflection_aggregate,
    execute_review_aggregate,
    execute_verification_aggregate,
)
from app.engine_tasks.finalize import execute_finalize as execute_finalize
from app.engine_tasks.inputs import enqueue_bootstrap as enqueue_bootstrap
from app.engine_tasks.inputs import (
    enqueue_scientist_continuation as enqueue_scientist_continuation,
)
from app.engine_tasks.inputs import execute_bootstrap as execute_bootstrap
from app.engine_tasks.node import execute_node_task as execute_node_task
from app.engine_tasks.outcome_refinement import (
    execute_outcome_refinement as execute_outcome_refinement,
)
from app.engine_tasks.ranking import (
    execute_ranking_finalize,
    execute_ranking_match,
)
from app.engine_tasks.support import BOOTSTRAP_TASK as BOOTSTRAP_TASK
from app.engine_tasks.support import ENGINE_TASK_PREFIX as ENGINE_TASK_PREFIX
from app.engine_tasks.support import (
    FINALIZE_TASK,
    GENERATION_AGGREGATE_TASK,
    GENERATION_STRATEGY_TASK,
    MATURE_REFLECTION_AGGREGATE_TASK,
    RANKING_FINALIZE_TASK,
    RANKING_MATCH_TASK,
    REVIEW_AGGREGATE_TASK,
    REVIEW_ITEM_TASK,
    VERIFICATION_AGGREGATE_TASK,
    VERIFICATION_ITEM_TASK,
)
from app.engine_tasks.support import (
    MATURE_REFLECTION_ITEM_TASK as MATURE_REFLECTION_ITEM_TASK,
)
from app.engine_tasks.support import NODE_TASK_PREFIX as NODE_TASK_PREFIX
from app.engine_tasks.support import (
    OUTCOME_REFINEMENT_TASK as OUTCOME_REFINEMENT_TASK,
)
from app.engine_tasks.support import SafetyHoldError as SafetyHoldError
from app.engine_tasks.support import SupersededTaskError as SupersededTaskError
from app.execution_policy import (
    CAMPAIGN,
    campaign_model_for_config,
    scoped_execution_policy,
)
from app.run_modes import resolved_run_config
from app.store import ScientificTask

_ENGINE_TASK_DISPATCH: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    BOOTSTRAP_TASK: execute_bootstrap,
    OUTCOME_REFINEMENT_TASK: execute_outcome_refinement,
    REVIEW_ITEM_TASK: execute_review_item,
    REVIEW_AGGREGATE_TASK: execute_review_aggregate,
    VERIFICATION_ITEM_TASK: execute_verification_item,
    VERIFICATION_AGGREGATE_TASK: execute_verification_aggregate,
    RANKING_MATCH_TASK: execute_ranking_match,
    RANKING_FINALIZE_TASK: execute_ranking_finalize,
    GENERATION_STRATEGY_TASK: execute_generation_strategy,
    GENERATION_AGGREGATE_TASK: execute_generation_aggregate,
    MATURE_REFLECTION_ITEM_TASK: execute_mature_reflection_item,
    MATURE_REFLECTION_AGGREGATE_TASK: execute_mature_reflection_aggregate,
    FINALIZE_TASK: execute_finalize,
}


async def _dispatch_engine_task(
    task: ScientificTask, *, db_path: str | None
) -> dict[str, Any]:
    """Route one engine task to its handler by task type."""
    handler = _ENGINE_TASK_DISPATCH.get(task.task_type)
    if handler is not None:
        return await handler(task, db_path=db_path)
    if task.task_type.startswith(NODE_TASK_PREFIX):
        return await execute_node_task(task, db_path=db_path)
    raise ValueError(f"unsupported engine task: {task.task_type}")


async def execute_engine_task(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Dispatch one leased engine task without executing unrelated nodes.

    A bring-your-own-key run's credential is scoped around the whole task
    -- into the app context (the app's own LLM calls) and the engine
    context (every agent completion) -- so it overrides the deployment
    credential for this task only, without touching any shared state.

    The run's LLM-call ceiling is scoped the same way, into the engine's
    ``llm.admission.call_budget`` context: every completion this task makes,
    however many retries or tool-loop turns deep, is counted against the
    run without any of that machinery needing to know the run id.
    """
    from co_scientist.llm import scoped_api_key, scoped_llm_call_budget

    from app.credentials import get_run_credential, scoped_byok

    run = store.get_run(task.run_id, db_path=db_path)
    if run is None:
        raise LookupError(f"run not found for task dispatch: {task.run_id}")
    credential = get_run_credential(task.run_id, db_path=db_path)
    if run.execution_policy == CAMPAIGN:
        campaign_model = campaign_model_for_config(run.config)
        if campaign_model is not None:
            # New campaign runs use their persisted server route even if an
            # older credential record was attached to the run.
            credential = None
    else:
        campaign_model = None
    ceiling = resolved_run_config(run.config).get("max_llm_calls")
    ceiling = int(ceiling) if isinstance(ceiling, int) else None
    with (
        engine_tasks_runtime.bound(engine_tasks_runtime.active()),
        scoped_byok(credential),
        scoped_api_key(credential.api_key if credential else None),
        scoped_llm_call_budget(task.run_id, ceiling),
        scoped_execution_policy(
            run.execution_policy, campaign_model_name=campaign_model
        ),
    ):
        return await _dispatch_engine_task(task, db_path=db_path)

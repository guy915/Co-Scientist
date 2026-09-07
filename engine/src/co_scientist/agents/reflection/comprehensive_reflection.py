"""Tool-grounded observation, full, simulation, and recurrent reviews.

Also runs the observation review for hypotheses that reached this node
without passing through the initial reflection node.
"""

import asyncio
import logging
from typing import Any, NamedTuple

from co_scientist.agents.reflection.deep_verification import (
    merge_retrieved_articles,
)
from co_scientist.agents.reflection.mature_reviews import (
    reviews_needed,
    store_mature_review_result,
)
from co_scientist.agents.reflection.observation_feedback import (
    apply_observation_result,
    store_indra_enrichment,
)
from co_scientist.agents.reflection.reflection import (
    _ReflectionContext,
    analyze_single_hypothesis,
)
from co_scientist.agents.reflection.review_evidence import (
    _evidence_key as _evidence_key,
)
from co_scientist.agents.reflection.review_evidence import (
    _hypothesis_search_queries as _hypothesis_search_queries,
)
from co_scientist.agents.reflection.review_evidence import (
    _review_evidence_for,
    _ReviewEvidence,
)
from co_scientist.agents.reflection.review_prompt_context import (
    _NO_EXECUTION_NOTE as _NO_EXECUTION_NOTE,
)
from co_scientist.agents.reflection.review_prompt_context import (
    _build_domain_context as _build_domain_context,
)
from co_scientist.agents.reflection.review_prompt_context import (
    _prompt_variables as _prompt_variables,
)
from co_scientist.agents.reflection.review_prompt_context import (
    _recurrent_review_suffix as _recurrent_review_suffix,
)
from co_scientist.agents.reflection.review_recheck import (
    RECHECK_REVIEW_TYPE,
    mark_recheck_issued,
    recheck_targets,
)
from co_scientist.agents.reflection.review_types import (
    ReviewType,
    prompt_name_for,
)
from co_scientist.agents.reflection.simulation_execution import (
    simulation_observations,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.models import (
    Article,
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


class _ReviewRun(NamedTuple):
    """One executed review, and what researching for it cost.

    Attributes:
        review_type: Which review ran.
        result: The review payload, or None when the call failed.
        ledger: The research this review's evidence came from, if any.
            Returned beside the result rather than inside it because the
            two are persisted by different writers -- the review by the
            hypothesis, the ledger by the run.
    """

    review_type: ReviewType
    result: dict[str, Any] | None
    ledger: dict[str, Any] | None


async def _run_review(
    state: WorkflowState,
    hypothesis: Hypothesis,
    review_type: ReviewType,
) -> _ReviewRun:
    """Execute one independently meaningful Reflection review call."""
    evidence = await _review_evidence_for(state, hypothesis, review_type)
    targeted_articles = evidence.articles
    observations = await _observations_for(state, hypothesis, review_type)
    prompt, schema = _build_review_prompt(
        state, hypothesis, review_type, targeted_articles, observations
    )
    try:
        result = await call_llm_json(
            prompt=prompt,
            spec=CompletionSpec(
                model_name=state["model_name"],
                max_tokens=EXTENDED_MAX_TOKENS,
                temperature=LOW_TEMPERATURE,
                json_schema=schema,
            ),
            options=LLMCallOptions(
                run_id=state.get("run_id"),
                prompt_name=f"reflection_{review_type.value}_{hypothesis.id}",
            ),
        )
    except Exception as exc:
        logger.error(
            "%s review failed for %s: %s", review_type.value, hypothesis.id, exc
        )
        return _ReviewRun(review_type, None, evidence.ledger)
    _record_review_provenance(
        result, evidence, targeted_articles, review_type, observations
    )
    return _ReviewRun(review_type, result, evidence.ledger)


def _record_review_provenance(
    result: dict[str, Any],
    evidence: "_ReviewEvidence",
    targeted_articles: list[Article],
    review_type: ReviewType,
    observations: str | None,
) -> None:
    """Records what the review was given, on the review itself.

    Each review persists the evidence it was handed, so the shared
    retrieval survives the checkpoint through both of their results
    rather than depending on the in-process cache outliving the task.

    Whether a simulation was executed is stamped here -- by the caller,
    which knows -- rather than asked of the model, which would make "did
    this verdict come from a run or from imagination" exactly as
    reliable as the rest of its output.

    Nothing reads either field yet: no report section, tab or later node
    consults them, so they are a record kept against the day a reader
    weighing a ``breaks_down`` needs to tell the two apart. Recorded
    anyway because the fact is only available here and cannot be
    reconstructed afterwards -- but that is the whole justification, so
    the observations are capped before they arrive
    (``simulation_execution.MAX_OBSERVATION_CHARS``): an uncapped
    write-only field rides into `enrichments` and from there into every
    checkpoint envelope.
    """
    result["retrieval_queries"] = evidence.queries
    result["retrieval_errors"] = evidence.errors
    result["retrieved_articles"] = [
        article.to_dict() for article in targeted_articles
    ]
    if review_type is not ReviewType.SIMULATION:
        return
    result["executed"] = observations is not None
    if observations is not None:
        result["execution_observations"] = observations


async def _observations_for(
    state: WorkflowState, hypothesis: Hypothesis, review_type: ReviewType
) -> str | None:
    """Runs a simulation of the mechanism, where this run may.

    Gated three ways, all of which have to hold. The caller has to have
    asked (the app asks on the deep tiers only, because this is a tool
    loop per hypothesis and that shape has been the largest line in a
    run's budget before); the review has to be the simulation; and the
    host has to be able to confine a command, which
    ``simulation_execution`` checks for itself. Anything short of all
    three is the review that was always here.
    """
    if review_type is not ReviewType.SIMULATION:
        return None
    if not state.get("enable_simulation_execution"):
        return None
    return await simulation_observations(state, hypothesis)


def _build_review_prompt(
    state: WorkflowState,
    hypothesis: Hypothesis,
    review_type: ReviewType,
    targeted_articles: list[Article],
    observations: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Builds the review prompt/schema, adding the recurrent-review preamble."""
    template_type = (
        ReviewType.FULL if review_type is ReviewType.RECURRENT else review_type
    )
    prompt, schema = load_prompt_with_schema(
        prompt_name_for(template_type),
        _prompt_variables(
            state, hypothesis, review_type, targeted_articles, observations
        ),
    )
    if review_type is ReviewType.RECURRENT:
        prompt = (
            "Perform a recurrent/tournament review. Adapt the full review to "
            "the accumulated reviews, Elo outcomes, recurring issues, and "
            "meta-review feedback below. Identify what changed since the "
            "earlier review.\n\n" + prompt
        )
    return prompt, schema


def _apply_review_results(
    hypothesis: Hypothesis,
    iteration: int,
    results: list[_ReviewRun],
) -> int:
    """Store each successful review result, reconciling dispositions.

    Storage goes through ``store_mature_review_result`` -- the write path
    shared with the durable fan-out -- so a fatal finding changes the
    review disposition on both execution paths (audit E1).

    Returns:
        The number of results that were not None.
    """
    successful = 0
    for run in results:
        if run.result is None:
            continue
        store_mature_review_result(
            hypothesis, run.review_type, run.result, iteration
        )
        successful += 1
    return successful


async def _review_hypothesis(
    state: WorkflowState, hypothesis: Hypothesis
) -> tuple[int, list[dict[str, Any]]]:
    """Apply maturity-appropriate reviews to one viable hypothesis.

    Returns:
        How many reviews succeeded, and the ledgers of any research
        their evidence came from -- one per hypothesis at most, since
        the reviews share a single retrieval.
    """
    iteration = int(state.get("current_iteration", 0))
    reviews = reviews_needed(hypothesis, iteration)
    if not reviews:
        return 0, []
    results = await asyncio.gather(
        *[
            _run_review(state, hypothesis, review_type)
            for review_type in reviews
        ]
    )
    successful = _apply_review_results(hypothesis, iteration, results)
    state["articles"] = merge_retrieved_articles(
        state.get("articles"), [run.result for run in results]
    )
    ledgers = [run.ledger for run in results if run.ledger is not None]
    return successful, _distinct(ledgers)


def _distinct(ledgers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the repeats two reviews sharing one retrieval produce."""
    unique: list[dict[str, Any]] = []
    for ledger in ledgers:
        if ledger not in unique:
            unique.append(ledger)
    return unique


async def _recheck_hypothesis(
    state: WorkflowState, hypothesis: Hypothesis
) -> int:
    """Give one blocked idea its single recurrent review for the run.

    The attempt is recorded before the call, so a failure spends it too
    (``review_recheck.mark_recheck_issued``). The result is stored
    through the same write path as every other mature review, so the
    disposition it changes is derived exactly as it is everywhere else.

    Returns:
        1 when the review produced a verdict, 0 when the call failed.
    """
    mark_recheck_issued(hypothesis)
    run = await _run_review(state, hypothesis, RECHECK_REVIEW_TYPE)
    if run.result is None:
        return 0
    store_mature_review_result(
        hypothesis,
        run.review_type,
        run.result,
        int(state.get("current_iteration", 0)),
    )
    return 1


async def _run_blocked_rechecks(
    state: WorkflowState, hypotheses: list[Hypothesis]
) -> int:
    """Re-examine the blocked ideas still owed a recheck, within budget.

    Returns:
        How many rechecks produced a verdict.
    """
    targets = recheck_targets(hypotheses)
    if not targets:
        return 0
    results = await asyncio.gather(
        *[_recheck_hypothesis(state, hypothesis) for hypothesis in targets]
    )
    return sum(results)


async def _run_missing_observation_reviews(
    state: WorkflowState, hypotheses: list[Hypothesis]
) -> int:
    """Apply observation review to ideas that bypass the initial node."""
    literature = state.get("articles_with_reasoning")
    if not literature:
        return 0
    pending = [h for h in hypotheses if not h.reflection_notes]
    if not pending:
        return 0
    context = _ReflectionContext(
        articles_with_reasoning=literature,
        model_name=state["model_name"],
        run_id=state.get("run_id"),
        tool_registry=state.get("tool_registry"),
        meta_review=state.get("meta_review"),
    )
    results = await asyncio.gather(
        *[
            analyze_single_hypothesis(
                hypothesis=hypothesis,
                hypothesis_index=index + 1,
                total_count=len(pending),
                context=context,
            )
            for index, hypothesis in enumerate(pending)
        ]
    )
    successful = 0
    for hypothesis, result in zip(pending, results, strict=True):
        if result is None:
            continue
        apply_observation_result(hypothesis, result)
        store_indra_enrichment(hypothesis, result)
        successful += 1
    return successful


async def comprehensive_reflection_node(state: WorkflowState) -> dict[str, Any]:
    """Run the mature cascade over viable ideas, and recheck blocked ones.

    The cascade selects on ``viable``, which is why the blocked ideas need
    their own arm: without it no deeper verdict can ever reach an idea the
    initial screen barred, and the derived disposition has nothing later to
    derive from (``review_recheck``).
    """
    hypotheses = state["hypotheses"]
    viable = [
        hypothesis
        for hypothesis in hypotheses
        if hypothesis.review_disposition == "viable"
    ]
    # The observation reviews, the full/simulation/recurrent review batch and
    # the blocked-idea rechecks have no data dependency on each other, so
    # overlap their LLM latency.
    observation_calls, reviewed, recheck_calls = await asyncio.gather(
        _run_missing_observation_reviews(state, viable),
        asyncio.gather(*[_review_hypothesis(state, h) for h in viable]),
        _run_blocked_rechecks(state, hypotheses),
    )
    calls = (
        observation_calls + sum(count for count, _ in reviewed) + recheck_calls
    )
    return {
        "hypotheses": hypotheses,
        "articles": state.get("articles") or [],
        "research_ledgers": [
            ledger for _, ledgers in reviewed for ledger in ledgers
        ],
        "metrics": create_metrics_update(deltas=MetricDeltas(llm_calls=calls)),
        "messages": phase_message(
            "reflection",
            f"Completed {calls} full, simulation, or recurrent reviews",
        ),
    }

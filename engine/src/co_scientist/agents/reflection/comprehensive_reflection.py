from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any, NamedTuple

from co_scientist.agents.reflection.deep_verification import (
    merge_retrieved_articles,
)
from co_scientist.agents.reflection.deep_verification_evidence import (
    EvidenceCaps,
    build_evidence_context,
    showable_articles,
)
from co_scientist.agents.reflection.reflection import (
    apply_observation_result,
    observe_hypothesis,
    store_indra_enrichment,
)
from co_scientist.agents.reflection.review_evidence import (
    _review_evidence_for,
    _ReviewEvidence,
)
from co_scientist.agents.reflection.review_gate import (
    RECHECK_REVIEW_TYPE,
    ReviewType,
    mark_recheck_issued,
    prompt_name_for,
    recheck_targets,
    reviews_needed,
    store_mature_review_result,
)
from co_scientist.agents.reflection.simulation_execution import (
    simulation_observations,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
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
from co_scientist.prompts import build_tool_instructions
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


# Public and private caps are separate so a full corpus cannot crowd out
# scientist context.
_MAX_REVIEW_ARTICLES = 12

_MAX_REVIEW_PRIVATE_SOURCES = 4


# An empty section implies execution observed nothing; explicitly distinguish
# never running.
_NO_EXECUTION_NOTE = (
    "No simulation was executed for this review. Step through the "
    "mechanism yourself."
)


def _prompt_variables(
    state: WorkflowState,
    hypothesis: Hypothesis,
    review_type: ReviewType,
    targeted_articles: list[Article] | None = None,
    observations: str | None = None,
) -> dict[str, str]:
    registry = state.get("tool_registry")
    tool_ids = registry.get_tools_for_workflow("reflection") if registry else []
    tool_instructions = build_tool_instructions(tool_ids, registry)
    hypothesis_text = hypothesis.text
    if review_type is ReviewType.RECURRENT:
        hypothesis_text += _recurrent_review_suffix(state, hypothesis)
    domain_context = _build_domain_context(state, targeted_articles)
    return {
        "research_goal": state["research_goal"],
        "hypothesis_text": hypothesis_text,
        "domain_context": (
            "Evidence available to this review:\n" + domain_context
            if domain_context
            else "No retrieved evidence is available to this review."
        ),
        "tool_instructions": tool_instructions,
        "execution_observations": (
            "A simulation of this mechanism was built and run. What it "
            "reported:\n\n" + observations
            if observations
            else _NO_EXECUTION_NOTE
        ),
    }


def _recurrent_review_suffix(
    state: WorkflowState, hypothesis: Hypothesis
) -> str:
    tournament = {
        "elo_rating": hypothesis.elo_rating,
        "match_count": hypothesis.total_matches,
        "reviews": [asdict(review) for review in hypothesis.reviews],
    }
    return (
        "\n\nRecurrent-review context from the growing tournament:\n"
        + json.dumps(tournament, indent=2)
        + "\n\nCross-agent feedback:\n"
        + _format_meta_review_context(state.get("meta_review"))
    )


def _build_domain_context(
    state: WorkflowState, targeted_articles: list[Article] | None
) -> str:
    """Source counts bound distinct voices; reviews weigh a few papers in
    depth."""
    evidence = [
        # Only corpus sources are marked analyzed; filter targeted sources
        # separately. The shared cap preserves corpus-first selection.
        *showable_articles(state.get("articles")),
        *showable_articles(targeted_articles, require_analyzed=False),
    ]
    return build_evidence_context(
        evidence,
        private_sources=state.get("context_enrichment_sources"),
        caps=EvidenceCaps(
            articles=_MAX_REVIEW_ARTICLES,
            private_sources=_MAX_REVIEW_PRIVATE_SOURCES,
        ),
        require_analyzed=False,
    )


class ReviewRun(NamedTuple):
    """The hypothesis writer persists the review; the run writer persists its
    ledger."""

    review_type: ReviewType
    result: dict[str, Any] | None
    ledger: dict[str, Any] | None


async def review_hypothesis(
    state: WorkflowState,
    hypothesis: Hypothesis,
    review_type: ReviewType,
) -> ReviewRun:
    """Bad answers fail this review; worker-owned parking and spend
    exhaustion propagate instead of spending item retries."""
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
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as exc:
        logger.error(
            "%s review failed for %s: %s", review_type.value, hypothesis.id, exc
        )
        return ReviewRun(review_type, None, evidence.ledger)
    _record_review_provenance(
        result, evidence, targeted_articles, review_type, observations
    )
    return ReviewRun(review_type, result, evidence.ledger)


def _record_review_provenance(
    result: dict[str, Any],
    evidence: _ReviewEvidence,
    targeted_articles: list[Article],
    review_type: ReviewType,
    observations: str | None,
) -> None:
    """Checkpoint retrieval provenance; the caller attests execution because
    model self-report is unreliable."""
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
    """A tool loop per hypothesis multiplies cost; require tier opt-in and
    confinement."""
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
    results: list[ReviewRun],
) -> int:
    """Use the durable write path so fatal findings reconcile identically."""
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
    iteration = int(state.get("current_iteration", 0))
    reviews = reviews_needed(hypothesis, iteration)
    if not reviews:
        return 0, []
    results = await asyncio.gather(
        *[
            review_hypothesis(state, hypothesis, review_type)
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
    unique: list[dict[str, Any]] = []
    for ledger in ledgers:
        if ledger not in unique:
            unique.append(ledger)
    return unique


_ReviewRun = ReviewRun


_run_review = review_hypothesis


async def _recheck_hypothesis(
    state: WorkflowState, hypothesis: Hypothesis
) -> int:
    """Issuing spends the one recheck even when the call fails."""
    mark_recheck_issued(hypothesis)
    run = await review_hypothesis(state, hypothesis, RECHECK_REVIEW_TYPE)
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
    literature = state.get("articles_with_reasoning")
    if not literature:
        return 0
    pending = [h for h in hypotheses if not h.reflection_notes]
    if not pending:
        return 0
    results = await asyncio.gather(
        *[
            observe_hypothesis(
                state,
                hypothesis,
                hypothesis_index=index + 1,
                total_count=len(pending),
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
    """Blocked ideas need their own recheck arm: the viable-only cascade
    cannot reach them to produce a deeper verdict."""
    hypotheses = state["hypotheses"]
    viable = [
        hypothesis
        for hypothesis in hypotheses
        if hypothesis.review_disposition == "viable"
    ]
    # These review arms have no data dependency; overlap their model latency.
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

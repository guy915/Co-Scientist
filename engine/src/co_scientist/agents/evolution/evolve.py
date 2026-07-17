"""Evolve node - refine top hypotheses with context-aware evolution."""

import asyncio
import json
import logging
from collections.abc import Coroutine
from typing import Any

from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
    select_operator,
)
from co_scientist.agents.evolution.evolve_context import (
    _find_most_similar as _find_most_similar,
)
from co_scientist.agents.evolution.evolve_context import (
    _hypothesis_texts as _hypothesis_texts,
)
from co_scientist.agents.evolution.evolve_context import (
    _sample_up_to as _sample_up_to,
)
from co_scientist.agents.evolution.evolve_context import (
    calculate_text_similarity as calculate_text_similarity,
)
from co_scientist.agents.evolution.evolve_context import (
    sample_context_hypotheses as sample_context_hypotheses,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _build_evolution_prompt as _build_evolution_prompt,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _build_evolution_variables as _build_evolution_variables,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _build_meta_review_insights as _build_meta_review_insights,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _build_review_feedback as _build_review_feedback,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _build_supervisor_guidance_text as _build_supervisor_guidance_text,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _format_diversity_instruction as _format_diversity_instruction,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _format_evolution_guidance_lines as _format_evolution_guidance_lines,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _format_iteration_strategy as _format_iteration_strategy,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _format_refinement_priorities as _format_refinement_priorities,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _log_items as _log_items,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _log_meta_review_debug as _log_meta_review_debug,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _log_truncated_items as _log_truncated_items,
)
from co_scientist.agents.evolution.evolve_results import (
    _apply_evolution_result as _apply_evolution_result,
)
from co_scientist.agents.evolution.evolve_results import (
    _apply_refined_hypothesis as _apply_refined_hypothesis,
)
from co_scientist.agents.evolution.evolve_results import (
    _build_evolve_state_delta as _build_evolve_state_delta,
)
from co_scientist.agents.evolution.evolve_results import (
    _collect_evolution_results as _collect_evolution_results,
)
from co_scientist.agents.evolution.evolve_results import (
    _extract_evolution_fields as _extract_evolution_fields,
)
from co_scientist.constants import (
    EVOLVE_MAX_TOKENS_CAP,
    EVOLVE_TOKENS_PER_CONTEXT_HYPOTHESIS,
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    PROGRESS_EVOLVE_COMPLETE,
    PROGRESS_EVOLVE_START,
    scaled_max_tokens,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import Hypothesis
from co_scientist.nodes.progress import emit_progress
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def _call_evolution_llm(
    full_prompt: str,
    schema: dict[str, Any] | None,
    other_hypotheses_texts: list[str],
    model_name: str,
    run_id: str | None,
    hypothesis_index: int | None,
) -> dict[str, Any]:
    """Calls the LLM to evolve a hypothesis from a prepared prompt.

    Args:
        full_prompt: The evolution prompt, including the diversity
            instruction.
        schema: JSON schema for the expected LLM response.
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15), used only to size the token budget.
        model_name: LLM model to use.
        run_id: Optional run ID for saving prompts.
        hypothesis_index: Optional index for naming saved prompts.

    Returns:
        Parsed JSON response from the LLM.
    """
    # Fixed token budget since we strategically sample max 15 context
    # hypotheses: 8000 base + 15 * 800 = 20,000 tokens at the cap, so the
    # budget is bounded for any pool size.
    evolve_max_tokens = scaled_max_tokens(
        EXTENDED_MAX_TOKENS,
        len(other_hypotheses_texts),
        per_item=EVOLVE_TOKENS_PER_CONTEXT_HYPOTHESIS,
        cap=EVOLVE_MAX_TOKENS_CAP,
    )

    logger.debug(
        "evolution token budget: %s (%s context hypotheses)",
        evolve_max_tokens,
        len(other_hypotheses_texts),
    )

    prompt_name = (
        f"evolve_{hypothesis_index}"
        if hypothesis_index is not None
        else "evolve"
    )

    # Call LLM to evolve hypothesis
    return await call_llm_json(
        prompt=full_prompt,
        model_name=model_name,
        max_tokens=evolve_max_tokens,
        temperature=HIGH_TEMPERATURE,
        json_schema=schema,
        max_attempts=7,  # increase retries for evolution (critical node)
        run_id=run_id,
        prompt_name=prompt_name,
        prompt_metadata={
            "hypothesis_index": hypothesis_index,
            "prompt_length_chars": len(full_prompt),
            "context_hypotheses_count": len(other_hypotheses_texts),
        },
    )


async def evolve_single_hypothesis(
    hypothesis: Hypothesis,
    other_hypotheses_texts: list[str],
    meta_review: dict[str, Any],
    model_name: str,
    removed_duplicates: list[str],
    supervisor_guidance: dict[str, Any] | None = None,
    articles_with_reasoning: str | None = None,
    run_id: str | None = None,
    hypothesis_index: int | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
    creation_iteration: int | None = None,
    operator: EvolutionOperator = EvolutionOperator.ENHANCEMENT,
    specialist_feedback: str = "",
) -> tuple[Hypothesis | None, dict[str, Any] | None]:
    """Evolve a single hypothesis into a new child with sampled context.

    This is the CRITICAL anti-duplicate strategy: we pass a subset of other
    hypotheses (top 5 by Elo + random samples) so the LLM knows what to
    avoid while keeping token budget manageable for large hypothesis pools.

    Args:
        hypothesis: Parent hypothesis to evolve (never mutated)
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15)
        meta_review: Meta-review insights for strategic guidance
        model_name: LLM model to use
        removed_duplicates: Previously removed duplicate texts to avoid
        supervisor_guidance: Optional supervisor guidance for evolution phase
        articles_with_reasoning: Optional literature review synthesis
            for context
        run_id: Optional run ID for saving prompts
        hypothesis_index: Optional index for naming saved prompts
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        run_setup_guidance: Optional durable setup guidance
        run_focus_guidance: Optional selected focus guidance
        creation_iteration: Workflow iteration producing any child
        operator: Distinct evolution strategy assigned to this task.
        specialist_feedback: Bounded prior-agent outputs for this parent.

    Returns:
        A ``(child, detail)`` pair on acceptance, or ``(None, None)`` when the
        refinement is rejected (no child created).
    """
    # The following call only logs meta-review signals (common
    # strengths/weaknesses, strategic recommendations, emerging themes)
    # for debugging; the same fields are formatted into the prompt itself
    # further below via _build_meta_review_insights.
    _log_meta_review_debug(meta_review)

    full_prompt, schema = _build_evolution_prompt(
        hypothesis=hypothesis,
        other_hypotheses_texts=other_hypotheses_texts,
        meta_review=meta_review,
        removed_duplicates=removed_duplicates,
        supervisor_guidance=supervisor_guidance,
        articles_with_reasoning=articles_with_reasoning,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
        operator=operator,
        specialist_feedback=specialist_feedback,
    )

    response = await _call_evolution_llm(
        full_prompt=full_prompt,
        schema=schema,
        other_hypotheses_texts=other_hypotheses_texts,
        model_name=model_name,
        run_id=run_id,
        hypothesis_index=hypothesis_index,
    )

    response["_evolution_operator"] = operator.value
    return _apply_evolution_result(
        hypothesis,
        response,
        other_hypotheses_texts,
        creation_iteration,
    )


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
    actual_count = len(top_k)

    logger.info("Evolving top %s hypotheses", actual_count)

    # Emit progress
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

    # Get previously removed duplicates
    # Flatten proximity.py's removed_duplicates dicts down to bare text;
    # used below to steer evolution away from recreating hypotheses that
    # were already pruned as duplicates in an earlier iteration.
    removed_duplicates = [
        dup.get("text", "") for dup in state.get("removed_duplicates", [])
    ]

    # Get supervisor guidance from state
    supervisor_guidance = state.get("supervisor_guidance")

    return top_k, removed_duplicates, supervisor_guidance


def _build_evolution_tasks(
    state: WorkflowState,
    top_k: list[Hypothesis],
    removed_duplicates: list[str],
    supervisor_guidance: dict[str, Any] | None,
) -> list[Coroutine[Any, Any, tuple[Hypothesis | None, dict[str, Any] | None]]]:
    """Builds the per-hypothesis evolution coroutines for this round.

    Evolve each hypothesis with strategically sampled context (PARALLEL):
    instead of including ALL other hypotheses, we sample a subset to
    control token budget.

    Args:
        state: Current workflow state.
        top_k: Hypotheses selected for evolution this round.
        removed_duplicates: Flattened previously removed duplicate texts.
        supervisor_guidance: Supervisor guidance for the evolution phase.

    Returns:
        List of evolve_single_hypothesis coroutines, one per hypothesis in
        top_k, ready to be awaited via asyncio.gather.
    """
    creation_iteration = state.get("current_iteration", 0)
    return [
        evolve_single_hypothesis(
            hypothesis=hyp,
            # Context is sampled from top_k (the peers also being evolved
            # this round), not the full hypothesis pool, so the diversity
            # check is scoped to the leaders a new child could resemble.
            other_hypotheses_texts=sample_context_hypotheses(
                all_hypotheses=top_k,
                exclude_hypothesis=hyp,
                max_context=15,  # cap at 15 for fixed token budget
            ),
            meta_review=state.get("meta_review", {}),
            model_name=state["model_name"],
            removed_duplicates=removed_duplicates,
            supervisor_guidance=supervisor_guidance,
            articles_with_reasoning=state.get("articles_with_reasoning"),
            run_id=state.get("run_id"),
            hypothesis_index=i,
            tool_registry=state.get("tool_registry"),
            run_setup_guidance=state.get("run_setup_guidance"),
            run_focus_guidance=state.get("run_focus_guidance"),
            creation_iteration=creation_iteration,
            operator=select_operator(i, creation_iteration),
            specialist_feedback=_specialist_feedback_for(state, hyp),
        )
        for i, hyp in enumerate(top_k)
    ]


def _specialist_feedback_for(
    state: WorkflowState, hypothesis: Hypothesis
) -> str:
    """Build a bounded, hypothesis-specific feedback ledger for evolution."""
    debates = [
        {
            "debate_id": item.get("debate_id"),
            "transcript": str(item.get("transcript") or "")[-2500:],
        }
        for item in state.get("debate_transcripts") or []
        if item.get("hypothesis_text") == hypothesis.text
    ][-2:]
    matches = []
    for item in state.get("tournament_matchups", []):
        side_a = item.get("hypothesis_a_id") == hypothesis.id
        side_b = item.get("hypothesis_b_id") == hypothesis.id
        if not side_a and not side_b:
            continue
        matches.append(
            {
                "outcome": (
                    "won" if item.get("winner_id") == hypothesis.id else "lost"
                ),
                "reasoning": item.get("reasoning") or item.get("reason"),
                "confidence": item.get("confidence"),
            }
        )
    neighbors = []
    for edge in (state.get("proximity_graph") or {}).get("edges", []):
        if edge.get("source") == hypothesis.id:
            neighbor = edge.get("target")
        elif edge.get("target") == hypothesis.id:
            neighbor = edge.get("source")
        else:
            continue
        neighbors.append(
            {
                "hypothesis_id": neighbor,
                "similarity": edge.get("similarity"),
                "cluster_id": edge.get("cluster_id"),
            }
        )
    verification = {
        "verdict": hypothesis.deep_verification_verdict,
        "probes": hypothesis.deep_verification_probes,
    }
    ledger = {
        "claim_evidence_gate": hypothesis.enrichments.get("claim_gate") or {},
        "debates": debates,
        "tournament": matches[-8:],
        "proximity_neighbors": neighbors[:8],
        "deep_verification": verification,
    }
    return json.dumps(ledger, indent=2)[:8000]


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


async def evolve_node(state: WorkflowState) -> dict[str, Any]:
    """Evolve top-k hypotheses with context-aware refinement.

    This node implements the most impactful anti-duplicate strategy:
    context-aware evolution where each LLM call sees a strategically
    sampled subset of its peers (top-Elo plus random, capped at 15) to
    prevent convergence without an unbounded token budget.

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields (evolved hypotheses)
    """
    hypotheses = state["hypotheses"]

    (
        top_k,
        removed_duplicates,
        supervisor_guidance,
    ) = await _prepare_evolution_round(state, hypotheses)

    evolution_tasks = _build_evolution_tasks(
        state, top_k, removed_duplicates, supervisor_guidance
    )
    results = await asyncio.gather(*evolution_tasks)

    # Unpack results: (child or None, evolution_detail or None). One attempt
    # per selected parent; rejected refinements contribute no child.
    children, evolution_details = _collect_evolution_results(results)

    return await _finalize_evolve_result(
        state, children, evolution_details, attempt_count=len(top_k)
    )

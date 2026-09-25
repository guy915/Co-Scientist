"""Evolve node - refine top hypotheses with context-aware evolution."""

import asyncio
import logging
import random
from collections.abc import Coroutine
from typing import Any

from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
    select_operators,
)
from co_scientist.agents.evolution.evolve_context import (
    combination_partners as combination_partners,
)
from co_scientist.agents.evolution.evolve_context import (
    find_nearest_peer as find_nearest_peer,
)
from co_scientist.agents.evolution.evolve_context import (
    sample_context_hypotheses as sample_context_hypotheses,
)
from co_scientist.agents.evolution.evolve_context import (
    token_coverage as token_coverage,
)
from co_scientist.agents.evolution.evolve_feedback import (
    _specialist_feedback_for as _specialist_feedback_for,
)
from co_scientist.agents.evolution.evolve_grounding import (
    enhancement_grounding_block,
    grounding_metrics_extra,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _build_evolution_prompt as _build_evolution_prompt,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _EvolutionContext as _EvolutionContext,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _EvolutionOperation as _EvolutionOperation,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _OutcomeRefinement as _OutcomeRefinement,
)
from co_scientist.agents.evolution.evolve_results import (
    _apply_evolution_result as _apply_evolution_result,
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
from co_scientist.agents.evolution.evolve_round import (
    _emit_evolution_start as _emit_evolution_start,
)
from co_scientist.agents.evolution.evolve_round import (
    _finalize_evolve_result as _finalize_evolve_result,
)
from co_scientist.agents.evolution.evolve_round import (
    _prepare_evolution_round as _prepare_evolution_round,
)
from co_scientist.agents.evolution.evolve_round import (
    _select_evolution_pool as _select_evolution_pool,
)
from co_scientist.agents.generation.citations import build_reference_index
from co_scientist.constants import (
    EVOLVE_MAX_TOKENS_CAP,
    EVOLVE_TOKENS_PER_CONTEXT_HYPOTHESIS,
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    scaled_max_tokens,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
    indexed_prompt_name,
)
from co_scientist.models import Hypothesis, rank_by_elo
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Shared default operation (frozen/immutable): the enhancement operator with
# no specialist feedback, used when a caller does not specify one.
_DEFAULT_EVOLUTION_OPERATION = _EvolutionOperation()

# Operators whose brief draws on designated top-ranked partners:
# combination merges them, inspiration borrows from them, and out-of-box
# reasons by analogy from them (published A.7's {hypotheses} input -- see
# evolution_operators.py's MP-8 note; without partners that prompt's
# central input renders empty).
_PARTNER_OPERATORS = frozenset(
    {
        EvolutionOperator.COMBINATION,
        EvolutionOperator.INSPIRATION,
        EvolutionOperator.OUT_OF_BOX,
    }
)


def _evolve_token_budget(other_hypotheses_texts: list[str]) -> int:
    """Computes and logs the evolution call's token budget.

    Fixed token budget since we strategically sample max 15 context
    hypotheses: 8000 base + 15 * 800 = 20,000 tokens at the cap, so the
    budget is bounded for any pool size.
    """
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
    return evolve_max_tokens


async def _call_evolution_llm(
    full_prompt: str,
    schema: dict[str, Any] | None,
    other_hypotheses_texts: list[str],
    context: _EvolutionContext,
    hypothesis_index: int | None,
) -> dict[str, Any]:
    """Calls the LLM to evolve a hypothesis from a prepared prompt.

    Args:
        full_prompt: The evolution prompt, including the diversity
            instruction.
        schema: JSON schema for the expected LLM response.
        other_hypotheses_texts: Sampled subset of other hypotheses (max
            15), used only to size the token budget.
        context: Run-level evolution context (model name, run id).
        hypothesis_index: Optional index for naming saved prompts.

    Returns:
        Parsed JSON response from the LLM.
    """
    evolve_max_tokens = _evolve_token_budget(other_hypotheses_texts)
    prompt_name = indexed_prompt_name("evolve", hypothesis_index)
    return await call_llm_json(
        prompt=full_prompt,
        spec=CompletionSpec(
            model_name=context.model_name,
            max_tokens=evolve_max_tokens,
            temperature=HIGH_TEMPERATURE,
            json_schema=schema,
        ),
        max_attempts=7,
        options=LLMCallOptions(
            prompt_name=prompt_name,
            prompt_metadata={
                "hypothesis_index": hypothesis_index,
                "prompt_length_chars": len(full_prompt),
                "context_hypotheses_count": len(other_hypotheses_texts),
            },
        ),
    )


async def evolve_single_hypothesis(
    hypothesis: Hypothesis,
    other_hypotheses: list[Hypothesis],
    context: _EvolutionContext,
    hypothesis_index: int | None = None,
    operation: _EvolutionOperation = _DEFAULT_EVOLUTION_OPERATION,
) -> tuple[Hypothesis | None, dict[str, Any] | None]:
    """Evolve a single hypothesis into a new child with sampled context.

    ``context`` bundles the run/round-invariant inputs (model, meta-review,
    removed duplicates, guidance, and -- for the enhancement operator's
    live grounding retrieval -- the workflow state) and ``operation`` the
    per-hypothesis operator and specialist feedback. Returns
    ``(child, detail)`` on acceptance, else ``(None, None)``.

    Args:
        hypothesis: The hypothesis to evolve.
        other_hypotheses: Sampled pool peers; their texts form the
            anti-convergence context and the near-duplicate rejection set.
        context: Run-level evolution context.
        hypothesis_index: Optional index for naming saved prompts.
        operation: The operator and its inputs for this hypothesis.
    """
    response = await _evolve_llm_response(
        hypothesis,
        other_hypotheses,
        context,
        hypothesis_index,
        operation,
    )
    validation_hypotheses = (
        list(operation.outcome_refinement.validation_hypotheses)
        if operation.outcome_refinement is not None
        else other_hypotheses
    )
    return _apply_evolution_result(
        hypothesis,
        response,
        validation_hypotheses,
        context,
        operation,
    )


async def evolve_single_hypothesis_from_outcome(
    hypothesis: Hypothesis,
    context: _EvolutionContext,
    outcome_context: str,
    validation_hypotheses: list[Hypothesis],
) -> tuple[Hypothesis | None, dict[str, Any] | None]:
    """Refine one parent with a recorded outcome and its sibling reject set.

    Args:
        hypothesis: The only parent this targeted action may evolve.
        context: Run context with unrelated prompt content removed.
        outcome_context: Bounded, untrusted outcome snapshot for the prompt.
        validation_hypotheses: Siblings used only to reject duplicate children.

    Returns:
        The accepted child and detail, or ``(None, None)`` when rejected.
    """
    operation = _EvolutionOperation(
        outcome_refinement=_OutcomeRefinement(
            context=outcome_context,
            validation_hypotheses=tuple(validation_hypotheses),
        )
    )
    return await evolve_single_hypothesis(
        hypothesis,
        [],
        context,
        operation=operation,
    )


async def _evolve_llm_response(
    hypothesis: Hypothesis,
    other_hypotheses: list[Hypothesis],
    context: _EvolutionContext,
    hypothesis_index: int | None,
    operation: _EvolutionOperation,
) -> dict[str, Any]:
    """Builds the prompt, calls the evolution LLM, tags the operator used."""
    other_hypotheses_texts = [peer.text for peer in other_hypotheses]
    grounding = ""
    if (
        operation.operator is EvolutionOperator.ENHANCEMENT
        and context.state is not None
    ):
        grounding = await enhancement_grounding_block(context.state, hypothesis)
    full_prompt, schema = _build_evolution_prompt(
        hypothesis,
        other_hypotheses_texts,
        context,
        operation,
        grounding,
    )
    response = await _call_evolution_llm(
        full_prompt,
        schema,
        other_hypotheses_texts,
        context,
        hypothesis_index,
    )
    return {**response, "_evolution_operator": operation.operator.value}


def _context_sample_seed(
    context: _EvolutionContext, hypothesis: Hypothesis
) -> str:
    """Run-scoped seed for one parent's diversity-context sample.

    Threaded from the run id so a round's sampling is reproducible (and so
    concurrent runs draw from their own RNG rather than perturbing a shared
    global one). The hypothesis id keeps each parent's sample independent;
    ids are stable across a durable task's retries, so a re-executed task
    samples the same context it did before.
    """
    return f"{context.run_id or 'evolution'}:context:{hypothesis.id}"


def _sampled_context(
    state: WorkflowState, context: _EvolutionContext, hyp: Hypothesis
) -> list[Hypothesis]:
    """Samples the near-duplicate rejection context for one parent.

    Sampled from the whole pool, not just the top_k being evolved this
    round. These hypotheses are the near-duplicate *rejection* set (see
    _apply_evolution_result), so anything missing from them is something
    a child is free to re-derive: scoping to top_k left the guard blind
    to most of the run's ideas, and a child duplicating one of them
    passed here only for proximity to archive it later. A run that ends
    with a dozen near-identical ideas has usually been through exactly
    that.

    It also makes sample_context_hypotheses do the job it was written
    for. Against top_k the pool never exceeded max_context, so the
    top-5-by-Elo-plus-random sampling never ran and the cap never bound;
    against the full pool it does both.
    """
    return sample_context_hypotheses(
        all_hypotheses=state["hypotheses"],
        exclude_hypothesis=hyp,
        max_context=15,  # cap at 15 for fixed token budget
        ranked_hypotheses=list(context.ranked_hypotheses),
        rng=random.Random(_context_sample_seed(context, hyp)),
    )


async def _evolve_or_none(
    hypothesis: Hypothesis,
    other_hypotheses: list[Hypothesis],
    context: _EvolutionContext,
    hypothesis_index: int,
    operation: _EvolutionOperation,
) -> tuple[Hypothesis | None, dict[str, Any] | None]:
    """Evolve one parent, isolating any failure to that parent.

    Returns ``(None, None)`` instead of raising, which is already the
    node's vocabulary for "this parent produced no child" (an unchanged or
    near-duplicate refinement). Letting the exception out of the
    ``asyncio.gather`` in ``evolve_node`` instead cancelled every sibling
    refinement mid-call and aborted the round, discarding children that
    had already been generated and paid for; on the durable path the whole
    evolution task then failed and re-ran every parent from scratch.
    """
    try:
        return await evolve_single_hypothesis(
            hypothesis=hypothesis,
            other_hypotheses=other_hypotheses,
            context=context,
            hypothesis_index=hypothesis_index,
            operation=operation,
        )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        logger.error(
            "Evolution failed for hypothesis %s: %s", hypothesis_index, e
        )
        return None, None


def _build_single_evolution_task(
    state: WorkflowState,
    i: int,
    hyp: Hypothesis,
    context: _EvolutionContext,
    operator: EvolutionOperator,
) -> Coroutine[Any, Any, tuple[Hypothesis | None, dict[str, Any] | None]]:
    """Builds the per-parent evolution coroutine for one pool member."""
    partners = (
        tuple(combination_partners(context.ranked_hypotheses, hyp))
        if operator in _PARTNER_OPERATORS
        else ()
    )
    operation = _EvolutionOperation(
        operator=operator,
        specialist_feedback=_specialist_feedback_for(state, hyp),
        partners=partners,
    )
    return _evolve_or_none(
        hyp,
        _sampled_context(state, context, hyp),
        context,
        i,
        operation,
    )


def _build_evolution_context(
    state: WorkflowState,
    removed_duplicates: list[str],
    supervisor_guidance: dict[str, Any] | None,
) -> _EvolutionContext:
    """Bundles this evolution round's run-invariant inputs from state."""
    return _EvolutionContext(
        model_name=state["model_name"],
        meta_review=state.get("meta_review", {}),
        removed_duplicates=removed_duplicates,
        creation_iteration=state.get("current_iteration", 0),
        supervisor_guidance=supervisor_guidance,
        articles_with_reasoning=state.get("articles_with_reasoning"),
        run_id=state.get("run_id"),
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
        proximity_graph=state.get("proximity_graph"),
        ranked_hypotheses=tuple(rank_by_elo(state["hypotheses"])),
        state=state,
        # Built once for the round, not once per parent: it is derived
        # from state, so every refinement in the round cites the same
        # [C*] keys and every child resolves against the same table.
        reference_index=build_reference_index(
            state.get("articles"), state.get("context_enrichment_sources")
        ),
    )


def _build_evolution_tasks(
    state: WorkflowState,
    top_k: list[Hypothesis],
    removed_duplicates: list[str],
    supervisor_guidance: dict[str, Any] | None,
    operators: list[EvolutionOperator],
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
        operators: The per-parent operator assignment for this round (one
            per member of top_k, in order).

    Returns:
        List of evolve_single_hypothesis coroutines, one per hypothesis in
        top_k, ready to be awaited via asyncio.gather.
    """
    context = _build_evolution_context(
        state, removed_duplicates, supervisor_guidance
    )
    # The pool is ranked once for the whole round in the context (see
    # _build_evolution_context): every member samples its context from the
    # same pool minus itself, and dropping one member cannot reorder the rest.
    return [
        _build_single_evolution_task(state, i, hyp, context, operator)
        for i, (hyp, operator) in enumerate(zip(top_k, operators, strict=True))
    ]


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

    # One seeded operator assignment for the round: every parent gets an
    # explicit operator and the portfolio gains coverage across rounds
    # whatever the tier's parent count.
    operators = select_operators(
        len(top_k),
        state.get("current_iteration", 0),
        state.get("run_id") or "evolution",
    )

    evolution_tasks = _build_evolution_tasks(
        state, top_k, removed_duplicates, supervisor_guidance, operators
    )
    results = await asyncio.gather(*evolution_tasks)

    # Unpack results: (child or None, evolution_detail or None). One attempt
    # per selected parent; rejected refinements contribute no child.
    children, evolution_details = _collect_evolution_results(results)

    return await _finalize_evolve_result(
        state,
        children,
        evolution_details,
        attempt_count=len(top_k),
        extra_llm_calls=grounding_metrics_extra(
            state, [operator.value for operator in operators]
        ),
    )

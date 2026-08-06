"""Prompt assembly and meta-review logging for the Evolve node."""

import dataclasses
import json
import logging
from typing import Any

from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
    operator_instruction,
)
from co_scientist.agents.evolution.evolve_context import (
    _format_partner_context as _format_partner_context,
)
from co_scientist.agents.evolution.evolve_grounding import (
    not_applicable_block,
)
from co_scientist.agents.generation.assumption_feedback import (
    build_falsified_assumptions_section,
)
from co_scientist.constants import truncate
from co_scientist.models import Hypothesis
from co_scientist.prompts import (
    _format_bullet_list,
    _format_run_guidance,
    _get_domain_variables,
    format_lab_constraints_section,
    load_prompt_with_schema,
)
from co_scientist.prompts._common import _csv_value
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _EvolutionContext:
    """Run/round-invariant inputs threaded through one evolution round.

    Bundles the model, prior-round signals (meta-review, removed
    duplicates), and the guidance/tool context every evolved hypothesis
    shares. ``creation_iteration``, ``model_name``, and ``run_id`` are
    unused by prompt assembly but ride along so the LLM call and child
    construction can read them from the same context. ``state`` and
    ``ranked_hypotheses`` are likewise round-invariant (one node run reads
    the state once, and dropping one parent cannot reorder the ranking),
    and ride here so per-hypothesis helpers keep five or fewer arguments.
    """

    model_name: str
    meta_review: dict[str, Any]
    removed_duplicates: list[str]
    creation_iteration: int | None = None
    supervisor_guidance: dict[str, Any] | None = None
    articles_with_reasoning: str | None = None
    run_id: str | None = None
    tool_registry: Any | None = None
    run_setup_guidance: str | None = None
    run_focus_guidance: str | None = None
    proximity_graph: dict[str, Any] | None = None
    ranked_hypotheses: tuple[Hypothesis, ...] = ()
    state: WorkflowState | None = None


@dataclasses.dataclass(frozen=True)
class _EvolutionOperation:
    """The per-hypothesis evolution operator and its inputs.

    ``partners`` are the top-ranked peers a COMBINATION task merges with or
    an INSPIRATION task borrows from; other operators leave it empty. They
    ride with the operation because both the prompt section that offers them
    and the lineage resolution that records them read the same list.
    """

    operator: EvolutionOperator = EvolutionOperator.ENHANCEMENT
    specialist_feedback: str = ""
    partners: tuple[Hypothesis, ...] = ()


def _log_debug_items(
    label: str, items: list[str], *, truncate_items: bool = False
) -> None:
    """Logs a debug header and up to the first 3 items.

    Args:
        label: Human-readable field label (e.g. "common Strengths").
        items: Meta-review items to log.
        truncate_items: Truncate each item to 100 chars when set.
    """
    if not items:
        return
    logger.debug("%s (%s):", label, len(items))
    for item in items[:3]:  # Show first 3
        logger.debug("- %s", truncate(item, 100) if truncate_items else item)


def _log_meta_review_debug(meta_review: dict[str, Any]) -> None:
    """Logs meta-review signals used during evolution, for debugging.

    The same fields are also formatted into the prompt itself (see
    _build_meta_review_insights); this only logs them for visibility.

    Args:
        meta_review: Meta-review insights for strategic guidance.
    """
    logger.debug("\n=== evolve single hypothesis ===")
    logger.debug("using meta review for evolution")

    _log_debug_items(
        "common Strengths",
        meta_review.get("common_strengths", []),
        truncate_items=True,
    )
    _log_debug_items(
        "common Weaknesses",
        meta_review.get("common_weaknesses", []),
        truncate_items=True,
    )
    _log_debug_items(
        "strategic Recommendations",
        meta_review.get("strategic_recommendations", []),
    )
    _log_debug_items("emerging Themes", meta_review.get("emerging_themes", []))


def _build_review_feedback(hypothesis: Hypothesis) -> str:
    """Formats a hypothesis's latest review as evolution-prompt context.

    Surfaces the most recent review's scores/feedback as context so the
    LLM addresses concrete critique rather than refining blind.

    Args:
        hypothesis: Hypothesis being evolved.

    Returns:
        JSON-formatted review feedback, or an empty string if the
        hypothesis has no reviews yet.
    """
    summary = hypothesis.review_summary()
    if summary is None:
        return ""
    return json.dumps(summary, indent=2)


def _build_meta_review_insights(meta_review: dict[str, Any]) -> str:
    """Formats meta-review insights for the evolution prompt.

    Args:
        meta_review: Meta-review insights for strategic guidance.

    Returns:
        JSON-formatted meta-review insights.
    """
    return json.dumps(
        {
            "common_strengths": meta_review.get("common_strengths", []),
            "common_weaknesses": meta_review.get("common_weaknesses", []),
            "strategic_recommendations": meta_review.get(
                "strategic_recommendations", []
            ),
            "emerging_themes": meta_review.get("emerging_themes", []),
        },
        indent=2,
    )


def _format_refinement_priorities(
    evolution_phase: dict[str, Any],
) -> str | None:
    """Format the refinement-priorities guidance line, if present."""
    priorities = evolution_phase.get("refinement_priorities")
    if not priorities:
        return None
    return f"**Refinement Priorities:** {_csv_value(priorities)}\n"


def _format_iteration_strategy(evolution_phase: dict[str, Any]) -> str | None:
    """Format the iteration-strategy guidance line, if present."""
    strategy = evolution_phase.get("iteration_strategy")
    if not strategy:
        return None
    return f"**Iteration Strategy:** {strategy}\n"


def _format_evolution_guidance_lines(
    evolution_phase: dict[str, Any],
) -> list[str]:
    """Format the non-empty evolution-phase guidance lines."""
    lines = []
    for formatter in (
        _format_refinement_priorities,
        _format_iteration_strategy,
    ):
        section = formatter(evolution_phase)
        if section:
            lines.append(section)
    return lines


def _build_supervisor_guidance_text(
    supervisor_guidance: dict[str, Any] | None,
) -> str:
    """Formats the evolution-phase slice of supervisor guidance.

    Only the evolution_phase slice of the supervisor's workflow_plan is
    relevant here; other phases (e.g. generation) are ignored.

    Args:
        supervisor_guidance: Optional supervisor guidance for evolution phase.

    Returns:
        Formatted supervisor guidance text, or an empty string if there is
        no evolution-phase guidance to surface.
    """
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""
    workflow_plan = supervisor_guidance.get("workflow_plan", {})
    evolution_phase = workflow_plan.get("evolution_phase", {})
    if not evolution_phase:
        return ""

    guidance_sections = ["## Supervisor Guidance for Evolution\n"]
    guidance_sections.extend(_format_evolution_guidance_lines(evolution_phase))
    guidance_sections.append(
        "\nUse this guidance to align your refinement with the research plan.\n"
    )
    return "".join(guidance_sections)


_DIVERSITY_INSTRUCTION_TEMPLATE = """

## CRITICAL: Preserve Diversity

**Other hypotheses in the active pool:**
{other_hyps}

**Previously removed duplicates (DO NOT recreate these):**
{removed_dups}

**CRITICAL REQUIREMENT:** Your refined hypothesis MUST remain DISTINCT from:
1. All other hypotheses listed above
2. Previously removed duplicates

DO NOT:
- Use the same biomarker/methodology as other hypotheses
- Make only trivial wording changes
- Converge toward similar concepts

DO:
- Maintain the unique aspects of this hypothesis
- Explore different mechanisms or approaches
- Preserve conceptual diversity
"""

# Combination merges the parent with its designated partners, so the generic
# "remain distinct from every other hypothesis" requirement would contradict
# the operator itself: a faithful combination necessarily shares mechanisms
# with the partners it merges. The directive keeps its anti-convergence force
# against every idea that is NOT a partner and against recreating pruned
# duplicates.
_COMBINATION_DIVERSITY_TEMPLATE = """

## CRITICAL: Preserve Diversity

**Other hypotheses in the active pool:**
{other_hyps}

**Previously removed duplicates (DO NOT recreate these):**
{removed_dups}

**CRITICAL REQUIREMENT:** Your combination MUST synthesize the designated
combination partners with the parent; sharing mechanisms with those partners
is the point of this operator. The result must still:
1. Remain DISTINCT from every other hypothesis listed above that is not a
   designated partner
2. NOT recreate any previously removed duplicate

DO NOT make only trivial wording changes; the synthesis must resolve the
parents' weaknesses, not restate them.
"""


def _format_diversity_instruction(
    other_hypotheses_texts: list[str],
    removed_duplicates: list[str],
    operator: EvolutionOperator = EvolutionOperator.ENHANCEMENT,
) -> str:
    """Builds the anti-convergence directive appended to the evolution prompt.

    Appended after the schema-driven prompt (not merged into its
    variables) as an explicit anti-convergence directive: without this,
    independently evolved hypotheses tend to drift toward the same winning
    idea.

    Args:
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15).
        removed_duplicates: Previously removed duplicate texts to avoid.
        operator: The operator this refinement executes; combination gets a
            directive that exempts its designated partners (a requirement to
            stay distinct from them would contradict the merge).

    Returns:
        Diversity-instruction text to append to the evolution prompt.
    """
    # Each item is capped at 200 chars -- enough for the LLM to recognize
    # overlap without materially growing the prompt. The full-field partner
    # context lives in the partner section; these bullets are only the
    # anti-convergence foil.
    other_hyps_formatted = _format_bullet_list(
        other_hypotheses_texts, truncate_chars=200
    )
    # Only the 5 most recently removed duplicates are shown, keeping this
    # section bounded regardless of how many duplicates accumulate over a
    # run.
    removed_dups_formatted = _format_bullet_list(
        removed_duplicates[-5:], truncate_chars=200
    )

    template = (
        _COMBINATION_DIVERSITY_TEMPLATE
        if operator is EvolutionOperator.COMBINATION
        else _DIVERSITY_INSTRUCTION_TEMPLATE
    )
    return template.format(
        other_hyps=other_hyps_formatted,
        removed_dups=removed_dups_formatted,
    )


def _build_evolution_variables(
    hypothesis: Hypothesis,
    context: _EvolutionContext,
    operation: _EvolutionOperation,
    grounding_evidence: str,
) -> dict[str, Any]:
    """Builds the template variables for the "evolution" prompt.

    Unlike most nodes, evolve has no dedicated get_evolution_prompt()
    wrapper in prompts.py, so this helper pulls in the normally-internal
    run-guidance/domain helpers itself to build the same variables those
    wrappers assemble. All fields feed the identically-named "evolution"
    prompt template variables (specialist_feedback and articles_with_reasoning
    fall back to a placeholder / empty string when unset).

    Args:
        hypothesis: The hypothesis being evolved.
        context: Run-level evolution context.
        operation: The per-hypothesis operator and partners.
        grounding_evidence: The enhancement operator's targeted-evidence
            block; other operators pass the not-applicable placeholder.

    Returns:
        Template variables for the "evolution" prompt.
    """
    variables = _base_evolution_variables(
        hypothesis, context.meta_review, context.supervisor_guidance
    )
    variables["run_guidance"] = _format_run_guidance(
        context.run_setup_guidance, context.run_focus_guidance
    )
    variables["articles_with_reasoning"] = context.articles_with_reasoning or ""
    variables["enhancement_grounding"] = grounding_evidence
    variables["partner_context"] = _format_partner_context(
        operation.partners, operation.operator
    )
    variables["falsified_assumptions_section"] = _falsified_assumptions_section(
        context
    )
    variables["lab_constraints_section"] = _lab_constraints_section(context)
    variables["specialist_feedback"] = (
        operation.specialist_feedback or "No prior specialist feedback."
    )
    variables.update(_get_domain_variables(context.tool_registry))
    return variables


def _lab_constraints_section(context: _EvolutionContext) -> str:
    """Renders the scientist's lab constraints for this refinement (K5).

    Feasibility improvements must respect what the scientist's lab can
    actually do. The block renders its own header and is empty when the
    run carries no lab constraints, which keeps the prompt byte-identical
    to its pre-K5 shape.
    """
    if context.state is None:
        return ""
    return format_lab_constraints_section(context.state.get("lab_constraints"))


def _falsified_assumptions_section(context: _EvolutionContext) -> str:
    """Renders the run's verified-wrong assumptions for this refinement.

    Feeds audit K9's evolution half: the assumptions deep verification
    already falsified here, so a refinement does not rebuild on the same
    broken ground. The block renders its own header and is empty until a
    hypothesis has been weakened. The specific parent's own probes already
    reach the prompt through the specialist-feedback ledger, so this adds
    only the run-wide record.
    """
    if context.state is None:
        return ""
    return build_falsified_assumptions_section(context.state.get("hypotheses"))


def _base_evolution_variables(
    hypothesis: Hypothesis,
    meta_review: dict[str, Any],
    supervisor_guidance: dict[str, Any] | None,
) -> dict[str, Any]:
    """Builds the hypothesis/meta-review/supervisor-guidance variables."""
    return {
        "original_hypothesis": hypothesis.text,
        "review_feedback": _build_review_feedback(hypothesis),
        "meta_review_insights": _build_meta_review_insights(meta_review),
        "supervisor_guidance": _build_supervisor_guidance_text(
            supervisor_guidance
        ),
    }


def _format_operator_section(operator: EvolutionOperator) -> str:
    """Format the required-evolution-operator section of the prompt."""
    return (
        "\n\n## Required Evolution Operator\n"
        f"**Operator:** {operator.value}\n"
        f"{operator_instruction(operator)}\n"
        "Record how this operator changed the proposal in the refinement "
        "summary.\n"
    )


def _build_evolution_prompt(
    hypothesis: Hypothesis,
    other_hypotheses_texts: list[str],
    context: _EvolutionContext,
    operation: _EvolutionOperation,
    grounding_evidence: str = "",
) -> tuple[str, dict[str, Any] | None]:
    """Assembles the full evolution prompt (and schema) for one hypothesis.

    Args:
        hypothesis: The hypothesis being evolved.
        other_hypotheses_texts: Sampled peer texts for the anti-convergence
            directive.
        context: Run-level evolution context.
        operation: The per-hypothesis operator and partners.
        grounding_evidence: The enhancement operator's targeted-evidence
            block; empty (or absent) renders the not-applicable placeholder.

    Returns:
        Tuple of (full prompt text with diversity instruction appended,
        JSON schema for the expected LLM response).
    """
    variables = _build_evolution_variables(
        hypothesis,
        context,
        operation,
        grounding_evidence or not_applicable_block(),
    )
    prompt, schema = load_prompt_with_schema("evolution", variables)

    full_prompt = (
        prompt
        + _format_operator_section(operation.operator)
        + _format_diversity_instruction(
            other_hypotheses_texts,
            context.removed_duplicates,
            operation.operator,
        )
    )
    return full_prompt, schema

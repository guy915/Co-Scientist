"""Render the selected evolution operator's published or local template."""

from typing import Any

from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
    operator_instruction,
    operator_template,
)
from co_scientist.prompts import load_prompt_with_schema


def _format_operator_section(operator: EvolutionOperator) -> str:
    """Format the required-evolution-operator section of the prompt."""
    return (
        "\n\n## Required Evolution Operator\n"
        f"**Operator:** {operator.value}\n"
        f"{operator_instruction(operator)}\n"
        "Record how this operator changed the proposal in the refinement "
        "summary.\n"
    )


def render_operator_template(
    operator: EvolutionOperator,
    variables: dict[str, Any],
    diversity: str,
) -> tuple[str, dict[str, Any] | None, str, bool]:
    """Render template and return sections that remain outside its slots."""
    template = operator_template(operator)
    has_template_diversity_slot = template != "evolution"
    if has_template_diversity_slot:
        # Published templates contain their own role and terminal answer cue.
        variables["diversity_section"] = diversity
        prompt, schema = load_prompt_with_schema(template, variables)
        operator_section = ""
    else:
        prompt, schema = load_prompt_with_schema(template, variables)
        operator_section = _format_operator_section(operator)
    return prompt, schema, operator_section, has_template_diversity_slot

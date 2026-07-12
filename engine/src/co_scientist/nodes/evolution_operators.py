"""Distinct, disclosed hypothesis-evolution operators and instructions."""

from __future__ import annotations

import enum


class EvolutionOperator(str, enum.Enum):
    """Published evolution strategies represented as executable operators."""

    ENHANCEMENT = "enhancement"
    SIMPLIFICATION = "simplification"
    COMBINATION = "combination"
    ANALOGY = "analogy"
    OUT_OF_BOX = "out_of_box"


_INSTRUCTIONS = {
    EvolutionOperator.ENHANCEMENT: (
        "Strengthen grounding, coherence, practicality, feasibility, and "
        "falsifiability while retaining the scientifically valuable premise."
    ),
    EvolutionOperator.SIMPLIFICATION: (
        "Remove unnecessary assumptions and experimental complexity. Produce "
        "the smallest mechanism and decisive experiment that can test it."
    ),
    EvolutionOperator.COMBINATION: (
        "Synthesize complementary mechanisms or experiments from the parent "
        "and relevant peer hypotheses. Combination is required; do not merely "
        "polish the parent in isolation."
    ),
    EvolutionOperator.ANALOGY: (
        "Transfer a defensible mechanism or experimental pattern from a "
        "different biological system or scientific domain, state the mapping, "
        "and identify where the analogy could fail."
    ),
    EvolutionOperator.OUT_OF_BOX: (
        "Deliberately depart from the parent's core approach to explore a "
        "high-value alternative that addresses the same research goal. "
        "Preserve lineage, but do not preserve the parent mechanism by default."
    ),
}


def operator_instruction(operator: EvolutionOperator) -> str:
    """Return the behavioral instruction for one evolution operator."""
    return _INSTRUCTIONS[operator]


def select_operator(index: int, iteration: int) -> EvolutionOperator:
    """Select a reproducible portfolio member across parents and iterations."""
    operators = tuple(EvolutionOperator)
    return operators[(index + iteration) % len(operators)]

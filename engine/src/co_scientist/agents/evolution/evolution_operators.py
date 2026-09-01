"""Distinct, disclosed hypothesis-evolution operators and instructions.

The operator portfolio covers all six strategies the paper discloses for
the Evolution agent (SSR §4): enhancement through grounding; coherence,
practicality and feasibility improvement; inspiration from existing
hypotheses; combination; simplification; and out-of-box thinking. The
engine additionally keeps analogy, which the expanded operator specs
carry ("the paper's six; some specs expand to eight").

Coherence/feasibility is its own operator rather than part of
ENHANCEMENT: the paper lists it as a distinct strategy with its own
feasibility-improvement prompt (SI Note 9.4), and folding it into
enhancement left enhancement doing two jobs while the paper's grounding
strategy (live retrieval, see ``evolve_grounding``) went unrepresented.

MP-8 (docs/CORPUS-EXTRACTION.md): the operator whose content structurally
matches published A.7 ("out-of-the-box thinking" -- generate one
hypothesis by analogy from supplied partner concepts, adapted rather than
replicated) is INSPIRATION, not OUT_OF_BOX below. OUT_OF_BOX takes no
partner hypotheses and is a clone-authored divergent-mechanism strategy
with no published counterpart. Left as a naming/documentation mismatch,
not renamed: EvolutionOperator.OUT_OF_BOX is a persisted value (lineage
records, telemetry), so renaming it is a data-migration decision for the
owner, not a prompt-content fix.
"""

from __future__ import annotations

import enum
import random


class EvolutionOperator(str, enum.Enum):
    """Published evolution strategies represented as executable operators."""

    ENHANCEMENT = "enhancement"
    COHERENCE_FEASIBILITY = "coherence_feasibility"
    INSPIRATION = "inspiration"
    COMBINATION = "combination"
    SIMPLIFICATION = "simplification"
    ANALOGY = "analogy"
    OUT_OF_BOX = "out_of_box"


_INSTRUCTIONS = {
    EvolutionOperator.ENHANCEMENT: (
        "Strengthen the hypothesis's grounding in evidence: identify its "
        "weaknesses and reasoning gaps, and elaborate details using the "
        "targeted literature supplied for this refinement, while retaining "
        "the scientifically valuable premise."
    ),
    EvolutionOperator.COHERENCE_FEASIBILITY: (
        "Improve coherence, practicality, and feasibility: rectify invalid "
        "initial assumptions, tighten the internal logic, and refine the "
        "proposal so it is implementable with contemporary technological "
        "capabilities, retaining its novelty and specific articulation."
    ),
    EvolutionOperator.INSPIRATION: (
        "Evolve the idea by borrowing the mechanism or structure of one of "
        "the existing top-ranked approaches supplied as partners into this "
        "hypothesis's target context. State what was borrowed, from which "
        "approach, and what was adapted rather than replicated."
    ),
    EvolutionOperator.COMBINATION: (
        "Synthesize complementary mechanisms or experiments from the parent "
        "and the combination partners supplied. Combination is required; do "
        "not merely polish the parent in isolation."
    ),
    EvolutionOperator.SIMPLIFICATION: (
        "Remove unnecessary assumptions and experimental complexity. Produce "
        "the smallest mechanism and decisive experiment that can test it."
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


def select_operators(
    count: int, iteration: int, seed_material: str
) -> list[EvolutionOperator]:
    """Assign this round's operators with coverage across the portfolio.

    Deals from a per-run shuffled deck of every operator, rotating the deal
    position each round, so every operator gains coverage across rounds
    whatever the tier's parent count. The old ``(index + iteration) % len``
    round-robin structurally skipped operators a small parent set never
    reached -- on an express-tier round the position of ENHANCEMENT in the
    cycle decided whether enhancement (and the live retrieval it carries)
    happened at all.

    Args:
        count: Number of parents to assign operators to.
        iteration: This evolution round's iteration number; rotates which
            operators a round of a given size reaches.
        seed_material: Run-scoped seed text; the assignment is fully
            deterministic for a given (seed_material, iteration, count).

    Returns:
        One operator per parent, in parent order.
    """
    if count <= 0:
        return []
    deck = list(EvolutionOperator)
    rng = random.Random(f"{seed_material}:evolution-operators")
    rng.shuffle(deck)
    offset = (iteration * count) % len(deck)
    return [deck[(offset + index) % len(deck)] for index in range(count)]

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

MP-8 (docs/CORPUS-EXTRACTION.md) recorded A.7's name and A.7's content
attached to different operators: OUT_OF_BOX carried the published name
but received no partner concepts, while INSPIRATION carried the content
(one hypothesis by analogy from supplied concepts, adapted rather than
replicated). Resolved by moving the content to the name rather than
renaming anything: OUT_OF_BOX now receives the partner concepts and
renders published A.7 (``evolution_out_of_box.md``), and INSPIRATION
keeps the paper's separately disclosed "inspiration from existing
hypotheses" strategy on ``evolution.md``. Every persisted operator value
(lineage records, telemetry) stays valid, so this is not a migration.

Two operators therefore render a *whole* published prompt rather than an
instruction appended to ``evolution.md``: COHERENCE_FEASIBILITY (A.6) and
OUT_OF_BOX (A.7). Their brief is the published prompt's own role sentence
and guidelines, so they carry a template in ``_TEMPLATES`` instead of an
entry in ``_INSTRUCTIONS``; every other operator is the reverse.
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
}

# The two operators Google published a whole prompt for, mapped to the
# template that carries it. Every other operator renders "evolution.md"
# with its _INSTRUCTIONS entry appended as the required-operator section.
_TEMPLATES = {
    EvolutionOperator.COHERENCE_FEASIBILITY: "evolution_feasibility",
    EvolutionOperator.OUT_OF_BOX: "evolution_out_of_box",
}


def operator_instruction(operator: EvolutionOperator) -> str:
    """Return the behavioral instruction for one evolution operator.

    Raises:
        KeyError: For an operator whose brief is a published template
            rather than an appended instruction (see ``_TEMPLATES``).
    """
    return _INSTRUCTIONS[operator]


def operator_template(operator: EvolutionOperator) -> str:
    """Return the prompt template one operator renders through."""
    return _TEMPLATES.get(operator, "evolution")


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

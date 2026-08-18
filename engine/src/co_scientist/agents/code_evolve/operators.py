"""Code operators: the moves a variant proposal is allowed to make.

Naming the move before asking for the edit is what keeps a search from
collapsing onto one kind of change. Left unprompted, a model asked to
"improve this program" tunes constants -- the safest edit, and the one
least likely to find anything -- over and over, and the lineage graph
fills with a hundred children that differ by a learning rate.

The deck is deliberately small. Each entry has to describe a move a
model can actually carry out against a program it can see, so
"restructure the architecture" is absent while "replace the core
algorithm" is present.
"""

from __future__ import annotations

import enum
import random


class CodeOperator(str, enum.Enum):
    """A named move from a parent program to a child."""

    REPAIR = "repair"
    TARGETED_EDIT = "targeted_edit"
    ALGORITHM_SWAP = "algorithm_swap"
    VECTORIZE = "vectorize"
    HYPERPARAMETERS = "hyperparameters"
    SIMPLIFY = "simplify"
    EXPLORE = "explore"


_INSTRUCTIONS: dict[CodeOperator, str] = {
    CodeOperator.REPAIR: (
        "The parent did not run. Read the captured error and fix the"
        " specific defect it names. Change nothing else: this edit's"
        " only job is to get the program executing again, so that the"
        " next one can be judged on its merits."
    ),
    CodeOperator.TARGETED_EDIT: (
        "Identify the single step that most limits the objective and"
        " change that step. Say which measurement points at it. Prefer"
        " one substantive change to several speculative ones -- the"
        " score cannot attribute an improvement across three edits."
    ),
    CodeOperator.ALGORITHM_SWAP: (
        "Replace the core algorithm with one that has a different"
        " complexity or a different failure mode, not a tidier version"
        " of the same idea. Name what the replacement does differently"
        " and what it gives up."
    ),
    CodeOperator.VECTORIZE: (
        "Replace explicit iteration with array or batched operations"
        " where the semantics are genuinely preserved. If a loop cannot"
        " be vectorised without changing results, leave it and say so"
        " rather than approximating."
    ),
    CodeOperator.HYPERPARAMETERS: (
        "Change the numeric constants that govern behaviour, and only"
        " those. Move them far enough to be distinguishable from noise"
        " in the metric, and state what you expect the change to do."
    ),
    CodeOperator.SIMPLIFY: (
        "Remove machinery that is not earning its cost -- an unused"
        " branch, a redundant pass, an abstraction with one caller."
        " Simplification is a real move here: a smaller program is"
        " easier for every later variant to change correctly."
    ),
    CodeOperator.EXPLORE: (
        "Take a deliberately different approach, accepting that it may"
        " score worse. Do not refine the parent. A search that only"
        " ever accepts improvements stops at the first local maximum it"
        " reaches, and this is the move that leaves one."
    ),
}

# Drawn when the parent ran. REPAIR is absent by construction -- there is
# nothing to repair -- and EXPLORE is deliberately rare rather than
# absent: it is the only move that can leave a local maximum, but a deck
# that plays it often never refines anything to begin with.
_WORKING_PARENT_DECK: tuple[tuple[CodeOperator, float], ...] = (
    (CodeOperator.TARGETED_EDIT, 0.34),
    (CodeOperator.ALGORITHM_SWAP, 0.18),
    (CodeOperator.VECTORIZE, 0.14),
    (CodeOperator.HYPERPARAMETERS, 0.14),
    (CodeOperator.SIMPLIFY, 0.10),
    (CodeOperator.EXPLORE, 0.10),
)


def instructions_for(operator: CodeOperator) -> str:
    """Returns the prompt text describing one operator's move."""
    return _INSTRUCTIONS[operator]


def select_operator(
    *, parent_failed: bool, rng: random.Random | None = None
) -> CodeOperator:
    """Chooses the move for the next child.

    Args:
        parent_failed: Whether the parent produced no usable score.
        rng: Source of randomness, injectable so a test can pin the draw.

    Returns:
        REPAIR whenever the parent failed, and a weighted draw otherwise.

    A failed parent forces REPAIR because every other move is wasted on
    a program that does not run: vectorising the loops of a module that
    raises on import produces a child that fails identically, and the
    search spends a generation learning nothing. This is the artifacts
    side-channel doing its actual work -- the captured error is only
    worth keeping if something acts on it.
    """
    if parent_failed:
        return CodeOperator.REPAIR
    source = rng or random.Random()
    return source.choices(
        [operator for operator, _ in _WORKING_PARENT_DECK],
        weights=[weight for _, weight in _WORKING_PARENT_DECK],
    )[0]

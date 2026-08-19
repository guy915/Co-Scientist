"""Proposing code variants: the generative half of code evolution.

`code_eval` scores a program; this package writes the next one. The two
are deliberately separate -- a proposal is an LLM call that can be wrong
in interesting ways, and an evaluation is a subprocess that must be
wrong in boring ones.
"""

from co_scientist.agents.code_evolve.archive import (
    DEFAULT_CELL_CAPACITY,
    EXPLOIT_SHARE,
    ArchiveEntry,
    archive_coverage,
    build_archive,
    select_parents,
)
from co_scientist.agents.code_evolve.behaviour import (
    CATEGORICAL_FEATURES,
    describe,
    is_categorical,
)
from co_scientist.agents.code_evolve.context import (
    MAX_ARTIFACT_CHARS,
    MAX_SOURCE_CHARS,
    ParentVariant,
)
from co_scientist.agents.code_evolve.grid import (
    DEFAULT_CELLS,
    DEFAULT_DESCRIPTORS,
    DEFAULT_GRID,
    Descriptor,
    Grid,
    GridStrategy,
    assign_cells,
    coverage,
)
from co_scientist.agents.code_evolve.operators import (
    CodeOperator,
    instructions_for,
    select_operator,
)
from co_scientist.agents.code_evolve.proposal import (
    ProposalRejectedError,
    VariantProposal,
    apply_proposal,
    build_prompt,
    propose_variant,
)

__all__ = [
    "CATEGORICAL_FEATURES",
    "DEFAULT_CELLS",
    "DEFAULT_CELL_CAPACITY",
    "DEFAULT_DESCRIPTORS",
    "DEFAULT_GRID",
    "EXPLOIT_SHARE",
    "MAX_ARTIFACT_CHARS",
    "MAX_SOURCE_CHARS",
    "ArchiveEntry",
    "CodeOperator",
    "Descriptor",
    "Grid",
    "GridStrategy",
    "ParentVariant",
    "ProposalRejectedError",
    "VariantProposal",
    "apply_proposal",
    "archive_coverage",
    "assign_cells",
    "build_archive",
    "build_prompt",
    "coverage",
    "describe",
    "instructions_for",
    "is_categorical",
    "propose_variant",
    "select_operator",
    "select_parents",
]

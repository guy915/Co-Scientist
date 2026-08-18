"""Proposing code variants: the generative half of code evolution.

`code_eval` scores a program; this package writes the next one. The two
are deliberately separate -- a proposal is an LLM call that can be wrong
in interesting ways, and an evaluation is a subprocess that must be
wrong in boring ones.
"""

from co_scientist.agents.code_evolve.context import (
    MAX_ARTIFACT_CHARS,
    MAX_SOURCE_CHARS,
    ParentVariant,
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
    "MAX_ARTIFACT_CHARS",
    "MAX_SOURCE_CHARS",
    "CodeOperator",
    "ParentVariant",
    "ProposalRejectedError",
    "VariantProposal",
    "apply_proposal",
    "build_prompt",
    "instructions_for",
    "propose_variant",
    "select_operator",
]

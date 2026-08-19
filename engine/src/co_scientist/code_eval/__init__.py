"""Evaluating candidate programs: the scored half of code evolution.

An agent proposes code; this package runs it and turns the run into a
number, a set of metrics, and -- when it fails -- the evidence needed to
propose something better. Confinement comes from `workspace`; nothing
here is a security boundary.
"""

from co_scientist.code_eval.pareto import (
    ObjectiveValues,
    dominates,
    is_multi_objective,
    pareto_front,
)
from co_scientist.code_eval.result import (
    EvaluationResult,
    EvaluationStatus,
    StageOutcome,
)
from co_scientist.code_eval.runner import evaluate_variant
from co_scientist.code_eval.spec import (
    DEFAULT_ARTIFACT_CHARS,
    DEFAULT_STAGE_TIMEOUT_SECONDS,
    Direction,
    EvaluationRequest,
    EvaluationStage,
    EvaluatorSpec,
    Objective,
)

__all__ = [
    "DEFAULT_ARTIFACT_CHARS",
    "DEFAULT_STAGE_TIMEOUT_SECONDS",
    "Direction",
    "EvaluationRequest",
    "EvaluationResult",
    "EvaluationStage",
    "EvaluationStatus",
    "EvaluatorSpec",
    "Objective",
    "ObjectiveValues",
    "StageOutcome",
    "dominates",
    "evaluate_variant",
    "is_multi_objective",
    "pareto_front",
]

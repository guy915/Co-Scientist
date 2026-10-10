from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal, cast

from co_scientist.core.exceptions import ProviderAdmissionError

ReasoningEffort = Literal["none", "low", "medium"]
ModelTier = Literal["worker", "supervisor"]
CallRole = Literal[
    "worker",
    "supervisor",
    "orchestrator",
    "meta_review",
    "overview",
    "overview_review",
    "overview_outline",
    "overview_directions",
    "generation",
    "literature_queries",
    "literature_analysis",
    "literature_synthesis",
    "drafting",
    "novelty",
    "reflection",
    "review",
    "deep_verification",
    "evidence_queries",
    "simulation",
    "ranking",
    "evolution",
    "grounding_queries",
    "proximity",
    "relevance",
    "research",
    "research_extract",
    "claims",
    "safety",
    "question_repair",
    "interview",
    "chat",
    "goal_text",
    "announcement",
    "credential_probe",
]

# "none" means the role never reasons, on every provider.
ROLE_DEFAULTS: dict[str, tuple[ModelTier, ReasoningEffort]] = {
    **dict.fromkeys(("supervisor", "meta_review", "overview"), ("supervisor", "medium")),
    **dict.fromkeys(
        ("overview_review", "overview_outline", "overview_directions"), ("supervisor", "low")
    ),
    **dict.fromkeys(
        (
            "worker",
            "generation",
            "literature_synthesis",
            "reflection",
            "review",
            "deep_verification",
            "simulation",
            "evolution",
            "interview",
            "chat",
        ),
        ("worker", "medium"),
    ),
    **dict.fromkeys(
        (
            "orchestrator",
            "research_extract",
            "literature_analysis",
            "drafting",
            "novelty",
            "ranking",
            "proximity",
            "relevance",
            "claims",
            "safety",
        ),
        ("worker", "low"),
    ),
    **dict.fromkeys(
        (
            "evidence_queries",
            "grounding_queries",
            "literature_queries",
            "research",
            "question_repair",
            "goal_text",
            "announcement",
            "credential_probe",
        ),
        ("worker", "none"),
    ),
}


# Operator credit runs Luna at its lowest reasoning effort, except the planning
# and report roles.
AZURE_MEDIUM_ROLES: frozenset[str] = frozenset({"supervisor", "overview"})


@dataclass(frozen=True)
class CallPolicy:
    role: CallRole = "worker"
    tier: ModelTier = "worker"
    effort: ReasoningEffort = "medium"
    # False when the caller turns thinking off or the role's effort is none.
    enable_thinking: bool = True
    azure_effort: ReasoningEffort = "low"


_policy: ContextVar[tuple[CallRole, ReasoningEffort | None, bool]] = ContextVar(
    "llm_call_policy", default=("worker", None, True)
)


def current_call_policy() -> CallPolicy:
    role, explicit, thinking = _policy.get()
    if role not in ROLE_DEFAULTS:
        raise ProviderAdmissionError("Unknown model call role")
    tier, default = ROLE_DEFAULTS[role]
    override = (
        os.getenv(f"LLM_EFFORT_{role.upper()}")
        or explicit
        or os.getenv(f"LLM_{tier.upper()}_EFFORT")
    )
    effort = override or default
    if effort not in ("none", "low", "medium"):
        raise ProviderAdmissionError("Model effort must be none, low or medium")
    reasons = thinking and effort != "none"
    azure_effort = (
        "none" if not reasons else override or ("medium" if role in AZURE_MEDIUM_ROLES else "low")
    )
    return CallPolicy(
        role,
        tier,
        cast(ReasoningEffort, effort),
        reasons,
        cast(ReasoningEffort, azure_effort),
    )


@contextmanager
def scoped_call_policy(
    role: CallRole,
    effort: ReasoningEffort | None = None,
    *,
    enable_thinking: bool = True,
) -> Iterator[None]:
    token = _policy.set((role, effort, enable_thinking))
    try:
        yield
    finally:
        _policy.reset(token)


# Persisted numeric call-type IDs must keep their meaning across releases.
_CALL_TYPES = (
    "worker",
    "supervisor",
    "orchestrator",
    "meta_review",
    "overview",
    "overview_review",
    "overview_outline",
    "overview_directions",
    "generation",
    "literature_queries",
    "literature_analysis",
    "literature_synthesis",
    "drafting",
    "novelty",
    "reflection",
    "review",
    "deep_verification",
    "evidence_queries",
    "simulation",
    "ranking",
    "evolution",
    "grounding_queries",
    "proximity",
    "relevance",
    "research",
    "research_extract",
    "claims",
    "safety",
    "question_repair",
    "interview",
    "chat",
    "goal_text",
    "announcement",
    "credential_probe",
)


def current_call_type_id() -> int:
    return _CALL_TYPES.index(current_call_policy().role) + 1

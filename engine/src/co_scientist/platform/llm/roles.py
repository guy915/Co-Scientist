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

ROLE_DEFAULTS: dict[str, tuple[ModelTier, ReasoningEffort]] = {
    "supervisor": ("supervisor", "medium"),
    "meta_review": ("supervisor", "medium"),
    "overview": ("supervisor", "medium"),
    "overview_review": ("supervisor", "low"),
    "overview_outline": ("supervisor", "none"),
    "overview_directions": ("supervisor", "none"),
    **dict.fromkeys(
        (
            "worker",
            "generation",
            "literature_synthesis",
            "reflection",
            "review",
            "deep_verification",
            "evidence_queries",
            "simulation",
            "evolution",
            "grounding_queries",
            "research_extract",
            "interview",
            "chat",
        ),
        ("worker", "medium"),
    ),
    **dict.fromkeys(
        (
            "orchestrator",
            "literature_queries",
            "literature_analysis",
            "drafting",
            "novelty",
            "ranking",
            "proximity",
            "relevance",
            "research",
            "claims",
            "safety",
            "question_repair",
            "goal_text",
            "announcement",
            "credential_probe",
        ),
        ("worker", "low"),
    ),
}


@dataclass(frozen=True)
class CallPolicy:
    role: CallRole = "worker"
    tier: ModelTier = "worker"
    effort: ReasoningEffort = "medium"
    enable_thinking: bool = True


_policy: ContextVar[tuple[CallRole, ReasoningEffort | None, bool]] = ContextVar(
    "llm_call_policy", default=("worker", None, True)
)


def current_call_policy() -> CallPolicy:
    role, explicit, thinking = _policy.get()
    if role not in ROLE_DEFAULTS:
        raise ProviderAdmissionError("Unknown model call role")
    tier, default = ROLE_DEFAULTS[role]
    effort = (
        os.getenv(f"LLM_EFFORT_{role.upper()}")
        or explicit
        or os.getenv(f"LLM_{tier.upper()}_EFFORT")
        or default
    )
    if effort not in ("none", "low", "medium") or (tier == "worker" and effort == "none"):
        raise ProviderAdmissionError(
            "Model effort must be none, low or medium; workers require low or medium"
        )
    return CallPolicy(role, tier, cast(ReasoningEffort, effort), thinking)


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

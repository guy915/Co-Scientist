import contextlib
import dataclasses
import enum
import itertools
import uuid
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from co_scientist.core.constants import INITIAL_ELO_RATING
from co_scientist.core.metrics import ExecutionMetrics as ExecutionMetrics
from co_scientist.core.metrics import MetricDeltas as MetricDeltas
from co_scientist.core.metrics import (
    create_metrics_update as create_metrics_update,
)
from co_scientist.core.metrics import merge_metrics as merge_metrics
from co_scientist.core.metrics import phase_message as phase_message

# Default agent authorship keeps pre-field checkpoints eligible as peer reviews.
AGENT_REVIEWER = "agent"

# Human verdicts never satisfy the run's owed peer review.
SCIENTIST_REVIEWER = "scientist"


@dataclass
class HypothesisReview:
    """Scientist reviews affect the gate but never satisfy the run's owed
    peer review.
    """

    review_summary: str
    scores: dict[str, int]
    safety_ethical_concerns: str
    detailed_feedback: dict[str, str]
    constructive_feedback: str
    overall_score: float
    already_explored: list[str] = field(default_factory=list)
    novel_aspects: list[str] = field(default_factory=list)
    reviewer: str = AGENT_REVIEWER


def has_peer_review(hypothesis: "Hypothesis") -> bool:
    """Human verdicts must not satisfy agent review, durable fan-out or
    scheduler review debt.
    """
    return any(review.reviewer != SCIENTIST_REVIEWER for review in hypothesis.reviews)


def _rebuild_reviews(
    reviews_data: list[dict[str, Any]],
) -> list[HypothesisReview]:
    return [HypothesisReview(**review) for review in reviews_data]


def _reviews_to_dicts(
    reviews: list[HypothesisReview],
) -> list[dict[str, Any]]:
    """Derive fields so new review fields cannot silently disappear during a
    round trip.
    """
    return [dataclasses.asdict(r) for r in reviews]


def _claim_fields(hypothesis: "Hypothesis") -> dict[str, Any]:
    return {
        # Authored titles may remain absent until the app's drain resolves a
        # display name.
        "title": hypothesis.title,
        "text": hypothesis.text,
        "category": hypothesis.category,
        "introduction": hypothesis.introduction,
        "recent_findings": hypothesis.recent_findings,
        "safety_and_toxicity": hypothesis.safety_and_toxicity,
        "explanation": hypothesis.explanation,
        "literature_grounding": hypothesis.literature_grounding,
        "experiment": hypothesis.experiment,
        "novelty_validation": hypothesis.novelty_validation,
        "enrichments": hypothesis.enrichments,
        "citation_map": hypothesis.citation_map,
    }


def _assessment_fields(hypothesis: "Hypothesis") -> dict[str, Any]:
    return {
        "reviews": _reviews_to_dicts(hypothesis.reviews),
        "similarity_cluster_id": hypothesis.similarity_cluster_id,
        "evolution_history": hypothesis.evolution_history,
        "reflection_notes": hypothesis.reflection_notes,
        "deep_verification_probes": hypothesis.deep_verification_probes,
        "deep_verification_verdict": hypothesis.deep_verification_verdict,
        "deep_verification_fingerprint": (hypothesis.deep_verification_fingerprint),
        "review_disposition": hypothesis.review_disposition,
        "safety_status": hypothesis.safety_status,
    }


# Eligibility and scheduler coverage share dispositions; weak ideas compete,
# duplicates archive. Undermined probes demote rather than block; unsafe remains
# a distinct reason.
BLOCKING_REVIEW_DISPOSITIONS = frozenset(
    {
        "inaccurate",
        "non_novel",
        "inaccurate_and_non_novel",
        "unsafe",
        "evidence_blocked",
    }
)

# Verification failure demotes without blocking; ordering and persistence share
# this exact verdict.
UNDERMINED_VERDICT = "undermined"


_ID_FACTORY: ContextVar[Callable[[], str] | None] = ContextVar(
    "hypothesis_id_factory", default=None
)


def new_hypothesis_id() -> str:
    factory = _ID_FACTORY.get()
    if factory is None:
        return str(uuid.uuid4())
    return factory()


def run_seed_material(run_id: str, research_goal: str) -> str:
    """NUL separates seed inputs so distinct pairs cannot collapse by
    concatenation.
    """
    return f"{run_id}\x00{research_goal}"


def _make_id_factory(seed_material: str) -> Callable[[], str]:
    namespace = uuid.uuid5(uuid.NAMESPACE_OID, seed_material)
    ordinals = itertools.count(1)

    def _mint() -> str:
        # Atomic next(count) prevents duplicate ordinals; execution order
        # determines who receives each ID.
        return str(uuid.uuid5(namespace, str(next(ordinals))))

    return _mint


@contextlib.contextmanager
def run_scoped_hypothesis_ids(seed_material: str) -> Iterator[None]:
    _ID_FACTORY.set(_make_id_factory(seed_material))
    try:
        yield
    finally:
        # Clear rather than reset: yielding consumers can exit in a different
        # ContextVar context.
        _ID_FACTORY.set(None)


class GenerationMethod(str, enum.Enum):
    DEBATE = "debate"
    LITERATURE_TOOLS = "literature_tools"
    ASSUMPTIONS = "assumptions"
    RESEARCH_EXPANSION = "research_expansion"


class HypothesisOrigin(str, enum.Enum):
    """Origin names the creating agent; GenerationMethod names the technique."""

    GENERATION = "generation"
    EVOLUTION = "evolution"
    SCIENTIST_MANUAL = "scientist_manual"


def _strip_computed_fields(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in ("total_matches", "win_rate")}


def _generation_method_value(
    method: "GenerationMethod | None",
) -> str | None:
    return method.value if method else None


@dataclass
class Hypothesis:
    """Identity does not affect text-based equality; proposer safety prose
    never controls the safety gate.
    """

    text: str
    id: str = field(default_factory=new_hypothesis_id, compare=False)
    # Evolution creates immutable children; lineage defaults keep older cached
    # payloads loadable.
    parent_id: str | None = field(default=None, compare=False)
    # Record every merged parent while retaining the primary parent for existing
    # lineage consumers.
    parent_ids: list[str] = field(default_factory=list, compare=False)
    generation: int = field(default=0, compare=False)
    origin: HypothesisOrigin = field(default=HypothesisOrigin.GENERATION, compare=False)
    creation_iteration: int | None = field(default=None, compare=False)
    title: str | None = None
    category: str | None = None
    introduction: str | None = None
    recent_findings: str | None = None
    safety_and_toxicity: str | None = None
    explanation: str | None = None
    literature_grounding: str | None = None
    experiment: str | None = None
    novelty_validation: str | None = None
    enrichments: dict[str, Any] = field(default_factory=dict)
    citation_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    score: float = 0.0
    elo_rating: int = INITIAL_ELO_RATING
    reviews: list[HypothesisReview] = field(default_factory=list)
    similarity_cluster_id: str | None = None
    similarity_degree: str | None = None
    evolution_history: list[str] = field(default_factory=list)
    reflection_notes: str | None = None
    deep_verification_probes: list[dict[str, Any]] = field(default_factory=list)
    deep_verification_verdict: str | None = None
    # Only cited-evidence inputs invalidate probes; unrelated new evidence must
    # not force re-verification.
    deep_verification_fingerprint: str | None = field(default=None, compare=False)
    review_disposition: str | None = field(default=None, compare=False)
    generation_method: GenerationMethod | None = None
    debate_id: None | (int) = None
    safety_status: str | None = field(default=None, compare=False)
    win_count: int = 0
    loss_count: int = 0

    @property
    def total_matches(self) -> int:
        return self.win_count + self.loss_count

    @property
    def win_rate(self) -> float:
        if self.total_matches == 0:
            return 0.0
        return (self.win_count / self.total_matches) * 100

    @property
    def latest_review(self) -> HypothesisReview | None:
        return self.reviews[-1] if self.reviews else None

    def review_summary(self) -> dict[str, Any] | None:
        latest = self.latest_review
        if latest is None:
            return None
        return {
            "overall_score": latest.overall_score,
            "review_summary": latest.review_summary,
            "constructive_feedback": latest.constructive_feedback,
            "scores": latest.scores,
        }

    def deep_verification_summary(self) -> dict[str, Any] | None:
        if not self.deep_verification_probes:
            return None
        return {
            "probes": self.deep_verification_probes,
            "verdict": self.deep_verification_verdict,
        }

    def is_rankable(self) -> bool:
        """Coverage counts only eligible ideas. Undermined verification
        demotes rather than blocks publication.
        """
        return self.review_disposition not in BLOCKING_REVIEW_DISPOSITIONS

    def is_undermined(self) -> bool:
        """One predicate serves publication order and persisted state so the
        verdict cannot drift.
        """
        return self.deep_verification_verdict == UNDERMINED_VERDICT

    def to_dict(self) -> dict[str, Any]:
        # API computed match fields are stripped on reload and recomputed;
        # serialized key order stays stable.
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "parent_ids": list(self.parent_ids),
            "generation": self.generation,
            "origin": self.origin.value,
            "creation_iteration": self.creation_iteration,
            **_claim_fields(self),
            "score": self.score,
            "elo_rating": self.elo_rating,
            **_assessment_fields(self),
            "generation_method": _generation_method_value(self.generation_method),
            "debate_id": self.debate_id,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "total_matches": self.total_matches,
            "win_rate": self.win_rate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Hypothesis":
        """Preserve provided identities; only absent legacy IDs mint new
        values.
        """
        payload = _strip_computed_fields(data)
        generation_method = payload.get("generation_method")
        if generation_method is not None:
            payload["generation_method"] = GenerationMethod(generation_method)
        origin = payload.get("origin")
        if origin is not None:
            payload["origin"] = HypothesisOrigin(origin)
        reviews = payload.get("reviews")
        if reviews:
            payload["reviews"] = _rebuild_reviews(reviews)
        return cls(**payload)


def rank_by_elo(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """All tie-break components descend, including text; mixed directions
    change canonical top-k.
    """
    return sorted(
        hypotheses,
        key=lambda h: (h.elo_rating, h.score, h.text),
        reverse=True,
    )


def rank_for_publication(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """One order for every reader-facing surface, matching the app's: an
    unplayed baseline rating is not evidence, and verification can undermine
    the highest-Elo idea after matches. Pair selection keeps raw Elo.
    """
    return sorted(
        rank_by_elo(hypotheses),
        key=lambda h: (h.is_undermined(), not h.total_matches),
    )

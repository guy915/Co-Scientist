"""Data models for hypothesis generation workflow.

These models maintain compatibility with the original AI-CoScientist
while providing clean type safety for LangGraph.

The execution-metrics models and node state-update helpers live in
``models_metrics``, and hypothesis-id minting in ``models_ids``; both are
re-exported here so import sites are unaffected by the split.
"""

import dataclasses
import enum
from dataclasses import dataclass, field
from typing import Any

from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models_ids import new_hypothesis_id as new_hypothesis_id
from co_scientist.models_ids import (
    run_scoped_hypothesis_ids as run_scoped_hypothesis_ids,
)
from co_scientist.models_ids import run_seed_material as run_seed_material
from co_scientist.models_metrics import ExecutionMetrics as ExecutionMetrics
from co_scientist.models_metrics import MetricDeltas as MetricDeltas
from co_scientist.models_metrics import _known_field_kwargs
from co_scientist.models_metrics import (
    create_metrics_update as create_metrics_update,
)
from co_scientist.models_metrics import merge_metrics as merge_metrics
from co_scientist.models_metrics import phase_message as phase_message


class GenerationMethod(str, enum.Enum):
    """How a hypothesis was generated (the four techniques of SSR §4)."""

    DEBATE = "debate"  # simulated scientific debate
    LITERATURE_TOOLS = "literature_tools"  # literature exploration
    ASSUMPTIONS = "assumptions"  # iterative assumptions identification
    RESEARCH_EXPANSION = "research_expansion"  # generate in unexplored areas


class HypothesisOrigin(str, enum.Enum):
    """Which agent created a hypothesis (its lineage origin).

    Distinct from ``GenerationMethod`` (which describes *how* the Generation
    agent produced a hypothesis). ``origin`` records *who* created it, matching
    the paper's parent/child lineage model (SSR §4, Evolution) and the store's
    ``hypotheses.created_by_agent`` column.
    """

    GENERATION = "generation"
    EVOLUTION = "evolution"
    SCIENTIST_MANUAL = "scientist_manual"


@dataclass
class HypothesisReview:
    """Review of a hypothesis with scores and feedback."""

    review_summary: str
    scores: dict[str, int]  # scientific_soundness, novelty, relevance, etc.
    safety_ethical_concerns: str
    detailed_feedback: dict[str, str]
    constructive_feedback: str
    overall_score: float


def _strip_computed_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Drop the derived-only total_matches/win_rate keys from a payload.

    Args:
        data: A dict shaped like the output of ``Hypothesis.to_dict``.

    Returns:
        A copy of data without the ``total_matches``/``win_rate`` keys.
    """
    return {
        k: v for k, v in data.items() if k not in ("total_matches", "win_rate")
    }


def _rebuild_reviews(
    reviews_data: list[dict[str, Any]],
) -> list[HypothesisReview]:
    """Rebuild serialized review dicts into HypothesisReview instances."""
    return [HypothesisReview(**review) for review in reviews_data]


def _generation_method_value(
    method: "GenerationMethod | None",
) -> str | None:
    """Return the enum's string value, or None."""
    return method.value if method else None


def _reviews_to_dicts(
    reviews: list[HypothesisReview],
) -> list[dict[str, Any]]:
    """Serialize HypothesisReview instances into plain dicts.

    ``asdict`` rather than a hand-written field list: the inverse
    ``_rebuild_reviews`` splats straight back into the dataclass, so a field
    added to ``HypothesisReview`` and not to the list here would round-trip
    as a silently missing key.
    """
    return [dataclasses.asdict(r) for r in reviews]


def _claim_fields(hypothesis: "Hypothesis") -> dict[str, Any]:
    """Serialize what the hypothesis asserts, as generation wrote it.

    Args:
        hypothesis: The hypothesis being serialized.

    Returns:
        The claim, its supporting prose, and the citations it rests on.
    """
    return {
        # Also referred to as "hypothesis" in other contexts.
        "text": hypothesis.text,
        "category": hypothesis.category,
        "explanation": hypothesis.explanation,
        "literature_grounding": hypothesis.literature_grounding,
        "experiment": hypothesis.experiment,
        # "literature_review_used": hypothesis.literature_review_used,
        "novelty_validation": hypothesis.novelty_validation,
        "enrichments": hypothesis.enrichments,
        "citation_map": hypothesis.citation_map,
    }


def _assessment_fields(hypothesis: "Hypothesis") -> dict[str, Any]:
    """Serialize what the run's review agents concluded about a hypothesis.

    Args:
        hypothesis: The hypothesis being serialized.

    Returns:
        The reviews, proximity/evolution traces, deep-verification result,
        and the review and safety dispositions gating publication.
    """
    return {
        "reviews": _reviews_to_dicts(hypothesis.reviews),
        "similarity_cluster_id": hypothesis.similarity_cluster_id,
        "evolution_history": hypothesis.evolution_history,
        "reflection_notes": hypothesis.reflection_notes,
        "deep_verification_probes": hypothesis.deep_verification_probes,
        "deep_verification_verdict": hypothesis.deep_verification_verdict,
        "deep_verification_fingerprint": (
            hypothesis.deep_verification_fingerprint
        ),
        "review_disposition": hypothesis.review_disposition,
        "safety_status": hypothesis.safety_status,
    }


# Review dispositions that keep a hypothesis out of the Elo tournament: the
# initial peer-review gate (inaccurate / non-novel) and the pre-ranking
# evidence gate (evidence_blocked). Shared by ranking and the scheduler so
# tournament-coverage accounting matches tournament eligibility.
#
# Note what is deliberately absent: "needs_revision" and "duplicate". A
# weak-but-not-fatal idea still competes and publishes -- the tournament,
# not a single early review, decides its standing (see
# agents/reflection/review.py::_apply_initial_review_gate). A duplicate is
# archived by proximity rather than judged, so it is excluded through its
# own path and reported as a duplicate, not as a failed idea.
BLOCKING_REVIEW_DISPOSITIONS = frozenset(
    {
        "inaccurate",
        "non_novel",
        "inaccurate_and_non_novel",
        "evidence_blocked",
    }
)


@dataclass
class Hypothesis:
    """A research hypothesis with associated metadata.

    Attributes:
        text: The dense technical hypothesis formulation
        id: Stable unique identifier that survives serialization and
            evolution. Excluded from equality/hashing (``compare=False``) so the
            text-based dedup heuristics are unaffected. Minted by
            ``models_ids.new_hypothesis_id``: a random uuid4, or this run's
            next deterministic id inside a ``run_scoped_hypothesis_ids``
            block.
        category: Short classification label for the hypothesis (e.g. the
            mechanism family or research sub-area it belongs to). Optional;
            when set it drives the document breadcrumb in the viewer, mirroring
            the reference product's first-class ``category`` field.
        explanation: Step-by-step layman explanation of the hypothesis
        literature_grounding: Explicit grounding in literature review with
            [P1]/[KG1]-style citation keys
        experiment: Practical experiment design to test the hypothesis
        novelty_validation: Summary of search queries used to validate
            novelty and findings (tool-based generation only)
        enrichments: Post-generation enrichment data from configured tools
            (e.g., related CVEs)
        citation_map: Resolves inline citation keys to full source metadata.
            Paper entries: {"type": "paper", "title": ..., "url": ...,
            "authors": [...], "year": ...}
            KG entries: {"type": "knowledge_graph", "display": ...,
            "tool_id": ..., "data": {...}}
        score: Overall quality score (0-100)
        elo_rating: Elo rating from tournament selection
        reviews: List of reviews received
        similarity_cluster_id: Cluster ID from proximity analysis
        evolution_history: List of refinement summaries
        reflection_notes: Reflection analysis from literature comparison
        generation_method: Method used to generate ('debate' or
            'literature_tools')
        debate_id: Debate ID for debate-generated hypotheses
            (None for literature)
        win_count: Tournament wins
        loss_count: Tournament losses
        total_matches: Total tournament matches
    """

    text: str
    id: str = field(default_factory=new_hypothesis_id, compare=False)
    # Lineage metadata (paper invariant: Evolution creates immutable children;
    # SSR §4, §12; TE §5). parent_id is None for generation-0 hypotheses and
    # points to the immediate parent for evolved/derived children. generation
    # is the lineage depth (0 = initial). origin records the creating agent.
    # creation_iteration records which workflow iteration produced it. All
    # default so older cached payloads without these keys still deserialize
    # (see from_dict).
    parent_id: str | None = field(default=None, compare=False)
    generation: int = field(default=0, compare=False)
    origin: HypothesisOrigin = field(
        default=HypothesisOrigin.GENERATION, compare=False
    )
    creation_iteration: int | None = field(default=None, compare=False)
    category: str | None = None
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
    similarity_degree: str | None = None  # 'high', 'medium', or 'low'
    evolution_history: list[str] = field(default_factory=list)
    reflection_notes: str | None = None
    deep_verification_probes: list[dict[str, Any]] = field(default_factory=list)
    deep_verification_verdict: str | None = None
    # Digest of the inputs the stored probes/verdict were produced from --
    # hypothesis text, verifier model, prompt version, and the evidence this
    # hypothesis actually cites. Deep verification re-runs only when it
    # changes, so unrelated evidence arriving elsewhere in the run does not
    # invalidate a verification that could not have used it. Compared, never
    # interpreted; see agents/reflection/deep_verification.py.
    deep_verification_fingerprint: str | None = field(
        default=None, compare=False
    )
    # Initial peer-review gate used to keep flawed/non-novel ideas out of Elo.
    review_disposition: str | None = field(default=None, compare=False)
    # 'debate' or 'literature_tools'
    generation_method: GenerationMethod | None = None
    debate_id: None | (
        int
    ) = None  # None for literature-generated, 0-N for debate-generated
    safety_status: str | None = field(default=None, compare=False)
    win_count: int = 0
    loss_count: int = 0

    @property
    def total_matches(self) -> int:
        """Total tournament matches played."""
        return self.win_count + self.loss_count

    @property
    def win_rate(self) -> float:
        """Win rate percentage (0-100)."""
        if self.total_matches == 0:
            return 0.0
        return (self.win_count / self.total_matches) * 100

    @property
    def latest_review(self) -> HypothesisReview | None:
        """The most recent review, or None if the hypothesis has none."""
        return self.reviews[-1] if self.reviews else None

    def review_summary(self) -> dict[str, Any] | None:
        """Project the latest review into a prompt-ready summary dict.

        None when the hypothesis has not been reviewed yet, so a prompt
        builder can drop the block entirely rather than render a hollow
        one. Shared by the ranking-matchup and evolution prompts, which
        each keep only the subset of fields they need from the result.

        Returns:
            A dict with the latest review's overall_score, review_summary,
            constructive_feedback, and scores, or None with no reviews yet.
        """
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
        """Project deep-verification probes/verdict into a prompt-ready dict.

        None before deep verification has run on this hypothesis (it only
        reaches the tournament's leaders, after the first ranking pass), so
        a prompt builder can drop the block entirely rather than render a
        hollow one.

        Returns:
            A dict with this hypothesis's probes and verdict, or None if no
            probes have been recorded yet.
        """
        if not self.deep_verification_probes:
            return None
        return {
            "probes": self.deep_verification_probes,
            "verdict": self.deep_verification_verdict,
        }

    def is_rankable(self) -> bool:
        """Return whether this hypothesis may enter the Elo tournament.

        A hypothesis is excluded from ranking if deep verification undermined
        it or an initial review / pre-ranking evidence gate rejected it. The
        scheduler must count tournament coverage over rankable hypotheses only,
        otherwise a pool full of un-rankable ideas keeps average coverage below
        the termination threshold and the orchestrator loops on ranking.
        """
        return (
            self.deep_verification_verdict != "undermined"
            and self.review_disposition not in BLOCKING_REVIEW_DISPOSITIONS
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        # Includes the derived total_matches/win_rate properties for API
        # consumers; from_dict() strips both back out since they are
        # recomputed from win_count/loss_count, not stored state.
        # The field groups are spliced in at their original positions, so the
        # serialized key order is unchanged by the grouping.
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "origin": self.origin.value,
            "creation_iteration": self.creation_iteration,
            **_claim_fields(self),
            "score": self.score,
            "elo_rating": self.elo_rating,
            **_assessment_fields(self),
            "generation_method": _generation_method_value(
                self.generation_method
            ),
            "debate_id": self.debate_id,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "total_matches": self.total_matches,
            "win_rate": self.win_rate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Hypothesis":
        """Reconstruct a Hypothesis from a ``to_dict`` payload.

        Preserves a provided ``id`` and only mints a fresh one when absent, so
        round-tripped and pre-id (legacy) payloads both reconstruct correctly.
        The computed-only ``total_matches``/``win_rate`` keys are dropped, the
        ``generation_method`` string is restored to its enum, and nested review
        dicts are rebuilt into ``HypothesisReview`` instances.

        Args:
            data: A dict shaped like the output of ``to_dict``.

        Returns:
            A ``Hypothesis`` reconstructed from ``data``.
        """
        payload = _strip_computed_fields(data)
        generation_method = payload.get("generation_method")
        if generation_method is not None:
            payload["generation_method"] = GenerationMethod(generation_method)
        # Restore the origin enum. Absent in pre-lineage payloads, where the
        # dataclass default (GENERATION) applies; present payloads carry the
        # string value written by to_dict.
        origin = payload.get("origin")
        if origin is not None:
            payload["origin"] = HypothesisOrigin(origin)
        reviews = payload.get("reviews")
        if reviews:
            payload["reviews"] = _rebuild_reviews(reviews)
        return cls(**payload)


# Canonical ranking helper reused by ranking.py, evolve.py, proximity.py,
# deep_verification.py, and research_overview.py, so "top-k hypotheses"
# means the same thing everywhere in the workflow.
def rank_by_elo(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """Return hypotheses ordered by Elo rating, strongest first.

    Canonical ranking policy shared across nodes, including the ranking node's
    own output order -- there is one Elo comparison, and callers needing extra
    rules (the tournament puts unrankable ideas last) compose a stable sort on
    top of this rather than restating it.

    Ties break by ``score`` then ``text`` so ordering is fully deterministic
    for a fixed set of hypotheses. All three components sort descending:
    ``reverse=True`` applies to the whole key, and a mixed-direction key
    (negating the numbers to leave ``text`` ascending) is what let a second
    copy of this comparison disagree with it on every tie.

    Args:
        hypotheses: The hypotheses to rank (not mutated).

    Returns:
        A new list sorted by descending ``(elo_rating, score, text)``.
    """
    return sorted(
        hypotheses,
        key=lambda h: (h.elo_rating, h.score, h.text),
        reverse=True,
    )


@dataclass
class Article:
    """A literature article with extracted content and metadata.

    Note: In PubMed-only mode, `content` and `pdf_links` are unused.
    Fulltext content is accessed directly by PaperQA from HTML files.
    """

    title: str
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citations: int = 0
    abstract: str | None = None
    # Unused in PubMed-only mode (PaperQA reads HTML files directly)
    content: str | None = None
    source_id: str | None = None
    source: str = "pubmed"  # default changed to "pubmed" (was "google_scholar")
    doi: str | None = None
    is_retracted: bool = False
    correction_status: str = "current"
    publication_type: str | None = None
    pdf_links: list[str] = field(
        default_factory=list
    )  # unused in PubMed-only mode (HTML-only)
    # Flag indicating if this article was analyzed by the agent
    used_in_analysis: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Article":
        """Rebuild from a ``to_dict`` payload, ignoring unknown keys."""
        return cls(**_known_field_kwargs(cls, data))

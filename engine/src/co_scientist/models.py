"""Data models for hypothesis generation workflow.

These models maintain compatibility with the original AI-CoScientist
while providing clean type safety for LangGraph.
"""

import dataclasses
import enum
import uuid
from dataclasses import dataclass, field
from typing import Any

from co_scientist.constants import INITIAL_ELO_RATING


def _known_field_kwargs(cls: Any, data: dict[str, Any]) -> dict[str, Any]:
    """Return the items of ``data`` whose keys are fields of ``cls``.

    Dropping unknown keys keeps older serialized payloads loadable if a field
    is later removed; the caller splats the result into ``cls(...)``.

    Args:
        cls: The dataclass whose field names are the allowed keys.
        data: A ``to_dict`` payload, possibly carrying stale keys.

    Returns:
        A dict of ``data`` items restricted to ``cls``'s field names.
    """
    field_names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in data.items() if k in field_names}


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


# Review dispositions that keep a hypothesis out of the Elo tournament: the
# initial peer-review gate (inaccurate / non-novel) and the pre-ranking
# evidence gate (evidence_blocked). Shared by ranking and the scheduler so
# tournament-coverage accounting matches tournament eligibility.
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
        id: Stable unique identifier (uuid4) that survives serialization and
            evolution. Excluded from equality/hashing (``compare=False``) so the
            text-based dedup heuristics are unaffected.
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
    id: str = field(default_factory=lambda: str(uuid.uuid4()), compare=False)
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
        # consumers; from_dict() below strips both back out on the way in,
        # since they are recomputed from win_count/loss_count, not stored
        # state.
        generation_method = (
            self.generation_method.value if self.generation_method else None
        )
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "origin": self.origin.value,
            "creation_iteration": self.creation_iteration,
            # Also referred to as "hypothesis" in other contexts.
            "text": self.text,
            "category": self.category,
            "explanation": self.explanation,
            "literature_grounding": self.literature_grounding,
            "experiment": self.experiment,
            # "literature_review_used": self.literature_review_used,
            "novelty_validation": self.novelty_validation,
            "enrichments": self.enrichments,
            "citation_map": self.citation_map,
            "score": self.score,
            "elo_rating": self.elo_rating,
            "reviews": [
                {
                    "review_summary": r.review_summary,
                    "scores": r.scores,
                    "safety_ethical_concerns": r.safety_ethical_concerns,
                    "detailed_feedback": r.detailed_feedback,
                    "constructive_feedback": r.constructive_feedback,
                    "overall_score": r.overall_score,
                }
                for r in self.reviews
            ],
            "similarity_cluster_id": self.similarity_cluster_id,
            "evolution_history": self.evolution_history,
            "reflection_notes": self.reflection_notes,
            "deep_verification_probes": self.deep_verification_probes,
            "deep_verification_verdict": self.deep_verification_verdict,
            "review_disposition": self.review_disposition,
            "safety_status": self.safety_status,
            "generation_method": generation_method,
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

    Canonical ranking policy shared across nodes. Ties break by ``score`` then
    ``text`` so ordering is fully deterministic for a fixed set of hypotheses.

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
class ExecutionMetrics:
    """Metrics for workflow execution."""

    total_time: float = 0.0
    hypothesis_count: int = 0
    reviews_count: int = 0
    tournaments_count: int = 0
    evolutions_count: int = 0
    llm_calls: int = 0  # Total LLM calls made
    # Keyed by workflow phase/node name (e.g. "generate", "review");
    # wall-clock seconds spent in that phase, summed across calls.
    phase_times: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for checkpoint transport (all fields are plain data)."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionMetrics":
        """Rebuild from a ``to_dict`` payload, ignoring unknown keys.

        Ignoring unknown keys keeps older checkpoints loadable if a metric
        field is later removed.
        """
        return cls(**_known_field_kwargs(cls, data))


def _merge_phase_times(
    existing_phase_times: dict[str, float], new_phase_times: dict[str, float]
) -> dict[str, float]:
    """Merge two phase-timing dicts, summing seconds for phases in both.

    Args:
        existing_phase_times: Phase times already accumulated in state.
        new_phase_times: Phase times from a node's metrics delta.

    Returns:
        A new dict with combined wall-clock seconds per phase.
    """
    merged_phase_times = dict(existing_phase_times)

    for phase, time_val in new_phase_times.items():
        merged_phase_times[phase] = (
            merged_phase_times.get(phase, 0.0) + time_val
        )

    return merged_phase_times


def merge_metrics(
    existing: ExecutionMetrics, new: ExecutionMetrics
) -> ExecutionMetrics:
    """State reducer that merges metrics from multiple nodes.

    When multiple nodes update metrics concurrently, this combines them. Lives
    next to ExecutionMetrics so field additions and their merge policy are a
    one-file change.

    Args:
        existing: Existing metrics in state
        new: New metrics being added (should contain only deltas)

    Returns:
        Merged metrics (new object, does not mutate inputs)
    """
    # LangGraph invokes this reducer whenever a node's state update includes
    # a "metrics" key; "new" is that node's create_metrics_update(...)
    # output (deltas only, per its docstring), not a cumulative snapshot.
    # Create a NEW metrics object (don't mutate existing!)
    merged_phase_times = _merge_phase_times(
        existing.phase_times, new.phase_times
    )

    # Per-field merge policy, matched to what create_metrics_update
    # produces: hypothesis_count is the node's reported running *total*
    # rather than a delta, so max() keeps the larger observed count instead
    # of double-counting; total_time only overwrites when a node actually
    # measured one (> 0); the rest are straightforward additive deltas.
    merged = ExecutionMetrics(
        hypothesis_count=max(existing.hypothesis_count, new.hypothesis_count),
        reviews_count=existing.reviews_count + new.reviews_count,
        tournaments_count=existing.tournaments_count + new.tournaments_count,
        evolutions_count=existing.evolutions_count + new.evolutions_count,
        llm_calls=existing.llm_calls + new.llm_calls,
        total_time=new.total_time
        if new.total_time > 0
        else existing.total_time,
        phase_times=merged_phase_times,
    )

    return merged


def create_metrics_update(
    hypothesis_count: int | None = None,
    reviews_count_delta: int = 0,
    tournaments_count_delta: int = 0,
    evolutions_count_delta: int = 0,
    llm_calls_delta: int = 0,
    total_time: float | None = None,
    phase_times: dict[str, float] | None = None,
) -> ExecutionMetrics:
    """Create new ExecutionMetrics with ONLY the deltas (not cumulative).

    The merge_metrics reducer will add these deltas to the existing state.
    Do NOT pass base metrics - only pass the increments from this node.

    Args:
        hypothesis_count: new total hypothesis count
            (replaces via max(), not adds)
        reviews_count_delta: number of reviews to add (delta only)
        tournaments_count_delta: number of tournaments to add (delta only)
        evolutions_count_delta: number of evolutions to add (delta only)
        llm_calls_delta: number of llm calls to add (delta only)
        total_time: new total time (only set if > 0)
        phase_times: new phase times dict (merged with existing)

    Returns:
        new ExecutionMetrics object with ONLY deltas
    """
    return ExecutionMetrics(
        hypothesis_count=hypothesis_count
        if hypothesis_count is not None
        else 0,
        reviews_count=reviews_count_delta,
        tournaments_count=tournaments_count_delta,
        evolutions_count=evolutions_count_delta,
        llm_calls=llm_calls_delta,
        total_time=total_time if total_time is not None else 0.0,
        phase_times=phase_times if phase_times is not None else {},
    )


def phase_message(
    phase: str, content: str, **metadata: Any
) -> list[dict[str, Any]]:
    """Build the one-message list a node returns in its state update.

    Args:
        phase: Workflow phase name recorded in the message metadata.
        content: Human-readable summary of what the node did.
        **metadata: Extra metadata fields merged alongside the phase.

    Returns:
        A single-element assistant-message list for the messages channel.
    """
    return [
        {
            "role": "assistant",
            "content": content,
            "metadata": {"phase": phase, **metadata},
        }
    ]


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

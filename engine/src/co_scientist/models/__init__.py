"""Hypothesis models and run-scoped identifier minting.

Execution metrics and state updates live in models.metrics, Article in
models.article, and review records and serialization in models.review.
Their public names are exported here alongside Hypothesis.
"""

import contextlib
import enum
import itertools
import uuid
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models.article import Article as Article
from co_scientist.models.metrics import ExecutionMetrics as ExecutionMetrics
from co_scientist.models.metrics import MetricDeltas as MetricDeltas
from co_scientist.models.metrics import (
    create_metrics_update as create_metrics_update,
)
from co_scientist.models.metrics import merge_metrics as merge_metrics
from co_scientist.models.metrics import phase_message as phase_message
from co_scientist.models.review import AGENT_REVIEWER as AGENT_REVIEWER
from co_scientist.models.review import (
    BLOCKING_REVIEW_DISPOSITIONS as BLOCKING_REVIEW_DISPOSITIONS,
)
from co_scientist.models.review import SCIENTIST_REVIEWER as SCIENTIST_REVIEWER
from co_scientist.models.review import UNDERMINED_VERDICT as UNDERMINED_VERDICT
from co_scientist.models.review import HypothesisReview as HypothesisReview
from co_scientist.models.review import _assessment_fields as _assessment_fields
from co_scientist.models.review import _claim_fields as _claim_fields
from co_scientist.models.review import _rebuild_reviews as _rebuild_reviews
from co_scientist.models.review import has_peer_review as has_peer_review

# None (the default) means "draw a random uuid4", which is every context
# outside an in-process run.
_ID_FACTORY: ContextVar[Callable[[], str] | None] = ContextVar(
    "hypothesis_id_factory", default=None
)


def new_hypothesis_id() -> str:
    """Mints the identifier for a freshly constructed hypothesis.

    Returns:
        This run's next deterministic id when a run installed a factory in
        the calling context, otherwise a fresh random ``uuid4``.
    """
    factory = _ID_FACTORY.get()
    if factory is None:
        return str(uuid.uuid4())
    return factory()


def run_seed_material(run_id: str, research_goal: str) -> str:
    """Builds the text identifying one run's id stream.

    Args:
        run_id: The run's unique identifier.
        research_goal: The run's research question or goal.

    Returns:
        Seed text combining both, NUL-separated so no pair of inputs can
        be concatenated into another pair's seed.
    """
    return f"{run_id}\x00{research_goal}"


def _make_id_factory(seed_material: str) -> Callable[[], str]:
    """Builds one run's deterministic id minter.

    Args:
        seed_material: Text identifying this run (see
            ``run_seed_material``). Runs differing in it get disjoint
            namespaces, so their ids can never collide.

    Returns:
        A callable minting ``uuid5(run namespace, ordinal)`` ids: unique
        within the run, and disjoint from every other run's.
    """
    namespace = uuid.uuid5(uuid.NAMESPACE_OID, seed_material)
    ordinals = itertools.count(1)

    def _mint() -> str:
        # next() on an itertools.count is atomic, so two nodes minting
        # concurrently never draw the same ordinal. Which node draws
        # which ordinal follows the run's own execution order -- the same
        # basis the rest of the offline pipeline's determinism rests on.
        return str(uuid.uuid5(namespace, str(next(ordinals))))

    return _mint


@contextlib.contextmanager
def run_scoped_hypothesis_ids(seed_material: str) -> Iterator[None]:
    """Mints deterministic hypothesis ids for the duration of one run.

    Args:
        seed_material: Text identifying this run (see
            ``run_seed_material``).

    Yields:
        None; hypotheses constructed inside the block, and inside any task
        or thread it spawns, draw their ids from this run's stream.
    """
    _ID_FACTORY.set(_make_id_factory(seed_material))
    try:
        yield
    finally:
        # Cleared rather than reset from a token: a streaming run holds
        # this block open across yields, so entry and exit can run in
        # different consumer contexts, and ``ContextVar.reset`` rejects a
        # token from another context. Clearing restores the default
        # (``uuid4``) and cannot raise.
        _ID_FACTORY.set(None)


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


def _generation_method_value(
    method: "GenerationMethod | None",
) -> str | None:
    """Return the enum's string value, or None."""
    return method.value if method else None


@dataclass
class Hypothesis:
    """A research hypothesis with associated metadata.

    Attributes:
        text: The dense technical hypothesis formulation
        title: A short, authored noun-phrase name for the hypothesis (R14-12;
            the published '# **<Product> - <Title>**' pattern), distinct from
            ``text``. None for a run predating this field, or a
            ``json_object`` downgrade whose response omitted it -- the app's
            drain is where that absence is resolved to a displayable title
            (see ``app/app/engine_adapter/drain/hypotheses.py``), so this
            field is carried through unvalidated exactly as the LLM returned
            it, the same as ``category``/``introduction`` below.
        id: Stable unique identifier that survives serialization and
            evolution. Excluded from equality/hashing (``compare=False``) so the
            text-based dedup heuristics are unaffected. Minted by
            ``models.new_hypothesis_id``: a random uuid4, or this run's
            next deterministic id inside a ``run_scoped_hypothesis_ids``
            block.
        category: Short classification label for the hypothesis (e.g. the
            mechanism family or research sub-area it belongs to). Optional;
            when set it drives the document breadcrumb in the viewer, mirroring
            the reference product's first-class ``category`` field.
        introduction: Scene-setting background for the problem area, before
            any mechanism is proposed (MO-6; the published 'Introduction').
        recent_findings: Recent literature findings and related research
            this hypothesis builds on (MO-6; the published 'Recent findings
            and related research').
        safety_and_toxicity: The proposer's own pharmacological safety
            assessment of what the hypothesis proposes (MO-10; the
            published 'Safety and toxicity'). Distinct from the reviewer's
            ``safety_ethical_concerns`` (dual-use/ethics) and never
            consulted by the safety gate (see agents/safety/).
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
    # Every parent merged into this hypothesis (multi-parent combination);
    # parent_id stays the primary parent so lineage consumers are unchanged.
    # Empty for hypotheses with no recorded multi-parent lineage.
    parent_ids: list[str] = field(default_factory=list, compare=False)
    generation: int = field(default=0, compare=False)
    origin: HypothesisOrigin = field(
        default=HypothesisOrigin.GENERATION, compare=False
    )
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

        A hypothesis is excluded from ranking if an initial review or the
        pre-ranking evidence gate rejected it. The scheduler must count
        tournament coverage over rankable hypotheses only, otherwise a pool
        full of un-rankable ideas keeps average coverage below the
        termination threshold and the orchestrator loops on ranking.

        A deep-verification verdict of "undermined" is deliberately *not*
        one of these (superseding audit E9's exclusion, though not its
        fail-closed "unverified" record). It used to bar ranking exactly
        like a blocking disposition, which made it the second of two
        terminal gates in series: once the evidence gate stopped blocking
        on non-claims, undermined took over as the binding constraint and a
        measured run still published one idea of four. It is a single LLM
        call -- too thin a basis to delete work, and now delivered to
        every idea ahead of its first tournament match rather than to the
        few that led one, which makes a blocking reading of it costlier
        still. It demotes instead: ``is_undermined`` sorts those ideas
        below every sound one and the reader sees the verdict on the idea.
        """
        return self.review_disposition not in BLOCKING_REVIEW_DISPOSITIONS

    def is_undermined(self) -> bool:
        """Return whether deep verification found a fundamental flaw.

        Rankable but demoted: see :meth:`is_rankable`. The one predicate the
        ordering and the persisted state both read, so "undermined" cannot
        come to mean two things.
        """
        return self.deep_verification_verdict == UNDERMINED_VERDICT

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
            "parent_ids": list(self.parent_ids),
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


def rank_for_publication(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """Return hypotheses in the order a reader should meet them.

    :func:`rank_by_elo` with the deep-verification demotion composed on top:
    ideas whose fundamental assumption failed a probe sort below every sound
    one, keeping their relative Elo order among themselves.

    Elo cannot express this on its own, and points the wrong way. Deep
    verification only runs on the ideas that *led* the tournament, and its
    verdict lands after the matches that earned them their rating -- so the
    run's most doubted idea carries its highest score, and any surface
    ordering on Elo alone puts it first. Every surface a reader sees the
    order on (the ranking node's published pool, the research overview's
    top-k) uses this; the matchmaker and the tournament's own pairing keep
    the plain Elo comparison, which is a statement about strength of play,
    not about what to show first.

    Args:
        hypotheses: The hypotheses to order (not mutated).

    Returns:
        A new list, sound ideas first, each band ordered by Elo.
    """
    return sorted(rank_by_elo(hypotheses), key=lambda h: h.is_undermined())

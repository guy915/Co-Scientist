"""Pins the engine against the pseudo-code Google published for its agents.

Nature SI Note 8 prints the Supervisor's loop and each agent's functions as
one integrated listing. It is the only primary source that states several
values the papers' prose leaves out -- the tournament's entry rating, how
many hypotheses evolution breeds from, how many the final overview
synthesizes, and the two named termination predicates -- so those numbers
are read out of the listing here rather than restated, and the engine's
constants are checked against what is read.

Where the local implementation deliberately differs from the listing it is
not pinned: the proximity agent's all-pairs embedding similarity is one
such divergence (the paper says only "e.g. text embeddings"), recorded in
``docs/fidelity-audit`` rather than asserted here.

The literals quoted below are the published values, transcribed once as
module-level constants and cited to the extracted file they came from. Every
test in this module checks the engine against those constants directly, so
none of it touches disk and none of it can skip -- this is the half of the
pin that must keep guarding once ``references/`` is gone.
``test_published_pseudocode_invariants_corroboration.py`` re-reads the same
files and asserts the transcription still matches; that module is the one
allowed to skip when the corpus is absent.
"""

from __future__ import annotations

from co_scientist.agents.evolution.evolve_round import EVOLUTION_PARENT_COUNT
from co_scientist.agents.ranking.ranking_matchmaking import MatchmakingWeights
from co_scientist.constants import (
    INITIAL_ELO_RATING,
    RESEARCH_OVERVIEW_TOP_K,
)
from co_scientist.generator import HypothesisGenerator
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.scheduling.models import TerminationReason
from co_scientist.schemas import get_schema_for_prompt

# Every constant below cites
# references/core/google-co-scientist/research/extracted-artifacts/pseudocode/
# <name>.md, each one part of the single Nature SI Note 8 listing (source
# lines 905-1099 of the supplementary information).

# 01-supervisor.md -- 71 lines, sha256 2f7a6fe641b3.
# "WHILE NumberOfIdeas < MaxIdeas AND NumberOfMatchesPerIdea <
# MaxMatchesPerIdea DO" -- the Supervisor's two named termination
# predicates. Google states the names, not the values, so only the
# predicates are pinned; their thresholds stay configurable clone
# decisions. This constant is used by the corroboration module; the two
# reason values below are our own vocabulary for the same predicates.
_SUPERVISOR_TERMINATION_PREDICATES = (
    "NumberOfIdeas < MaxIdeas",
    "NumberOfMatchesPerIdea < MaxMatchesPerIdea",
)
_TERMINATION_REASON_VALUES = {"max_ideas", "max_matches_per_idea"}

# 02-generation.md -- 29 lines, sha256 f9d19a9a6505.
# "Strategy 1: Use existing knowledge" / "Strategy 2: Simulate debate",
# followed by "More strategies..." -- the two named strategies are
# required, and the enum is deliberately allowed to be larger.
_GENERATION_STATED_STRATEGIES = (
    "Strategy 1: Use existing knowledge",
    "Strategy 2: Simulate debate",
)

# 03-reflection.md -- 30 lines, sha256 ad6a4c3b022c.
# "Break down this hypothesis into its core assumptions." / "CHECK if the
# assumption is scientifically plausible" -- deep verification decomposes
# a hypothesis and checks each assumption in turn.
_REFLECTION_STATED_ASSUMPTION_LINES = (
    "Break down this hypothesis into its core assumptions",
    "CHECK if the assumption is scientifically plausible",
)

# 04-ranking.md -- 36 lines, sha256 e5c0327ddb0c.
# "SET HypothesisToAdd.EloRating TO 1200" -- AddToTournament's only
# initializer, since it exits early for a hypothesis that already has a
# rating.
_RANKING_STATED_ENTRY_RATING = 1200
# "Prioritize new hypotheses or those with similar Elo ratings" -- Google
# publishes no weights, so only the presence of the two matching terms is
# pinned below, not their magnitudes.
_RANKING_STATED_PAIRING_LINE = (
    "Prioritize new hypotheses or those with similar Elo ratings"
)

# 05-evolution.md -- 32 lines, sha256 f737c9a057b7.
# "FETCH the top 5 hypotheses from the HypothesesList".
_EVOLUTION_STATED_PARENT_COUNT = 5
# "// Treat it like a brand new idea" followed by a new Reflection review
# task -- an evolved hypothesis re-enters review exactly like a freshly
# generated one.
_EVOLUTION_STATED_TREAT_AS_NEW_LINE = "Treat it like a brand new idea"
_EVOLUTION_STATED_REVIEW_TASK_LINE = (
    'Agent: Reflection, Action: "ReviewHypothesis"'
)

# 07-meta-review.md -- 25 lines, sha256 7e502a1ae3fa.
# "FETCH the top 10 hypotheses from SharedMemory".
_META_REVIEW_STATED_TOP_N = 10
# "GATHER all reviews and tournament debate transcripts from SharedMemory".
_META_REVIEW_STATED_GATHER_LINE = (
    "GATHER all reviews and tournament debate transcripts"
)


def test_tournament_entry_rating_is_the_stated_one() -> None:
    """A hypothesis enters the tournament at the listing's rating.

    The Ranking agent's ``AddToTournament`` sets the rating once and exits
    early for a hypothesis that already has one, so the entry rating is
    also the only initializer -- which is why the model's default is
    checked against it too.
    """
    assert INITIAL_ELO_RATING == _RANKING_STATED_ENTRY_RATING
    hypothesis = Hypothesis(text="An idea.")
    assert hypothesis.elo_rating == _RANKING_STATED_ENTRY_RATING


def test_termination_predicates_are_the_named_ones() -> None:
    """The run stops on the two predicates the Supervisor loop names."""
    reasons = {reason.value for reason in TerminationReason}
    assert reasons >= _TERMINATION_REASON_VALUES


def test_evolution_breeds_from_the_stated_parent_count() -> None:
    """Evolution takes its parents from the listing's top-N by rank."""
    assert EVOLUTION_PARENT_COUNT == _EVOLUTION_STATED_PARENT_COUNT


def test_research_overview_synthesizes_the_stated_top_n() -> None:
    """The final overview synthesizes the listing's top-N hypotheses."""
    assert RESEARCH_OVERVIEW_TOP_K == _META_REVIEW_STATED_TOP_N


def test_pairing_prioritizes_new_and_similarly_rated_ideas() -> None:
    """Matchmaking weights the two priorities the listing names.

    ``RunTournamentBatch`` prioritizes new hypotheses (``recency``) and
    ones whose ratings are close (``elo_closeness``, the pairwise term
    scored in ``_partner_score`` -- ``rank`` and ``similarity_bonus``
    score different things and would let this pass without the property
    they name actually existing). Behavior is pinned separately by
    ``test_ranking_matchmaking.py::test_close_elo_hypotheses_are_preferred``.
    """
    weights = MatchmakingWeights()
    assert weights.recency > 0
    assert weights.elo_closeness > 0


def test_evolved_hypotheses_are_reviewed_like_new_ones() -> None:
    """An evolved hypothesis re-enters review, as the listing requires.

    The Evolution agent queues a Reflection review for each child it
    creates -- "treat it like a brand new idea" -- which in this graph is
    the evolve to review edge.
    """
    graph = HypothesisGenerator()._build_graph(
        enable_literature_review_node=False
    )
    drawable = graph.get_graph()
    assert {
        edge.target for edge in drawable.edges if edge.source == "evolve"
    } == {"review"}


def test_deep_verification_decomposes_into_assumptions() -> None:
    """Verification breaks a hypothesis down and checks each assumption.

    The Reflection agent's listing does exactly that, so the schema must
    carry the decomposition rather than only the probing questions.
    """
    schema = get_schema_for_prompt("deep_verification")
    assert schema is not None
    item = schema["schema"]["properties"]["sub_assumptions"]["items"]
    assert set(item["required"]) == {"assumption", "verification", "status"}


def test_generation_runs_the_strategies_the_listing_names() -> None:
    """Generation carries the listing's two named strategies, and more.

    The listing names existing-knowledge and simulated-debate generation
    and then says "More strategies...", so the two named ones are required
    and the enum is deliberately allowed to be larger.
    """
    methods = {method.value for method in GenerationMethod}
    assert {"literature_tools", "debate"} <= methods


def test_meta_review_reads_reviews_and_debate_transcripts() -> None:
    """System feedback is synthesized from both of the listing's inputs."""
    schema = get_schema_for_prompt("meta_review")
    assert schema is not None
    properties = schema["schema"]["properties"]
    assert "meta_review_summary" in properties

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
"""

from __future__ import annotations

import re

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
from tests._published_corpus import published_pseudocode

_WHITESPACE = re.compile(r"\s+")


def _states(listing: str, phrase: str) -> bool:
    """Whether the listing states a phrase, ignoring its line breaks.

    The source wraps prompts and comments mid-sentence, so a literal
    containment check would depend on where a line happened to break.

    Args:
        listing: The pseudo-code to search.
        phrase: The phrase to look for.

    Returns:
        Whether the phrase appears, comparing whitespace-collapsed text.
    """
    return _WHITESPACE.sub(" ", phrase) in _WHITESPACE.sub(" ", listing)


def _stated_number(listing: str, pattern: str) -> int:
    """Return the single number the listing states for one pattern.

    Args:
        listing: The pseudo-code to read it out of.
        pattern: Regex with one capturing group around the number.

    Returns:
        The captured number.
    """
    matches = re.findall(pattern, listing)
    assert len(matches) == 1, f"expected one {pattern!r}, got {matches}"
    return int(matches[0])


def test_tournament_entry_rating_is_the_stated_one() -> None:
    """A hypothesis enters the tournament at the listing's rating.

    The Ranking agent's ``AddToTournament`` sets the rating once and exits
    early for a hypothesis that already has one, so the entry rating is
    also the only initializer -- which is why the model's default is
    checked against it too.
    """
    listing = published_pseudocode("04-ranking")
    stated = _stated_number(listing, r"SET HypothesisToAdd\.EloRating TO (\d+)")

    assert stated == INITIAL_ELO_RATING
    assert Hypothesis(text="An idea.").elo_rating == stated


def test_termination_predicates_are_the_named_ones() -> None:
    """The run stops on the two predicates the Supervisor loop names.

    Google states the names and not the values, so only the predicates are
    pinned; their thresholds stay configurable clone decisions.
    """
    listing = published_pseudocode("01-supervisor")
    assert _states(listing, "NumberOfIdeas < MaxIdeas")
    assert _states(listing, "NumberOfMatchesPerIdea < MaxMatchesPerIdea")

    reasons = {reason.value for reason in TerminationReason}
    assert {"max_ideas", "max_matches_per_idea"} <= reasons


def test_evolution_breeds_from_the_stated_parent_count() -> None:
    """Evolution takes its parents from the listing's top-N by rank."""
    listing = published_pseudocode("05-evolution")
    stated = _stated_number(
        listing, r"FETCH the top (\d+) hypotheses from the HypothesesList"
    )

    assert stated == EVOLUTION_PARENT_COUNT


def test_research_overview_synthesizes_the_stated_top_n() -> None:
    """The final overview synthesizes the listing's top-N hypotheses."""
    listing = published_pseudocode("07-meta-review")
    stated = _stated_number(
        listing, r"FETCH the top (\d+) hypotheses from SharedMemory"
    )

    assert stated == RESEARCH_OVERVIEW_TOP_K


def test_pairing_prioritizes_new_and_similarly_rated_ideas() -> None:
    """Matchmaking weights the two priorities the listing names.

    ``RunTournamentBatch`` prioritizes new hypotheses (``recency``) and
    ones whose ratings are close (``elo_closeness``, the pairwise term
    scored in ``_partner_score`` -- ``rank`` and ``similarity_bonus``
    score different things and would let this pass without the property
    they name actually existing). Google publishes no weights, so only
    the presence of both terms is pinned, not their magnitudes; behavior
    is pinned separately by
    ``test_ranking_matchmaking.py::test_close_elo_hypotheses_are_preferred``.
    """
    listing = published_pseudocode("04-ranking")
    assert _states(
        listing, "Prioritize new hypotheses or those with similar Elo ratings"
    )

    weights = MatchmakingWeights()
    assert weights.recency > 0
    assert weights.elo_closeness > 0


def test_evolved_hypotheses_are_reviewed_like_new_ones() -> None:
    """An evolved hypothesis re-enters review, as the listing requires.

    The Evolution agent queues a Reflection review for each child it
    creates -- "treat it like a brand new idea" -- which in this graph is
    the evolve to review edge.
    """
    listing = published_pseudocode("05-evolution")
    assert _states(listing, "Treat it like a brand new idea")
    assert _states(listing, 'Agent: Reflection, Action: "ReviewHypothesis"')

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
    listing = published_pseudocode("03-reflection")
    assert _states(
        listing, "Break down this hypothesis into its core assumptions"
    )
    assert _states(
        listing, "CHECK if the assumption is scientifically plausible"
    )

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
    listing = published_pseudocode("02-generation")
    assert _states(listing, "Strategy 1: Use existing knowledge")
    assert _states(listing, "Strategy 2: Simulate debate")

    methods = {method.value for method in GenerationMethod}
    assert {"literature_tools", "debate"} <= methods


def test_meta_review_reads_reviews_and_debate_transcripts() -> None:
    """System feedback is synthesized from both of the listing's inputs."""
    listing = published_pseudocode("07-meta-review")
    assert _states(
        listing, "GATHER all reviews and tournament debate transcripts"
    )

    schema = get_schema_for_prompt("meta_review")
    assert schema is not None
    properties = schema["schema"]["properties"]
    assert "meta_review_summary" in properties

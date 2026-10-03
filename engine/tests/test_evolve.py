"""Offline contracts for evolve."""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from typing import Any, NamedTuple

import pytest

from co_scientist.agents.evolution import evolve
from co_scientist.agents.evolution.evolve import (
    _select_evolution_pool,
    evolve_node,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _sample_up_to,
    _specialist_feedback_for,
    combination_partners,
    find_nearest_peer,
    sample_context_hypotheses,
    token_coverage,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import Hypothesis, HypothesisOrigin, rank_by_elo
from co_scientist.state import WorkflowState
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_state

# Canned refinement reused by the single-hypothesis evolution tests. Its
# vocabulary is disjoint from the input hypotheses so neither the unchanged
# guard nor the 0.95 near-duplicate guard fires.
_RAPAMYCIN_RESPONSE: dict[str, Any] = {
    "hypothesis": "rapamycin suppresses mtor signaling downstream",
    "explanation": "fresh layman walkthrough",
    "experiment": "knock down the kinase and measure growth",
    "refinement_summary": "pivoted to a kinase mechanism",
}

_STALE_PROBE: dict[str, Any] = {
    "question": "stale q",
    "answer": "stale a",
    "reasoning": "stale r",
    "assumption_is_fundamental": True,
}

_MAX_COUNT_TEXTS = [
    "alpha membrane channel governs sodium",
    "bravo cytokine triggers inflammation cascade",
    "charlie enzyme catalyzes lipid breakdown",
    "delta receptor binds dopamine selectively",
    "echo transporter shuttles glucose intracellularly",
]

# Ratings for _MAX_COUNT_TEXTS, deliberately ascending: the top-2 by Elo are
# the last two entries, so a test asserting "the top-2 were evolved" fails if
# the pool is sliced in list order rather than ranked.
_MAX_COUNT_ELOS = [1000, 1100, 1200, 1300, 1400]

# Two more disjoint-vocabulary ideas that rank below _MAX_COUNT_TEXTS, used
# to build seven-hypothesis pools for the fixed top-5 selection tests.
_EXTRA_TEXTS = [
    "foxtrot scaffold stabilizes microtubule assembly",
    "golf ligand quenches reactive oxygen species",
]

# A distinct, disjoint evolved text per top-5 original so neither the
# unchanged guard nor the near-duplicate guard fires.
_TOP_FIVE_EVOLVED = {
    "alpha membrane channel governs sodium": (
        "hotel peptide blocks vesicle fusion irreversibly"
    ),
    "bravo cytokine triggers inflammation cascade": (
        "india cofactor rescues folding intermediates rapidly"
    ),
    "charlie enzyme catalyzes lipid breakdown": (
        "juliet chaperone prevents aggregation of nascent chains"
    ),
    "delta receptor binds dopamine selectively": (
        "kilo antisense oligo silences the splice variant cleanly"
    ),
    "echo transporter shuttles glucose intracellularly": (
        "lima nanoparticle ferries the payload across the membrane"
    ),
}

# The same, for the two ideas that survive the gates in the rankable-parent
# test: "charlie" (Elo 1100) and "delta" (Elo 1300).
_SURVIVOR_EVOLVED = {
    "charlie enzyme catalyzes lipid breakdown": (
        "hotel peptide blocks vesicle fusion"
    ),
    "delta receptor binds dopamine selectively": (
        "india cofactor rescues folding intermediates"
    ),
}


def _children(result: dict[str, Any]) -> list[Hypothesis]:
    """Return the evolution children an evolve_node result would append."""
    return list(result["hypotheses"].items)


def _assert_fresh_immutable_child(
    child: Hypothesis, parent: Hypothesis
) -> None:
    """A child is a fresh, immutable entrant linked to its parent."""
    assert child.id != parent.id
    assert child.parent_id == parent.id
    assert child.generation == 1
    assert child.origin is HypothesisOrigin.EVOLUTION
    assert child.elo_rating == INITIAL_ELO_RATING
    assert child.win_count == 0 and child.loss_count == 0
    assert child.reviews == []


class _ExpectedTransformation(NamedTuple):
    """The text an evolution detail is expected to record."""

    original: str
    evolved: str
    rationale: str


def _assert_single_evolution_detail(
    result: dict[str, Any],
    *,
    parent: Hypothesis,
    child: Hypothesis,
    expected: _ExpectedTransformation,
) -> None:
    """The lone evolution detail records the parent->child transformation."""
    details = result["evolution_details"]
    assert len(details) == 1
    assert details[0]["parent_id"] == parent.id
    assert details[0]["child_id"] == child.id
    assert details[0]["original"] == expected.original
    assert details[0]["evolved"] == expected.evolved
    assert details[0]["rationale"] == expected.rationale


def _make_top_k_builder(
    evolved_by_original: dict[str, str],
) -> Callable[[str], dict[str, Any]]:
    """Map a prompt to a response by matching the primary-slot original."""

    def builder(prompt: str) -> dict[str, Any]:
        # Match the primary slot (A.6 names it "Original Conceptualization"),
        # not the truncated block where every sibling original also appears.
        for original, evolved in evolved_by_original.items():
            slots = ("**Original Hypothesis:**", "Original Conceptualization:")
            if any(f"{slot}\n{original}" in prompt for slot in slots):
                return {
                    "hypothesis": evolved,
                    "refinement_summary": f"refined: {evolved}",
                }
        raise AssertionError("evolution called for a non-top-k hypothesis")

    return builder


def _stub_llm_from_prompt(
    monkeypatch: pytest.MonkeyPatch, builder: Callable[[str], dict[str, Any]]
) -> None:
    """Patch call_llm_json to derive each response from the prompt.

    The prompt embeds ``original_hypothesis``; ``builder`` maps the prompt text
    to a response dict, letting parallel evolutions return distinct text.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        builder: Callable taking the prompt string and returning a response.
    """

    async def fake(*, prompt: str, **_: Any) -> dict[str, Any]:
        return builder(prompt)

    monkeypatch.setattr(evolve, "call_llm_json", fake)


async def test_evolution_produces_evolved_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canned response yields an evolved hypothesis and an evolution detail.

    The evolved hypothesis must take its text/explanation/experiment from the
    stub, and ``evolution_details`` must record the original->evolved
    transformation with the stub's refinement summary as the rationale.
    """
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        explanation="old explanation",
        experiment="old experiment",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, _RAPAMYCIN_RESPONSE)

    result = await evolve_node(state)

    children = _children(result)
    assert len(children) == 1
    child = children[0]
    assert child.text == "rapamycin suppresses mtor signaling downstream"
    assert child.explanation == "fresh layman walkthrough"
    assert child.experiment == "knock down the kinase and measure growth"
    _assert_fresh_immutable_child(child, original)
    # The child's history records the parent's text; the parent is untouched.
    assert "quercetin inhibits aldolase activity" in child.evolution_history
    assert original.text == "quercetin inhibits aldolase activity"
    assert original.elo_rating == INITIAL_ELO_RATING

    _assert_single_evolution_detail(
        result,
        parent=original,
        child=child,
        expected=_ExpectedTransformation(
            original="quercetin inhibits aldolase activity",
            evolved="rapamycin suppresses mtor signaling downstream",
            rationale="pivoted to a kinase mechanism",
        ),
    )


async def test_evolution_child_starts_without_deep_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An evolution child is a fresh entrant with no deep-verification state.

    The child describes new text, so it starts with no probes/verdict and must
    be verified afresh. The parent keeps its own probes, untouched.
    """
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        deep_verification_probes=[_STALE_PROBE],
        deep_verification_verdict="holds",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, _RAPAMYCIN_RESPONSE)

    result = await evolve_node(state)

    child = _children(result)[0]
    assert child.text == "rapamycin suppresses mtor signaling downstream"
    assert child.deep_verification_probes == []
    assert child.deep_verification_verdict is None
    # The parent's own probes are untouched.
    assert original.deep_verification_probes == [_STALE_PROBE]
    assert original.deep_verification_verdict == "holds"


async def test_evolution_noop_produces_no_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unchanged refinement creates NO child and leaves the parent intact.

    When the LLM returns no change, evolve_single_hypothesis rejects it: no
    child is minted, and the parent (with its probes) is untouched.
    """
    probes = [
        {
            "question": "q",
            "answer": "a",
            "reasoning": "r",
            "assumption_is_fundamental": False,
        }
    ]
    original = make_hypothesis(
        text="osmotic gradient drives water flux",
        deep_verification_probes=probes,
        deep_verification_verdict="holds",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(
        monkeypatch, evolve, {}
    )  # empty -> unchanged -> no child

    result = await evolve_node(state)

    assert _children(result) == []  # no fake child minted
    # The parent is untouched, probes intact.
    assert original.deep_verification_probes == probes
    assert original.deep_verification_verdict == "holds"


async def test_evolution_breeds_the_paper_fixed_top_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evolution breeds the top-5 ranked hypotheses, not a tier-scaled set.

    Seven disjoint-vocabulary hypotheses must yield exactly five evolved
    children; the two lowest-ranked ideas are never bred. The strongest five
    sit at the *end* of the input list, so "top" can only mean the Elo
    ranking -- read off the first five positions this passes whatever the
    ratings say.
    """
    texts = [*_MAX_COUNT_TEXTS, _EXTRA_TEXTS[0], _EXTRA_TEXTS[1]]
    elos = [*_MAX_COUNT_ELOS, 900, 800]  # the extras rank below the five
    hypotheses = [
        make_hypothesis(text=text, elo_rating=elo)
        for text, elo in zip(texts, elos, strict=True)
    ]
    state = make_state(hypotheses=hypotheses)
    _stub_llm_from_prompt(monkeypatch, _make_top_k_builder(_TOP_FIVE_EVOLVED))

    result = await evolve_node(state)

    children = _children(result)
    assert len(children) == 5
    assert len(result["evolution_details"]) == 5
    evolved_texts = {h.text for h in children}
    assert evolved_texts == set(_TOP_FIVE_EVOLVED.values())
    top_five_ids = {hypotheses[i].id for i in range(5)}
    assert {c.parent_id for c in children} == top_five_ids


async def test_evolution_ignores_the_tier_scaled_evolution_max_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The state's evolution_max_count no longer sizes the parent set.

    Regression guard: a tier-scaled envelope (4/8/12/16) once decided how
    many parents were bred; the parent set is the paper's fixed top-5, so a
    pool of five rankable ideas yields five children even when the state
    still carries a smaller legacy value.
    """
    hypotheses = [
        make_hypothesis(text=text, elo_rating=elo)
        for text, elo in zip(_MAX_COUNT_TEXTS, _MAX_COUNT_ELOS, strict=True)
    ]
    state = make_state(hypotheses=hypotheses, evolution_max_count=1)
    _stub_llm_from_prompt(monkeypatch, _make_top_k_builder(_TOP_FIVE_EVOLVED))

    result = await evolve_node(state)

    assert len(_children(result)) == 5


async def test_evolution_small_pool_breeds_every_rankable_idea(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fewer than five rankable hypotheses evolve all of them.

    Express-tier runs can hold fewer than five ideas; the slice then returns
    every rankable hypothesis rather than padding or failing.
    """
    state = make_state(
        hypotheses=[
            make_hypothesis(text=_MAX_COUNT_TEXTS[0], elo_rating=1200),
            make_hypothesis(text=_MAX_COUNT_TEXTS[1], elo_rating=1100),
        ]
    )
    _stub_llm_from_prompt(
        monkeypatch,
        _make_top_k_builder(
            {
                _MAX_COUNT_TEXTS[0]: _TOP_FIVE_EVOLVED[_MAX_COUNT_TEXTS[0]],
                _MAX_COUNT_TEXTS[1]: _TOP_FIVE_EVOLVED[_MAX_COUNT_TEXTS[1]],
            }
        ),
    )

    result = await evolve_node(state)

    assert len(_children(result)) == 2


async def test_evolution_parents_are_ranked_survivors_not_the_list_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disqualified ideas at the head of an unsorted pool are not bred.

    Evolution is entered from meta_review, which returns no ``hypotheses``
    key, and the two ranking early-exits (fewer than two rankable ideas; the
    whole-run tournament budget spent) both hand the pool back untouched --
    so the pool routinely reaches evolution unsorted. Here the two ideas the
    review gate rejected lead the list and outrank the survivors on Elo, and
    the only two viable ideas trail it. Slicing the head bred the two
    rejected ideas and never touched the survivors, which surfaces as the
    run's ideas being repetitive rather than as its parents being wrong.
    """
    rejected = [
        make_hypothesis(text=text, elo_rating=1500)
        for text in _MAX_COUNT_TEXTS[:2]
    ]
    for hypothesis in rejected:
        hypothesis.review_disposition = "non_novel"
    survivors = [
        make_hypothesis(text=text, elo_rating=elo)
        for text, elo in zip(_MAX_COUNT_TEXTS[2:4], (1100, 1300), strict=True)
    ]
    undermined = make_hypothesis(text=_MAX_COUNT_TEXTS[4], elo_rating=1490)
    undermined.deep_verification_verdict = "undermined"

    state = make_state(
        hypotheses=[*rejected, undermined, *survivors],
        evolution_max_count=2,
    )
    _stub_llm_from_prompt(monkeypatch, _make_top_k_builder(_SURVIVOR_EVOLVED))

    # Asserted on the selection itself so a regression names the parents it
    # picked, not just the stub guard the wrong parent trips downstream.
    parents = _select_evolution_pool(state["hypotheses"])
    assert [h.text for h in parents] == [survivors[1].text, survivors[0].text]

    result = await evolve_node(state)

    children = _children(result)
    assert {c.parent_id for c in children} == {h.id for h in survivors}
    assert len(children) == 2


async def test_evolution_breeds_nothing_when_no_idea_is_rankable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An all-disqualified pool yields no parents rather than bad ones.

    A rejected idea is barred from the tournament and dropped from the
    report, so breeding one spends a model call on a lineage the run has
    already ruled out. Generation, which the orchestrator can still
    schedule, is the recovery path -- not evolution.
    """
    hypotheses = [make_hypothesis(text=text) for text in _MAX_COUNT_TEXTS[:3]]
    for hypothesis in hypotheses:
        hypothesis.review_disposition = "inaccurate"
    state = make_state(hypotheses=hypotheses, evolution_max_count=3)
    _stub_llm_from_prompt(monkeypatch, _make_top_k_builder({}))

    result = await evolve_node(state)

    assert _children(result) == []
    assert result["evolution_details"] == []


async def test_empty_hypotheses_returns_no_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no hypotheses, node returns no children without calling LLM."""

    async def never(**_: Any) -> dict[str, Any]:
        raise AssertionError("call_llm_json must not run with no hypotheses")

    monkeypatch.setattr(evolve, "call_llm_json", never)
    state = make_state(hypotheses=[], evolution_max_count=3)

    result = await evolve_node(state)

    assert _children(result) == []
    assert result["evolution_details"] == []


async def test_unchanged_response_records_no_child_or_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An LLM response echoing the original text creates no child or detail.

    Because the refined text equals the original, ``evolve_single_hypothesis``
    rejects it: no child is appended and ``evolution_details`` is empty. The
    parent stays in the pool untouched.
    """
    original = make_hypothesis(text="osmotic gradient drives water flux")
    state = make_state(hypotheses=[original], evolution_max_count=1)
    # Empty response -> ``hypothesis`` key missing, so the parser falls back to
    # the original text, which trips the unchanged-guard.
    stub_call_llm_json(monkeypatch, evolve, {})

    result = await evolve_node(state)

    assert _children(result) == []
    assert result["evolution_details"] == []
    assert original.text == "osmotic gradient drives water flux"


async def test_duplicate_guard_sees_ideas_outside_the_evolution_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child duplicating any pool member is rejected, not just a top-k one.

    ``other_hypotheses`` is the near-duplicate rejection set (see
    ``_apply_evolution_result``), so anything absent from it is something a
    child may freely re-derive. Scoping it to the hypotheses being evolved
    this round left the guard blind to the rest of the pool: the child
    passed here and proximity archived it afterwards, which is how a run
    ends up showing a dozen near-identical ideas.
    """
    outsider_text = "rapamycin suppresses mtor signaling downstream"
    # Ranks below the cap, so it is never itself evolved -- but the child
    # below reproduces it verbatim.
    hypotheses = [
        make_hypothesis(text="parent idea about oxidative stress"),
        make_hypothesis(text=outsider_text),
    ]
    state = make_state(hypotheses=hypotheses, evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, _RAPAMYCIN_RESPONSE)

    result = await evolve_node(state)

    assert _children(result) == []


# --- _sample_up_to -----------------------------------------------------------


def test_sample_up_to_empty_pool_returns_empty() -> None:
    """An empty pool returns an empty list without consuming random state."""
    assert _sample_up_to([], 5, random.Random(1)) == []


def test_sample_up_to_returns_requested_count() -> None:
    """A pool larger than count returns exactly count items, all from pool."""
    pool = [make_hypothesis(text=f"h{i}") for i in range(20)]
    sampled = _sample_up_to(pool, 10, random.Random(1))
    assert len(sampled) == 10
    assert all(h in pool for h in sampled)


def test_sample_up_to_caps_at_pool_size() -> None:
    """Requesting more than the pool holds returns the whole pool."""
    pool = [make_hypothesis(text=f"h{i}") for i in range(3)]
    sampled = _sample_up_to(pool, 10, random.Random(1))
    assert len(sampled) == 3


def test_sample_up_to_is_reproducible_under_its_seed() -> None:
    """The same seed draws the same sample; a run's context is stable."""
    pool = [make_hypothesis(text=f"h{i}") for i in range(20)]
    first = _sample_up_to(pool, 10, random.Random("run-seed"))
    again = _sample_up_to(pool, 10, random.Random("run-seed"))
    assert first == again


# --- sample_context_hypotheses: large-pool branch ---------------------------


def test_sample_context_hypotheses_large_pool_caps_at_max_context() -> None:
    """With more than max_context others, sampling caps at top-5 + 10 random.

    Twenty other hypotheses with distinct, descending Elo ratings exceed the
    default max_context of 15, forcing the top-5-plus-random-sample branch
    (and, transitively, _sample_up_to) that a small pool never reaches.
    """
    exclude = make_hypothesis(text="the hypothesis being evolved")
    others = [
        make_hypothesis(text=f"other hypothesis {i}", elo_rating=2000 - i)
        for i in range(20)
    ]
    all_hypotheses = [exclude, *others]

    result = sample_context_hypotheses(
        all_hypotheses,
        exclude_hypothesis=exclude,
        max_context=15,
        rng=random.Random(7),
    )

    # Top 5 (highest Elo: others[0..4]) + 10 randomly sampled from the
    # remaining 15 = 15 total, returned as hypothesis objects.
    assert len(result) == 15
    top_five_texts = {h.text for h in others[:5]}
    assert top_five_texts.issubset({h.text for h in result})
    # Every returned hypothesis belongs to the "others" pool, never the
    # excluded hypothesis itself.
    assert all(h.text != exclude.text for h in result)


def test_sample_context_hypotheses_seeded_draws_are_reproducible() -> None:
    """Equal seeds sample equal contexts; the diversity check is stable."""
    exclude = make_hypothesis(text="excluded")
    others = [
        make_hypothesis(text=f"other {i}", elo_rating=100 - i)
        for i in range(30)
    ]
    pool = [exclude, *others]

    first = sample_context_hypotheses(
        pool, exclude_hypothesis=exclude, rng=random.Random("seed-A")
    )
    again = sample_context_hypotheses(
        pool, exclude_hypothesis=exclude, rng=random.Random("seed-A")
    )
    assert first == again


def test_sample_context_hypotheses_small_pool_returns_all() -> None:
    """With others <= max_context, every other hypothesis is included."""
    exclude = make_hypothesis(text="excluded")
    others = [make_hypothesis(text=f"other {i}") for i in range(3)]
    result = sample_context_hypotheses(
        [exclude, *others], exclude_hypothesis=exclude, max_context=15
    )
    assert {h.text for h in result} == {h.text for h in others}


# --- combination_partners ----------------------------------------------------


def test_combination_partners_are_the_top_ranked_peers() -> None:
    """Partners are the strongest peers other than the parent, in order."""
    pool = [
        make_hypothesis(text=f"idea {i}", elo_rating=rating)
        for i, rating in enumerate((1100, 1500, 1300, 1200))
    ]
    ranked = rank_by_elo(pool)
    parent = pool[1]  # the strongest idea: partners are the next two

    partners = combination_partners(ranked, parent)

    assert [p.text for p in partners] == ["idea 2", "idea 3"]


def test_combination_partners_empty_for_a_one_idea_pool() -> None:
    """A pool holding only the parent offers no partners."""
    parent = make_hypothesis(text="the only idea")
    assert combination_partners([parent], parent) == []


# --- token_coverage ----------------------------------------------------------


def test_token_coverage_empty_text_returns_zero() -> None:
    """An empty derived text has no tokens to cover; coverage is 0.0."""
    assert token_coverage("", "some hypothesis text") == 0.0


def test_token_coverage_full_containment_scores_one() -> None:
    """A text whose tokens all appear in the peer is fully covered."""
    assert token_coverage("alpha beta", "alpha beta gamma delta") == 1.0


def test_token_coverage_is_not_dominated_by_peer_length() -> None:
    """Coverage divides by the derived text's tokens, never the union.

    The Jaccard this replaced scored the same pair near
    len(claim) / len(document) however perfectly the peer contained the
    text, which is how both duplicate bands became unreachable.
    """
    short = "alpha beta"
    long_peer = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    # Contained short text: coverage stays 1.0 at any peer length.
    assert token_coverage(short, long_peer) == 1.0
    # A long refinement reusing a short peer's words is not its duplicate.
    assert token_coverage(long_peer, short) < 0.5


def test_token_coverage_partial_overlap() -> None:
    """Coverage reflects the fraction of the derived text's own tokens."""
    assert token_coverage("alpha beta gamma", "alpha beta delta") == 2 / 3


# --- find_nearest_peer -------------------------------------------------------


def test_find_nearest_peer_empty_candidates_returns_none() -> None:
    """No candidate peers yields (0.0, None)."""
    assert find_nearest_peer("alpha beta", "parent-id", []) == (0.0, None)


def test_find_nearest_peer_falls_back_to_token_coverage() -> None:
    """Without a proximity edge the lexical fallback decides."""
    refined = "alpha beta gamma delta"
    peers = [
        make_hypothesis(text="completely unrelated text"),
        make_hypothesis(text="alpha beta gamma epsilon"),
    ]
    similarity, nearest = find_nearest_peer(refined, "parent-id", peers)
    assert nearest is peers[1]
    assert similarity == 3 / 4


def test_find_nearest_peer_prefers_the_proximity_graph_weight() -> None:
    """A persisted parent-neighbor edge outranks the lexical estimate."""
    refined = "alpha beta gamma delta"
    lexical_peer = make_hypothesis(text="alpha beta gamma epsilon")
    graph_peer = make_hypothesis(text="a disjoint wording entirely")
    graph = {
        "edges": [
            {
                "source": "parent-id",
                "target": graph_peer.id,
                "similarity": 1.0,
            }
        ]
    }
    similarity, nearest = find_nearest_peer(
        refined, "parent-id", [lexical_peer, graph_peer], graph
    )
    assert nearest is graph_peer
    assert similarity == 1.0


def test_find_nearest_peer_reads_both_edge_orientations() -> None:
    """The graph is undirected: target->source edges resolve too."""
    graph_peer = make_hypothesis(text="a disjoint wording entirely")
    graph = {
        "edges": [
            {
                "source": graph_peer.id,
                "target": "parent-id",
                "similarity": 0.6,
            }
        ]
    }
    similarity, nearest = find_nearest_peer(
        "refined wording", "parent-id", [graph_peer], graph
    )
    assert nearest is graph_peer
    assert similarity == 0.6


def _feedback_state(hypothesis: Hypothesis) -> WorkflowState:
    """Build a state carrying debate, tournament, and proximity feedback."""
    return make_state(
        hypotheses=[hypothesis],
        debate_transcripts=[
            {
                "debate_id": 3,
                "hypothesis_text": hypothesis.text,
                "transcript": "Skeptic requests a rescue experiment.",
            }
        ],
        tournament_matchups=[
            {
                "hypothesis_a_id": hypothesis.id,
                "hypothesis_b_id": "peer",
                "winner_id": "peer",
                "reasoning": "The peer has stronger causal controls.",
                "confidence": "high",
            }
        ],
        proximity_graph={
            "edges": [
                {
                    "source": hypothesis.id,
                    "target": "neighbor",
                    "similarity": 0.72,
                    "cluster_id": "c1",
                }
            ]
        },
    )


def test_specialist_feedback_joins_prior_agent_outputs() -> None:
    """Evolution receives debate, tournament, proximity, and probe feedback."""
    hypothesis = make_hypothesis(
        text="mitochondrial checkpoint controls neuronal aging",
        deep_verification_verdict="partially_holds",
        deep_verification_probes=[
            {"question": "Is it causal?", "answer": "Unknown"}
        ],
    )
    hypothesis.enrichments["claim_gate"] = {
        "decision": "block",
        "reason": "one causal claim lacks support",
    }
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    assert "rescue experiment" in feedback
    assert "stronger causal controls" in feedback
    assert '"outcome": "lost"' in feedback
    assert '"hypothesis_id": "neighbor"' in feedback
    assert "partially_holds" in feedback
    assert "one causal claim lacks support" in feedback


def test_specialist_feedback_carries_mature_review_findings() -> None:
    """The parent's full/simulation reviews steer evolution (audit E1).

    A fatal finding on the parent is exactly the weakness the child must
    refine away, so its verdict and findings join the specialist ledger.
    """
    hypothesis = make_hypothesis(text="a hypothesis with mature reviews")
    hypothesis.enrichments["full"] = {
        "verdict": "rejected",
        "justification": "circular pathway",
        "retrieved_articles": [{"title": "not for the ledger"}],
    }
    hypothesis.enrichments["simulation"] = {
        "verdict": "breaks_down",
        "decisive_step": "binding fails",
        "failure_points": ["step two"],
    }
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    ledger = json.loads(feedback)
    assert ledger["mature_reviews"]["full"]["verdict"] == "rejected"
    assert ledger["mature_reviews"]["full"]["justification"] == (
        "circular pathway"
    )
    assert ledger["mature_reviews"]["simulation"]["verdict"] == "breaks_down"
    # Retrieval bookkeeping stays out of the prompt context.
    assert "retrieved_articles" not in feedback


def test_specialist_feedback_omits_mature_reviews_before_the_cascade() -> None:
    """No mature review has run -> no "mature_reviews" key at all.

    Same omit-rather-than-hollow convention as deep verification: a
    present-but-empty block would read as "reviewed, nothing found".
    """
    hypothesis = make_hypothesis(text="a hypothesis awaiting review")
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    assert "mature_reviews" not in json.loads(feedback)


def test_specialist_feedback_omits_deep_verification_before_it_has_run() -> (
    None
):
    """No deep-verification probes yet -> no "deep_verification" key at all.

    Regression guard: deep verification only reaches the tournament's
    leaders, so most hypotheses reach evolution before it has run. The
    ledger used to include an unconditional ``{"verdict": None, "probes":
    []}`` block for these -- indistinguishable from "checked, nothing
    found" -- instead of omitting the key the way the ranking-matchup
    prompt's equivalent projection already did.
    """
    hypothesis = make_hypothesis(text="a hypothesis awaiting verification")
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    assert "deep_verification" not in json.loads(feedback)


async def test_evolution_child_takes_the_response_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canned response's title reaches the child, not the parent's."""
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        title="Quercetin Blockade of Aldolase",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(
        monkeypatch,
        evolve,
        {**_RAPAMYCIN_RESPONSE, "title": "Rapamycin-Driven mTOR Suppression"},
    )

    result = await evolve_node(state)

    child = _children(result)[0]
    assert child.title == "Rapamycin-Driven mTOR Suppression"
    assert original.title == "Quercetin Blockade of Aldolase"


async def test_evolution_child_title_is_none_when_response_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing title is left None, not inherited from the parent.

    The child's mechanism may have changed, so reusing the parent's
    (now possibly stale) title would misname it; the app's drain derives a
    fallback from the child's own refined text instead (R14-12).
    """
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        title="Quercetin Blockade of Aldolase",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, _RAPAMYCIN_RESPONSE)

    result = await evolve_node(state)

    child = _children(result)[0]
    assert child.title is None

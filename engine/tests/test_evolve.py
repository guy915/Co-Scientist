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

# Disjoint vocabulary avoids unchanged and near-duplicate guards.
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

# Ascending ratings put the strongest ideas last, exposing list-order slicing.
_MAX_COUNT_ELOS = [1000, 1100, 1200, 1300, 1400]

_EXTRA_TEXTS = [
    "foxtrot scaffold stabilizes microtubule assembly",
    "golf ligand quenches reactive oxygen species",
]

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

_SURVIVOR_EVOLVED = {
    "charlie enzyme catalyzes lipid breakdown": (
        "hotel peptide blocks vesicle fusion"
    ),
    "delta receptor binds dopamine selectively": (
        "india cofactor rescues folding intermediates"
    ),
}


def _children(result: dict[str, Any]) -> list[Hypothesis]:
    return list(result["hypotheses"].items)


def _assert_fresh_immutable_child(
    child: Hypothesis, parent: Hypothesis
) -> None:
    assert child.id != parent.id
    assert child.parent_id == parent.id
    assert child.generation == 1
    assert child.origin is HypothesisOrigin.EVOLUTION
    assert child.elo_rating == INITIAL_ELO_RATING
    assert child.win_count == 0 and child.loss_count == 0
    assert child.reviews == []


class _ExpectedTransformation(NamedTuple):
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

    def builder(prompt: str) -> dict[str, Any]:
        # Match the primary slot; the truncated context also contains sibling
        # originals.
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

    async def fake(*, prompt: str, **_: Any) -> dict[str, Any]:
        return builder(prompt)

    monkeypatch.setattr(evolve, "call_llm_json", fake)


async def test_evolution_produces_evolved_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tournament entrants require completed review stamps."""
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
    """Changed text invalidates the parent's verification probes."""
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
    assert original.deep_verification_probes == [_STALE_PROBE]
    assert original.deep_verification_verdict == "holds"


async def test_evolution_noop_produces_no_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    stub_call_llm_json(monkeypatch, evolve, {})

    result = await evolve_node(state)

    assert _children(result) == []
    assert original.deep_verification_probes == probes
    assert original.deep_verification_verdict == "holds"


async def test_evolution_breeds_the_paper_fixed_top_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texts = [*_MAX_COUNT_TEXTS, _EXTRA_TEXTS[0], _EXTRA_TEXTS[1]]
    elos = [*_MAX_COUNT_ELOS, 900, 800]
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
    """Meta-review and early ranking returns can leave the pool unsorted."""
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
    """Tournament entrants require completed review stamps."""

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
    original = make_hypothesis(text="osmotic gradient drives water flux")
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, {})

    result = await evolve_node(state)

    assert _children(result) == []
    assert result["evolution_details"] == []
    assert original.text == "osmotic gradient drives water flux"


async def test_duplicate_guard_sees_ideas_outside_the_evolution_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exclusion guard needs the entire pool, including excluded parents."""
    outsider_text = "rapamycin suppresses mtor signaling downstream"
    hypotheses = [
        make_hypothesis(text="parent idea about oxidative stress"),
        make_hypothesis(text=outsider_text),
    ]
    state = make_state(hypotheses=hypotheses, evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, _RAPAMYCIN_RESPONSE)

    result = await evolve_node(state)

    assert _children(result) == []


def test_sample_up_to_empty_pool_returns_empty() -> None:
    assert _sample_up_to([], 5, random.Random(1)) == []


def test_sample_up_to_returns_requested_count() -> None:
    pool = [make_hypothesis(text=f"h{i}") for i in range(20)]
    sampled = _sample_up_to(pool, 10, random.Random(1))
    assert len(sampled) == 10
    assert all(h in pool for h in sampled)


def test_sample_up_to_caps_at_pool_size() -> None:
    pool = [make_hypothesis(text=f"h{i}") for i in range(3)]
    sampled = _sample_up_to(pool, 10, random.Random(1))
    assert len(sampled) == 3


def test_sample_up_to_is_reproducible_under_its_seed() -> None:
    pool = [make_hypothesis(text=f"h{i}") for i in range(20)]
    first = _sample_up_to(pool, 10, random.Random("run-seed"))
    again = _sample_up_to(pool, 10, random.Random("run-seed"))
    assert first == again


def test_sample_context_hypotheses_large_pool_caps_at_max_context() -> None:
    """Tournament entrants require completed review stamps."""
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

    assert len(result) == 15
    top_five_texts = {h.text for h in others[:5]}
    assert top_five_texts.issubset({h.text for h in result})
    assert all(h.text != exclude.text for h in result)


def test_sample_context_hypotheses_seeded_draws_are_reproducible() -> None:
    """Tournament entrants require completed review stamps."""
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
    """Tournament entrants require completed review stamps."""
    exclude = make_hypothesis(text="excluded")
    others = [make_hypothesis(text=f"other {i}") for i in range(3)]
    result = sample_context_hypotheses(
        [exclude, *others], exclude_hypothesis=exclude, max_context=15
    )
    assert {h.text for h in result} == {h.text for h in others}


def test_combination_partners_are_the_top_ranked_peers() -> None:
    pool = [
        make_hypothesis(text=f"idea {i}", elo_rating=rating)
        for i, rating in enumerate((1100, 1500, 1300, 1200))
    ]
    ranked = rank_by_elo(pool)
    parent = pool[1]

    partners = combination_partners(ranked, parent)

    assert [p.text for p in partners] == ["idea 2", "idea 3"]


def test_combination_partners_empty_for_a_one_idea_pool() -> None:
    parent = make_hypothesis(text="the only idea")
    assert combination_partners([parent], parent) == []


def test_token_coverage_empty_text_returns_zero() -> None:
    assert token_coverage("", "some hypothesis text") == 0.0


def test_token_coverage_full_containment_scores_one() -> None:
    assert token_coverage("alpha beta", "alpha beta gamma delta") == 1.0


def test_token_coverage_is_not_dominated_by_peer_length() -> None:
    """Jaccard makes full containment in a longer peer unreachable."""
    short = "alpha beta"
    long_peer = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    assert token_coverage(short, long_peer) == 1.0
    assert token_coverage(long_peer, short) < 0.5


def test_token_coverage_partial_overlap() -> None:
    assert token_coverage("alpha beta gamma", "alpha beta delta") == 2 / 3


def test_find_nearest_peer_empty_candidates_returns_none() -> None:
    assert find_nearest_peer("alpha beta", "parent-id", []) == (0.0, None)


def test_find_nearest_peer_falls_back_to_token_coverage() -> None:
    refined = "alpha beta gamma delta"
    peers = [
        make_hypothesis(text="completely unrelated text"),
        make_hypothesis(text="alpha beta gamma epsilon"),
    ]
    similarity, nearest = find_nearest_peer(refined, "parent-id", peers)
    assert nearest is peers[1]
    assert similarity == 3 / 4


def test_find_nearest_peer_prefers_the_proximity_graph_weight() -> None:
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
    assert "retrieved_articles" not in feedback


def test_specialist_feedback_omits_mature_reviews_before_the_cascade() -> None:
    """An empty block would falsely imply that mature reviews checked
    nothing."""
    hypothesis = make_hypothesis(text="a hypothesis awaiting review")
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    assert "mature_reviews" not in json.loads(feedback)


def test_specialist_feedback_omits_deep_verification_before_it_has_run() -> (
    None
):
    """An empty block would falsely imply that verification checked nothing."""
    hypothesis = make_hypothesis(text="a hypothesis awaiting verification")
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    assert "deep_verification" not in json.loads(feedback)


async def test_evolution_child_takes_the_response_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    """Changed mechanisms cannot inherit stale parent titles; the app
    resolves fallback."""
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        title="Quercetin Blockade of Aldolase",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, _RAPAMYCIN_RESPONSE)

    result = await evolve_node(state)

    child = _children(result)[0]
    assert child.title is None

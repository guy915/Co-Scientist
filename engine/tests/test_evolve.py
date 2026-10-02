"""Tests for evolve_node: immutable-child refinement of the top hypotheses.

The node's only external dependency is a per-hypothesis ``call_llm_json`` call
that returns the refined hypothesis. These tests stub that out and assert on the
deterministic top-5 parent selection, the construction of immutable child
Hypothesis objects (new id, parent link, Elo 1200, zero matches) from the canned
response, and the recorded ``evolution_details``.

evolve_node returns ``{"hypotheses": AppendHypotheses(children), ...}``: the
children are APPENDED to the pool by the reducer, and the parents are left
unchanged (paper invariant SSR §4, §12). Use ``_children`` to unwrap them.

To keep the stub's evolved text below the near-duplicate guard
(``DUPLICATE_SIMILARITY_THRESHOLD``) and distinct from each original, the input
hypotheses and the canned responses use disjoint vocabularies.
"""

from collections.abc import Callable
from typing import Any, NamedTuple

import pytest

from co_scientist.agents.evolution import evolve
from co_scientist.agents.evolution.evolve import evolve_node
from co_scientist.agents.evolution.evolve_round import _select_evolution_pool
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import Hypothesis, HypothesisOrigin
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

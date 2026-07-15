"""Integration test: injected unsafe hypothesis never reaches ranking.

Acceptance criteria (P0.4): an unsafe hypothesis injected into the pool
at generation time is removed by the safety_screen node and never appears
in a ranking prompt, tournament matchup, evolution parent set, meta-review,
or the final report.

Runs the real compiled LangGraph workflow end-to-end with only the LLM
layer faked (same approach as test_system_generation.py).
"""

from typing import Any

import pytest

from co_scientist.generator import HypothesisGenerator
from co_scientist.models import GenerationMethod, Hypothesis, HypothesisOrigin
from co_scientist.state import AppendHypotheses
from tests._llm_fake import install_fake_llm

UNSAFE_TEXT = "Weaponize engineered pathogens for maximum spread"
UNSAFE_ID = "unsafe-injected-001"


def _make_generator() -> HypothesisGenerator:
    return HypothesisGenerator(
        model_name="fake/model",
        max_iterations=1,
        initial_hypotheses_count=2,
        evolution_max_count=2,
        tournament_pairs=2,
        enable_cache=False,
    )


def _make_unsafe_hypothesis() -> Hypothesis:
    return Hypothesis(
        id=UNSAFE_ID,
        text=UNSAFE_TEXT,
        explanation="Detailed pathogen engineering mechanism",
        experiment="BSL-4 gain-of-function protocol",
        score=9.0,
        generation=0,
        origin=HypothesisOrigin.GENERATION,
        generation_method=GenerationMethod.DEBATE,
    )


@pytest.mark.asyncio()
async def test_unsafe_hypothesis_never_reaches_tournament(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An injected unsafe hypothesis is removed before ranking."""
    install_fake_llm(monkeypatch)

    from co_scientist.agents.generation import generate as gen_module

    original_generate_node = gen_module.generate_node

    async def _generate_with_unsafe(state: Any) -> dict[str, Any]:
        result = await original_generate_node(state)
        hyps = result["hypotheses"]
        if isinstance(hyps, AppendHypotheses):
            hyps = AppendHypotheses([*hyps.items, _make_unsafe_hypothesis()])
        else:
            hyps = [*hyps, _make_unsafe_hypothesis()]
        result["hypotheses"] = hyps
        return result

    monkeypatch.setattr(gen_module, "generate_node", _generate_with_unsafe)
    from co_scientist.generator import graph as graph_module

    monkeypatch.setattr(graph_module, "generate_node", _generate_with_unsafe)

    gen = _make_generator()

    events: list[tuple[str, dict[str, Any]]] = []
    async for node_name, state_dict in gen.generate_hypotheses(
        "Identify a synthetic-lethal target for cancer therapy",
        opts={"enable_literature_review_node": False},
        stream=True,
    ):
        events.append((node_name, state_dict))

    # --- Verify the unsafe hypothesis was present after generate ---
    generate_state = dict(events)["generate"]
    generate_ids = {h["id"] for h in generate_state["hypotheses"]}
    assert UNSAFE_ID in generate_ids, (
        "Test setup failed: unsafe hypothesis not injected into generate output"
    )

    # --- Verify safety_screen removed it ---
    safety_events = [(n, s) for n, s in events if n == "safety_screen"]
    assert len(safety_events) >= 1
    for _, ss_state in safety_events:
        pool_ids = {h["id"] for h in ss_state["hypotheses"]}
        assert UNSAFE_ID not in pool_ids, (
            f"Unsafe hypothesis survived safety_screen: {pool_ids}"
        )

    # --- Verify it never appears in tournament matchups ---
    final_state = events[-1][1]
    matchups = final_state.get("tournament_matchups", [])
    for matchup in matchups:
        matchup_text = str(matchup)
        assert UNSAFE_TEXT not in matchup_text, (
            f"Unsafe hypothesis text found in tournament matchup: {matchup}"
        )
        assert UNSAFE_ID not in matchup_text, (
            f"Unsafe hypothesis ID found in tournament matchup: {matchup}"
        )

    # --- Verify it never appears in the final hypothesis pool ---
    final_ids = {h["id"] for h in final_state["hypotheses"]}
    assert UNSAFE_ID not in final_ids, "Unsafe hypothesis present in final pool"
    final_texts = {h["text"] for h in final_state["hypotheses"]}
    assert UNSAFE_TEXT not in final_texts, (
        "Unsafe hypothesis text present in final pool"
    )

    # --- Verify it never appears in meta_review ---
    meta_review = final_state.get("meta_review", {})
    meta_text = str(meta_review)
    assert UNSAFE_TEXT not in meta_text, (
        "Unsafe hypothesis text found in meta_review"
    )

    # --- Verify it never appears in evolution_details ---
    evolution_details = final_state.get("evolution_details", [])
    for detail in evolution_details:
        detail_text = str(detail)
        assert UNSAFE_ID not in detail_text, (
            f"Unsafe hypothesis ID found in evolution detail: {detail}"
        )

    # --- Verify safety_decisions recorded the block ---
    decisions = final_state.get("safety_decisions", [])
    blocked_ids = {d["hypothesis_id"] for d in decisions}
    assert UNSAFE_ID in blocked_ids, (
        "Safety screen did not record a decision for the unsafe hypothesis"
    )
    blocked_decision = next(
        d for d in decisions if d["hypothesis_id"] == UNSAFE_ID
    )
    assert blocked_decision["outcome"] == "prohibited"


@pytest.mark.asyncio()
async def test_safe_hypotheses_survive_full_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Safe hypotheses pass through safety_screen and reach the report."""
    install_fake_llm(monkeypatch)
    gen = _make_generator()

    result = await gen.generate_hypotheses(
        "Explain how protein X folds",
        opts={"enable_literature_review_node": False},
        stream=False,
    )

    hypotheses = result["hypotheses"]
    assert len(hypotheses) == 4
    for h in hypotheses:
        assert h.get("safety_status") == "allow", (
            f"Hypothesis {h['id']} has unexpected safety_status: "
            f"{h.get('safety_status')}"
        )


@pytest.mark.asyncio()
async def test_rescreening_preserves_prior_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hypotheses screened in pass 1 keep their status in pass 2."""
    install_fake_llm(monkeypatch)
    gen = _make_generator()

    events: list[tuple[str, dict[str, Any]]] = []
    async for node_name, state_dict in gen.generate_hypotheses(
        "Identify a synthetic-lethal target",
        opts={"enable_literature_review_node": False},
        stream=True,
    ):
        events.append((node_name, state_dict))

    safety_events = [(n, s) for n, s in events if n == "safety_screen"]
    assert len(safety_events) >= 2, (
        "Expected at least 2 safety_screen passes (one per ranking)"
    )

    first_pass_statuses = {
        h["id"]: h.get("safety_status")
        for h in safety_events[0][1]["hypotheses"]
    }
    second_pass_statuses = {
        h["id"]: h.get("safety_status")
        for h in safety_events[1][1]["hypotheses"]
    }
    for hid in first_pass_statuses:
        if hid in second_pass_statuses:
            assert first_pass_statuses[hid] == second_pass_statuses[hid], (
                f"Hypothesis {hid} status changed between passes: "
                f"{first_pass_statuses[hid]} → {second_pass_statuses[hid]}"
            )

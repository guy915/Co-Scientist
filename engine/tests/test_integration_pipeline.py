"""Integration tests: the real compiled LangGraph pipeline, LLM-only mode.

These tests run ``HypothesisGenerator``'s actual compiled ``StateGraph``
end-to-end -- every node (supervisor, generate, review, ranking,
deep_verification, meta_review, evolve, proximity, research_overview)
executes for real, with the LLM layer faked at the ``litellm.acompletion``
boundary (see ``tests/_llm_fake.py``), not by stubbing node functions.
Literature review is explicitly disabled, so the graph runs in LLM-only
fallback mode (no MCP server needed): ``literature_review`` and
``reflection`` are absent from the compiled graph (see
``tests/test_generator.py``'s ``_SIMPLE_NODES``).

Each test builds the initial state via
``HypothesisGenerator._prepare_generation`` and invokes the compiled graph
directly (``gen._graph.ainvoke``), rather than going through the public
``generate_hypotheses`` wrapper -- that system-level entry point is covered
separately in ``tests/test_system_generation.py``. Working at the raw
``WorkflowState`` level here lets these tests assert on the real
``Hypothesis``/``ExecutionMetrics`` objects (Elo ratings, review objects,
evolution history) rather than the serialized dicts the public API returns.
"""

from typing import Any, cast

import pytest

from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.generator import HypothesisGenerator
from co_scientist.state import WorkflowState
from tests._llm_fake import install_fake_llm


async def _run_graph(
    gen: HypothesisGenerator, research_goal: str, **opts: Any
) -> WorkflowState:
    """Prepares the initial state and runs the real graph to completion.

    Args:
        gen: A configured (but not yet run) HypothesisGenerator.
        research_goal: The research question to generate hypotheses for.
        **opts: Extra ``generate_hypotheses``-style opts merged in;
            literature review is disabled unless overridden here.

    Returns:
        The final WorkflowState after the graph run completes.
    """
    initial_state = await gen._prepare_generation(
        research_goal,
        opts={"enable_literature_review_node": False, **opts},
    )
    assert gen._graph is not None  # built by _prepare_generation
    final_state = await gen._graph.ainvoke(
        initial_state, config={"recursion_limit": 100}
    )
    return cast(WorkflowState, final_state)


async def test_single_iteration_pipeline_updates_cross_node_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A max_iterations=1 run touches every node with consistent state.

    Covers the full cycle: supervisor -> generate -> review -> ranking ->
    deep_verification -> meta_review -> evolve -> review -> ranking ->
    deep_verification -> proximity -> research_overview.
    """
    install_fake_llm(monkeypatch)
    gen = HypothesisGenerator(
        model_name="fake/model",
        max_iterations=1,
        initial_hypotheses_count=2,
        evolution_max_count=2,
        tournament_pairs=2,
        enable_cache=False,
    )

    final_state = await _run_graph(gen, "Explain how protein X folds")

    hypotheses = final_state["hypotheses"]
    assert len(hypotheses) == 2

    # Every survivor has distinct text. Note this does not exercise an
    # actual collapse: the fake LLM mints a unique "stub-N" leaf per call,
    # so neither the deduplicate_hypotheses reducer nor proximity's
    # high-similarity removal ever has a real duplicate to collapse here
    # (that path is covered directly by tests/test_state_reducer.py and
    # tests/test_proximity.py); this only confirms the pipeline does not
    # itself introduce a collision.
    texts = [h.text for h in hypotheses]
    assert len(texts) == len(set(texts))

    # Every hypothesis was reviewed twice: once before evolution, once
    # after evolve rewrote its text.
    assert all(len(h.reviews) == 2 for h in hypotheses)

    # The tournament judged matchups and moved Elo off the initial rating.
    assert final_state["tournament_matchups"]
    assert any(h.elo_rating != INITIAL_ELO_RATING for h in hypotheses)

    # Meta-review synthesis ran and produced the expected shape.
    meta_review = final_state["meta_review"]
    assert meta_review["summary"]
    assert "common_strengths" in meta_review
    assert "strategic_recommendations" in meta_review

    # Evolution ran and left an audit trail on every hypothesis.
    assert final_state["evolution_details"]
    assert all(h.evolution_history for h in hypotheses)

    # Deep verification probed the (post-evolution) top hypotheses.
    assert all(h.deep_verification_verdict for h in hypotheses)
    assert all(h.deep_verification_probes for h in hypotheses)

    # Research overview was synthesized as the terminal step.
    overview = final_state["research_overview"]
    assert overview is not None
    assert overview["overview"]
    assert overview["nih_specific_aims"]

    # Execution metrics were populated across nodes, not just one.
    metrics = final_state["metrics"]
    assert metrics.llm_calls > 0
    assert metrics.hypothesis_count == 2
    assert metrics.reviews_count >= 2
    assert metrics.tournaments_count >= 2
    assert metrics.evolutions_count == 2

    # One full iteration cycle completed (proximity increments the
    # counter exactly once per pass through the iterate loop).
    assert final_state["current_iteration"] == 1


async def test_evolve_path_shrinks_pool_to_evolution_max_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evolution keeps only its top-k pool, discarding lower-ranked ones.

    Generates 3 hypotheses but caps evolution at 2: the final pool should
    be exactly the 2 evolved hypotheses, and each should carry a genuine
    (non-identical) refinement.
    """
    install_fake_llm(monkeypatch)
    gen = HypothesisGenerator(
        model_name="fake/model",
        max_iterations=1,
        initial_hypotheses_count=3,
        evolution_max_count=2,
        tournament_pairs=3,
        enable_cache=False,
    )

    final_state = await _run_graph(gen, "Identify a synthetic-lethal target")

    # Generation produced 3, but evolve_node keeps ONLY the evolved
    # top-evolution_max_count pool going forward.
    hypotheses = final_state["hypotheses"]
    assert len(hypotheses) == 2

    # Every survivor was accepted-refined by evolve (the fake LLM never
    # echoes text back verbatim) and carries the resulting audit trail.
    assert len(final_state["evolution_details"]) == 2
    for hyp in hypotheses:
        assert hyp.evolution_history
        assert hyp.text not in hyp.evolution_history
    for detail in final_state["evolution_details"]:
        assert detail["original"] != detail["evolved"]
        assert detail["rationale"]


async def test_zero_iteration_pipeline_deep_verifies_and_skips_iterate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """max_iterations=0 still deep-verifies once but skips the iterate cycle.

    Deep verification runs unconditionally right after ranking, so even a
    zero-iteration run should leave every hypothesis probed and verdicted,
    while meta_review/evolve/proximity -- gated behind the iterate
    routing -- never run at all.
    """
    install_fake_llm(monkeypatch)
    gen = HypothesisGenerator(
        model_name="fake/model",
        max_iterations=0,
        initial_hypotheses_count=2,
        tournament_pairs=2,
        enable_cache=False,
    )

    final_state = await _run_graph(
        gen, "Repurpose an existing kinase inhibitor"
    )

    hypotheses = final_state["hypotheses"]
    assert len(hypotheses) == 2

    # Deep verification ran once, deterministically ("holds" is the first
    # allowed value in DEEP_VERIFICATION_SCHEMA's "verdict" enum).
    assert all(h.deep_verification_verdict == "holds" for h in hypotheses)
    assert all(h.deep_verification_probes for h in hypotheses)

    # The iterate cycle (meta_review / evolve / proximity) never ran, so
    # these stay at their untouched initial-state values.
    assert final_state["meta_review"] == {}
    assert final_state["evolution_details"] == []
    assert final_state["current_iteration"] == 0

    # The workflow still terminates through research_overview.
    overview = final_state["research_overview"]
    assert overview is not None
    assert overview["overview"]

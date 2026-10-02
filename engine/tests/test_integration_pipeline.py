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
``HypothesisGenerator.prepare_task_state`` and invokes the compiled graph
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
from co_scientist.generator import (
    GeneratorOptions,
    HypothesisGenerator,
)
from co_scientist.models import Hypothesis, HypothesisOrigin
from co_scientist.state import WorkflowState
from tests._llm_fake import install_fake_llm

_ADVANCED_KNOBS = frozenset(
    {
        "supervisor_model_name",
        "tournament_pairs",
        "elo_k_factor",
        "literature_review_papers_count",
        "enable_cache",
        "cache_dir",
        "tools_config",
        "disable_tools",
        "budget",
    }
)


def _make_gen(**overrides: Any) -> HypothesisGenerator:
    """Build a small, fast generator; overrides tweak individual knobs.

    Overrides may name any constructor knob flatly; advanced knobs are
    routed into ``GeneratorOptions`` for the caller.
    """
    params: dict[str, Any] = {
        "model_name": "fake/model",
        "max_iterations": 1,
        "initial_hypotheses_count": 2,
        "evolution_max_count": 2,
    }
    options: dict[str, Any] = {"tournament_pairs": 2, "enable_cache": False}
    for key, value in overrides.items():
        (options if key in _ADVANCED_KNOBS else params)[key] = value
    return HypothesisGenerator(**params, options=GeneratorOptions(**options))


def _generations(
    final_state: WorkflowState,
) -> tuple[list[Hypothesis], list[Hypothesis]]:
    """Split the final pool into generation-0 parents and their children."""
    hyps = final_state["hypotheses"]
    parents = [h for h in hyps if h.generation == 0]
    children = [h for h in hyps if h.generation >= 1]
    return parents, children


def _assert_iteration_children(
    children: list[Hypothesis], parent_ids: set[str]
) -> None:
    """Each child is a fresh, reviewed EVOLUTION entrant of a real parent."""
    for child in children:
        assert child.origin is HypothesisOrigin.EVOLUTION
        assert child.parent_id in parent_ids
        assert child.generation == 1
        assert len(child.reviews) >= 1  # reviewed before ranking
        assert child.evolution_history


def _assert_top_ranked_verified(final_state: WorkflowState) -> None:
    """Deep verification probed the top hypothesis by Elo (top-k, not all)."""
    ranked = sorted(
        final_state["hypotheses"], key=lambda h: h.elo_rating, reverse=True
    )
    assert ranked[0].deep_verification_verdict
    assert ranked[0].deep_verification_probes


def _assert_meta_review_shape(final_state: WorkflowState) -> None:
    """Meta-review synthesis ran and produced the expected shape."""
    meta_review = final_state["meta_review"]
    assert meta_review["summary"]
    assert "common_strengths" in meta_review
    assert "strategic_recommendations" in meta_review


def _assert_terminal_overview(final_state: WorkflowState) -> None:
    """Research overview was synthesized as the terminal step."""
    overview = final_state["research_overview"]
    assert overview is not None
    assert overview["overview"]
    assert overview["nih_specific_aims"]


def _assert_execution_metrics(final_state: WorkflowState) -> None:
    """Execution metrics were populated across nodes, not just one."""
    metrics = final_state["metrics"]
    assert metrics.llm_calls > 0
    assert metrics.reviews_count >= 2
    assert metrics.tournaments_count >= 2
    assert metrics.evolutions_count == 2


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
    initial_state = await gen.prepare_task_state(
        research_goal,
        opts={"enable_literature_review_node": False, **opts},
    )
    assert gen._graph is not None  # built by prepare_task_state
    final_state = await gen._graph.ainvoke(
        initial_state, config={"recursion_limit": 100}
    )
    return cast(WorkflowState, final_state)


async def test_single_iteration_pipeline_updates_cross_node_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A max_iterations=1 run touches every node with consistent state.

    Covers the full cycle: supervisor -> generate -> review -> ranking ->
    verification -> meta_review -> evolve -> review -> ranking ->
    verification -> proximity -> research_overview.
    """
    install_fake_llm(monkeypatch)
    gen = _make_gen()

    final_state = await _run_graph(gen, "Explain how protein X folds")

    # The pool grew: 2 generation-0 parents plus 2 appended evolution children.
    hypotheses = final_state["hypotheses"]
    parents, children = _generations(final_state)
    assert len(parents) == 2
    assert len(children) == 2
    assert len(hypotheses) == 4
    # Every hypothesis has distinct text.
    texts = [h.text for h in hypotheses]
    assert len(texts) == len(set(texts))

    # Reviews are incremental: each parent reviewed once; children reviewed
    # before ranking (EVO-COMPETE-001).
    assert all(len(p.reviews) == 1 for p in parents)
    _assert_iteration_children(children, {p.id for p in parents})

    # The tournament judged matchups and moved Elo off the initial rating.
    assert final_state["tournament_matchups"]
    assert any(h.elo_rating != INITIAL_ELO_RATING for h in hypotheses)
    assert final_state["evolution_details"]  # evolution left an audit trail
    _assert_top_ranked_verified(final_state)
    _assert_meta_review_shape(final_state)
    _assert_terminal_overview(final_state)
    _assert_execution_metrics(final_state)

    # One full iteration cycle completed (proximity increments once per pass).
    assert final_state["current_iteration"] == 1


async def test_evolve_path_appends_immutable_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evolution appends immutable children; parents stay and both compete.

    Generates 3 hypotheses, caps evolution at 2: the 3 parents remain in the
    pool unchanged and up to 2 evolution children are appended, each linking
    back to a parent with a fresh generation. The pool grows rather than
    shrinking (paper invariant SSR §4, §12).
    """
    install_fake_llm(monkeypatch)
    gen = _make_gen(initial_hypotheses_count=3, tournament_pairs=3)

    final_state = await _run_graph(gen, "Identify a synthetic-lethal target")

    hypotheses = final_state["hypotheses"]
    # The pool grew beyond the 3 originals: children were appended, not
    # substituted for their parents.
    assert len(hypotheses) > 3

    parents, children = _generations(final_state)
    assert len(parents) == 3  # every parent survived
    assert children, "evolution should append at least one child"

    parent_ids = {h.id for h in parents}
    for child in children:
        # Each child is a fresh, immutable entrant linked to a real parent.
        assert child.parent_id in parent_ids
        assert child.origin is HypothesisOrigin.EVOLUTION
        assert child.evolution_history
        assert child.text not in [p.text for p in parents]

    # Evolution details record the parent->child edges.
    assert final_state["evolution_details"]
    for detail in final_state["evolution_details"]:
        assert detail["parent_id"] in parent_ids
        assert detail["original"] != detail["evolved"]
        assert detail["rationale"]


async def test_adaptive_orchestration_schedules_generation_and_records_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Supervisor loop generates after the first tournament, with reasons.

    M2 acceptance: over multiple iterations the orchestrator schedules new
    Generation work after the first tournament (not only Evolution), every
    scheduled task and the final stop carry a recorded reason, and the run
    terminates with an explicit termination reason.
    """
    install_fake_llm(monkeypatch)
    gen = _make_gen(max_iterations=3)

    final_state = await _run_graph(gen, "Explain how protein X folds")

    history = final_state["task_history"]
    assert history, "the orchestrator should record scheduled tasks"
    # Every scheduled task carries a non-empty recorded reason.
    for record in history:
        assert record["reason"], record

    tasks = [r["task_type"] for r in history]
    # Both evolution and new generation happen across the run; the first work
    # cycle evolves the leaders and a later cycle generates new regions.
    assert "evolve" in tasks
    assert "generate" in tasks
    # Generation is scheduled after the first evolve (a later cycle), not only
    # in the initial pass.
    assert tasks.index("generate") > tasks.index("evolve")

    # The run terminates with an explicit, recorded reason.
    assert tasks[-1] == "terminate"
    assert history[-1]["termination_reason"]
    assert final_state["termination_reason"]


async def test_budget_exhaustion_terminates_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hard LLM-call budget stops the run with a budget termination reason.

    Proves the budget is a real termination predicate, not just
    max_iterations.
    """
    install_fake_llm(monkeypatch)
    gen = HypothesisGenerator(
        model_name="fake/model",
        max_iterations=50,
        # would run for many cycles without a budget
        initial_hypotheses_count=2,
        evolution_max_count=2,
        options=GeneratorOptions(
            tournament_pairs=2,
            enable_cache=False,
            budget={"max_llm_calls": 12},
        ),
    )

    final_state = await _run_graph(gen, "Explain how protein X folds")

    # The run stopped on the budget, well before 50 iterations.
    assert final_state["termination_reason"] == "budget"
    assert final_state["current_iteration"] < 50
    terminate_records = [
        r for r in final_state["task_history"] if r["task_type"] == "terminate"
    ]
    assert terminate_records
    assert terminate_records[-1]["termination_reason"] == "budget"


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
    gen = _make_gen(max_iterations=0)

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

"""System tests: the public ``HypothesisGenerator.generate_hypotheses`` API.

These exercise the generator strictly from the caller's perspective -- the
same entry point ``examples/run.py`` and the FastAPI viewer's engine
adapter use -- in both of its modes: ``stream=False`` (await a single
result dict) and ``stream=True`` (consume an async iterator of
``(node_name, cumulative_state_dict)`` tuples). Like
``tests/test_integration_pipeline.py``, the real compiled LangGraph
workflow runs end-to-end with only the LLM layer faked at the
``litellm.acompletion`` boundary (see ``tests/_llm_fake.py``); no network
access, no MCP server, and literature review explicitly disabled so the
run is deterministic and offline.

Unlike the integration tests, everything here is read back through the
public API's serialized shapes (plain dicts, not ``Hypothesis``/
``ExecutionMetrics`` objects), matching what an external caller actually
sees.
"""

from typing import Any

import pytest

from co_scientist.generator import HypothesisGenerator
from tests._llm_fake import install_fake_llm

# The node execution order for one max_iterations=1 run in LLM-only mode
# (literature_review/reflection are absent -- see tests/test_generator.py's
# _SIMPLE_NODES). One full pass through generate/review/ranking/
# deep_verification reaches the orchestrator, which schedules one evolve cycle,
# then a proximity refresh, then terminates (converged) into research_overview.
# The orchestrator is the loop point that appears before each routed phase.
_EXPECTED_NODE_SEQUENCE = [
    "supervisor",
    "generate",
    "review",
    "ranking",
    "deep_verification",
    "orchestrator",
    "meta_review",
    "evolve",
    "review",
    "ranking",
    "deep_verification",
    "orchestrator",
    "proximity",
    "orchestrator",
    "research_overview",
]


def _make_generator() -> HypothesisGenerator:
    """Builds a small, fast HypothesisGenerator for the tests below."""
    return HypothesisGenerator(
        model_name="fake/model",
        max_iterations=1,
        initial_hypotheses_count=2,
        evolution_max_count=2,
        tournament_pairs=2,
        enable_cache=False,
    )


async def test_generate_hypotheses_non_streaming_result_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``stream=False`` returns a single, fully-populated result dict."""
    install_fake_llm(monkeypatch)
    gen = _make_generator()

    result = await gen.generate_hypotheses(
        "Explain how protein X folds",
        opts={"enable_literature_review_node": False},
        stream=False,
    )

    hypotheses = result["hypotheses"]
    assert isinstance(hypotheses, list)
    # 2 generation-0 parents plus 2 appended evolution children.
    assert len(hypotheses) == 4
    assert sorted(h["generation"] for h in hypotheses) == [0, 0, 1, 1]
    for hyp in hypotheses:
        # Public shape: plain dicts (Hypothesis.to_dict()), not objects.
        assert isinstance(hyp, dict)
        assert hyp["text"]
        assert isinstance(hyp["reviews"], list) and hyp["reviews"]
        assert hyp["elo_rating"] != 0
        # Lineage fields are part of the public serialized shape.
        assert "parent_id" in hyp and "origin" in hyp
    # Deep verification runs on the top-k by Elo, so at least the top-ranked
    # hypotheses carry a verdict.
    verdicts = [h["deep_verification_verdict"] for h in hypotheses]
    assert verdicts.count("holds") >= 1

    assert result["meta_review"]["summary"]
    assert result["research_overview"]["overview"]
    assert result["research_overview"]["nih_specific_aims"]
    assert result["research_plan"]  # supervisor guidance, renamed
    assert result["tournament_matchups"]
    assert result["evolution_details"]
    assert result["execution_time"] >= 0

    metrics = result["metrics"]
    assert metrics["llm_calls"] > 0
    assert metrics["hypothesis_count"] == 2
    assert metrics["reviews_count"] >= 2
    assert metrics["tournaments_count"] >= 2
    assert metrics["evolutions_count"] == 2
    assert metrics["total_time"] == result["execution_time"]


async def test_generate_hypotheses_streaming_event_progression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``stream=True`` yields nodes in graph order with growing state."""
    install_fake_llm(monkeypatch)
    gen = _make_generator()

    events: list[tuple[str, dict[str, Any]]] = []
    async for node_name, state_dict in gen.generate_hypotheses(
        "Identify a synthetic-lethal target",
        opts={"enable_literature_review_node": False},
        stream=True,
    ):
        events.append((node_name, state_dict))

    assert [name for name, _ in events] == _EXPECTED_NODE_SEQUENCE

    # Right after "generate", the cumulative state already carries the
    # full initial hypothesis pool (as serialized dicts).
    generate_state = dict(events)["generate"]
    assert len(generate_state["hypotheses"]) == 2
    assert all(isinstance(h, dict) for h in generate_state["hypotheses"])

    # The first "ranking" pass has already recorded tournament matchups.
    first_ranking_state = events[3][1]
    assert events[3][0] == "ranking"
    assert first_ranking_state["tournament_matchups"]

    # "meta_review" carries a populated meta_review payload from that
    # point on.
    meta_review_state = dict(events)["meta_review"]
    assert meta_review_state["meta_review"]["summary"]

    # The stream is strictly cumulative: current_iteration never resets
    # across the run once proximity has incremented it.
    iterations = [state["current_iteration"] for _, state in events]
    assert iterations == sorted(iterations)
    assert iterations[-1] == 1

    # Final yielded state (after research_overview) matches the shape and
    # content invariants of the non-streaming result. The pool grew to 4:
    # 2 generation-0 parents plus 2 appended evolution children.
    node_name, final_state = events[-1]
    assert node_name == "research_overview"
    assert len(final_state["hypotheses"]) == 4
    generations = [h["generation"] for h in final_state["hypotheses"]]
    assert sorted(generations) == [0, 0, 1, 1]
    assert final_state["research_overview"]["overview"]
    assert final_state["research_overview"]["nih_specific_aims"]
    assert final_state["evolution_details"]
    final_metrics = final_state["metrics"]
    assert final_metrics["llm_calls"] > 0
    assert final_metrics["hypothesis_count"] == 2
    assert final_metrics["evolutions_count"] == 2


async def test_streaming_and_non_streaming_agree_on_final_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both modes settle on the same cumulative counts for equal configs.

    The two runs use independent fake-LLM content (a shared, ever-
    incrementing counter backs every stub string), so hypothesis text
    will differ between them; this asserts structural agreement, not
    byte-for-byte equality.
    """
    install_fake_llm(monkeypatch)

    non_streaming_result = await _make_generator().generate_hypotheses(
        "Explain a resistance mechanism",
        opts={"enable_literature_review_node": False},
        stream=False,
    )

    last_state: dict[str, Any] | None = None
    async for _node_name, state_dict in _make_generator().generate_hypotheses(
        "Explain a resistance mechanism",
        opts={"enable_literature_review_node": False},
        stream=True,
    ):
        last_state = state_dict
    assert last_state is not None

    assert len(last_state["hypotheses"]) == len(
        non_streaming_result["hypotheses"]
    )
    assert (
        last_state["metrics"]["hypothesis_count"]
        == non_streaming_result["metrics"]["hypothesis_count"]
    )
    assert (
        last_state["metrics"]["evolutions_count"]
        == non_streaming_result["metrics"]["evolutions_count"]
    )
    assert bool(last_state["meta_review"]) == bool(
        non_streaming_result["meta_review"]
    )
    assert bool(last_state["research_overview"]["overview"]) == bool(
        non_streaming_result["research_overview"]["overview"]
    )

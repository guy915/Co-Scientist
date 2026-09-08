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

from tests._llm_fake import install_fake_llm, make_test_generator
from tests._stream import collect_stream_events

# The node execution order for one max_iterations=1 run in LLM-only mode
# (literature_review/reflection are absent -- see tests/test_generator.py's
# _SIMPLE_NODES). One full pass through generate/review/ranking reaches the
# orchestrator, which schedules one evolve cycle, then a proximity refresh,
# then terminates (converged) into research_overview. Deep verification
# follows every ranking pass, probing the tournament's leaders (audit E9).
# The orchestrator is the loop point that appears before each routed phase.
#
# Each tournament is followed by a second ranking pass: this pool holds two
# rankable ideas, so one pairing leaves both at one match of the
# TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS the tournament's coverage floor asks
# for, and the orchestrator's owed-coverage check settles the shortfall before
# moving on. The settlement round re-enters through safety_screen and ranking
# like any other routed ranking phase. It fires once per tournament, not
# repeatedly: settling brings the pool to the minimum, which closes the
# settlement episode.
_EXPECTED_NODE_SEQUENCE = [
    "supervisor",
    "generate",
    "review",
    "comprehensive_reflection",
    "safety_screen",
    "ranking",
    "deep_verification",
    "orchestrator",
    "safety_screen",
    "ranking",
    "deep_verification",
    "orchestrator",
    "meta_review",
    "evolve",
    "review",
    "comprehensive_reflection",
    "safety_screen",
    "ranking",
    "deep_verification",
    "orchestrator",
    "proximity",
    "orchestrator",
    "research_overview",
]
# The second tournament needs no settlement round of its own, because the run
# is charged for matches judged rather than for rounds offered
# (``ranking_results._ranking_metrics_update``). The two-idea passes are
# unaffected either way -- a two-idea pool holds exactly one pair, so they
# judge one match whichever number is charged. The difference lands on the
# third pass, over the evolved four-idea pool: charged for offered rounds it
# arrived with 4 of the 6-round budget already spent, judged the 2 that were
# left, and still owed coverage -- which bought a fourth ranking phase for one
# more match. Charged for matches judged it arrives with 2 spent, judges 4 at
# once, and closes the shortfall inside the tournament. Measured: 27 nodes /
# 5 matches / 7 charged before, 23 nodes / 6 matches / 6 charged after.


def _assert_public_hypothesis_shape(hyp: dict[str, Any]) -> None:
    """A serialized hypothesis is a plain dict with the public fields."""
    assert isinstance(hyp, dict)
    assert hyp["text"]
    assert isinstance(hyp["reviews"], list) and hyp["reviews"]
    assert hyp["elo_rating"] != 0
    # Lineage fields are part of the public serialized shape.
    assert "parent_id" in hyp and "origin" in hyp


def _assert_streaming_final_state(
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    """The final yielded state matches the non-streaming shape invariants.

    The pool grew to 4: 2 generation-0 parents plus 2 appended evolution
    children.
    """
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


async def test_generate_hypotheses_non_streaming_result_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``stream=False`` returns a single, fully-populated result dict."""
    install_fake_llm(monkeypatch)
    gen = make_test_generator()

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
        _assert_public_hypothesis_shape(hyp)
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
    gen = make_test_generator()

    events = await collect_stream_events(
        gen, "Identify a synthetic-lethal target"
    )

    assert [name for name, _ in events] == _EXPECTED_NODE_SEQUENCE

    # Right after "generate", the cumulative state already carries the
    # full initial hypothesis pool (as serialized dicts).
    generate_state = dict(events)["generate"]
    assert len(generate_state["hypotheses"]) == 2
    assert all(isinstance(h, dict) for h in generate_state["hypotheses"])

    # The first "ranking" pass has already recorded tournament matchups.
    first_ranking_state = events[5][1]
    assert events[5][0] == "ranking"
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
    # content invariants of the non-streaming result.
    _assert_streaming_final_state(events)


async def test_streaming_and_non_streaming_agree_on_final_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both modes settle on the same cumulative counts for equal configs.

    The two runs use independent fake-LLM content (a shared, ever-incrementing
    counter backs every stub string), so hypothesis text differs between them;
    this asserts structural agreement, not byte-for-byte equality.
    """
    install_fake_llm(monkeypatch)

    non_streaming_result = await make_test_generator().generate_hypotheses(
        "Explain a resistance mechanism",
        opts={"enable_literature_review_node": False},
        stream=False,
    )

    events = await collect_stream_events(
        make_test_generator(), "Explain a resistance mechanism"
    )
    assert events
    last_state = events[-1][1]

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

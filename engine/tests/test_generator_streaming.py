"""Tests for streaming-state accumulation and result shaping.

Exercises the pure helpers in ``co_scientist.generator.streaming`` directly:
merging a node's incremental update into cumulative streaming state, seeding
that cumulative state, shaping it into a per-node stream payload, and
formatting a completed workflow's final state into the non-streaming result
dict.
"""

from typing import Any, cast

from co_scientist.generator.streaming import (
    _build_generation_result,
    _build_stream_state_dict,
    _initial_cumulative_stream_state,
    _merge_node_state_into_cumulative,
)
from co_scientist.models import ExecutionMetrics
from co_scientist.state import WorkflowState
from tests._state import make_article, make_hypothesis

# --- _merge_node_state_into_cumulative --------------------------------------


def test_merge_copies_streamed_keys_last_write_wins() -> None:
    """Plain streamed keys are copied verbatim, overwriting prior values."""
    cumulative = _initial_cumulative_stream_state()
    hyp = make_hypothesis("h1")
    _merge_node_state_into_cumulative(
        cumulative,
        {
            "hypotheses": [hyp],
            "current_iteration": 2,
            "tournament_matchups": [{"a": 1}],
            "evolution_details": [{"b": 2}],
            "articles_with_reasoning": [{"c": 3}],
            "literature_review_queries": ["q1"],
            "articles": [make_article("An article")],
            "debate_transcripts": [{"d": 4}],
            "meta_review": {"summary": "s"},
            "research_overview": {"o": 1},
        },
    )
    assert cumulative["hypotheses"] == [hyp]
    assert cumulative["current_iteration"] == 2
    assert cumulative["tournament_matchups"] == [{"a": 1}]
    assert cumulative["evolution_details"] == [{"b": 2}]
    assert cumulative["articles_with_reasoning"] == [{"c": 3}]
    assert cumulative["literature_review_queries"] == ["q1"]
    assert len(cumulative["articles"]) == 1
    assert cumulative["debate_transcripts"] == [{"d": 4}]
    assert cumulative["meta_review"] == {"summary": "s"}
    assert cumulative["research_overview"] == {"o": 1}


def test_merge_ignores_keys_absent_from_node_state() -> None:
    """Keys not present in the node update leave cumulative state untouched."""
    cumulative = _initial_cumulative_stream_state()
    original_hypotheses = cumulative["hypotheses"]
    _merge_node_state_into_cumulative(cumulative, {})
    assert cumulative["hypotheses"] is original_hypotheses
    assert cumulative["current_iteration"] == 0


def test_merge_renames_supervisor_guidance_to_research_plan() -> None:
    """``supervisor_guidance`` is copied under the ``research_plan`` key."""
    cumulative = _initial_cumulative_stream_state()
    _merge_node_state_into_cumulative(
        cumulative, {"supervisor_guidance": {"plan": "do X"}}
    )
    assert cumulative["research_plan"] == {"plan": "do X"}
    # The source key itself is not added to cumulative state.
    assert "supervisor_guidance" not in cumulative


def test_merge_merges_metrics_instead_of_replacing() -> None:
    """``metrics`` updates are merged (summed) rather than overwritten."""
    cumulative = _initial_cumulative_stream_state()
    cumulative["metrics"] = ExecutionMetrics(llm_calls=2, reviews_count=1)
    _merge_node_state_into_cumulative(
        cumulative,
        {"metrics": ExecutionMetrics(llm_calls=3, tournaments_count=1)},
    )
    merged = cumulative["metrics"]
    assert merged.llm_calls == 5
    assert merged.reviews_count == 1
    assert merged.tournaments_count == 1


def test_merge_handles_multiple_keys_in_one_update() -> None:
    """A single node update touching several streamed keys merges all."""
    cumulative = _initial_cumulative_stream_state()
    hyp = make_hypothesis("multi")
    _merge_node_state_into_cumulative(
        cumulative,
        {
            "hypotheses": [hyp],
            "supervisor_guidance": {"plan": "y"},
            "metrics": ExecutionMetrics(llm_calls=1),
        },
    )
    assert cumulative["hypotheses"] == [hyp]
    assert cumulative["research_plan"] == {"plan": "y"}
    assert cumulative["metrics"].llm_calls == 1


# --- _initial_cumulative_stream_state ---------------------------------------


def test_initial_cumulative_stream_state_seeds_every_field() -> None:
    """The seed state has empty/zero defaults for every streamed field."""
    state = _initial_cumulative_stream_state()
    assert state["hypotheses"] == []
    assert state["meta_review"] == {}
    assert state["research_overview"] == {}
    assert state["research_plan"] == {}
    assert state["tournament_matchups"] == []
    assert state["evolution_details"] == []
    assert state["current_iteration"] == 0
    assert isinstance(state["metrics"], ExecutionMetrics)
    assert state["articles_with_reasoning"] is None
    assert state["literature_review_queries"] == []
    assert state["articles"] == []
    assert state["debate_transcripts"] is None


# --- _build_stream_state_dict ------------------------------------------------


def test_build_stream_state_dict_serializes_hypotheses_and_articles() -> None:
    """Hypotheses/articles are serialized via ``to_dict``; metrics flattened."""
    cumulative = _initial_cumulative_stream_state()
    hyp = make_hypothesis("h1", score=3.5)
    cumulative["hypotheses"] = [hyp]
    cumulative["articles"] = [make_article("Paper 1")]
    cumulative["research_plan"] = {"plan": "z"}
    cumulative["metrics"] = ExecutionMetrics(
        hypothesis_count=1,
        reviews_count=2,
        tournaments_count=3,
        evolutions_count=4,
        llm_calls=5,
        total_time=6.5,
        phase_times={"generate": 1.25},
    )

    result = _build_stream_state_dict(cumulative)

    assert result["hypotheses"] == [hyp.to_dict()]
    assert result["articles"][0]["title"] == "Paper 1"
    assert result["research_plan"] == {"plan": "z"}
    assert result["metrics"] == {
        "hypothesis_count": 1,
        "reviews_count": 2,
        "tournaments_count": 3,
        "evolutions_count": 4,
        "llm_calls": 5,
        "total_time": 6.5,
        "phase_times": {"generate": 1.25},
        "model_usage": {},
        "skills_used": {},
    }


def test_build_stream_state_dict_includes_all_streamed_keys() -> None:
    """Every key in ``_STREAMED_STATE_KEYS`` is present in the payload."""
    cumulative = _initial_cumulative_stream_state()
    result = _build_stream_state_dict(cumulative)
    for key in (
        "hypotheses",
        "meta_review",
        "research_overview",
        "tournament_matchups",
        "evolution_details",
        "current_iteration",
        "articles_with_reasoning",
        "literature_review_queries",
        "articles",
        "debate_transcripts",
    ):
        assert key in result


# --- _build_generation_result ------------------------------------------------


def _make_final_state(**overrides: Any) -> WorkflowState:
    """Builds a minimal final-state dict for ``_build_generation_result``.

    Args:
        **overrides: Fields to override on top of the minimal defaults.

    Returns:
        A dict shaped like the fields ``_build_generation_result`` reads.
    """
    base: dict[str, Any] = {
        "hypotheses": [make_hypothesis("final h")],
        "metrics": ExecutionMetrics(
            hypothesis_count=1,
            reviews_count=2,
            tournaments_count=3,
            evolutions_count=4,
            llm_calls=5,
            phase_times={"generate": 1.5},
        ),
    }
    base.update(overrides)
    return cast(WorkflowState, base)


def test_build_generation_result_shapes_full_state() -> None:
    """A final state with every optional field populated is fully shaped."""
    final_state = _make_final_state(
        meta_review={"summary": "s"},
        research_overview={"o": 1},
        supervisor_guidance={"plan": "p"},
        tournament_matchups=[{"a": 1}],
        evolution_details=[{"b": 2}],
        debate_transcripts=[{"d": 3}],
    )
    result = _build_generation_result(final_state, execution_time=12.5)

    assert result["hypotheses"] == [
        h.to_dict() for h in final_state["hypotheses"]
    ]
    assert result["meta_review"] == {"summary": "s"}
    assert result["research_overview"] == {"o": 1}
    assert result["research_plan"] == {"plan": "p"}
    assert result["tournament_matchups"] == [{"a": 1}]
    assert result["evolution_details"] == [{"b": 2}]
    assert result["debate_transcripts"] == [{"d": 3}]
    assert result["execution_time"] == 12.5
    assert result["metrics"]["total_time"] == 12.5
    assert result["metrics"]["hypothesis_count"] == 1
    assert result["metrics"]["reviews_count"] == 2
    assert result["metrics"]["tournaments_count"] == 3
    assert result["metrics"]["evolutions_count"] == 4
    assert result["metrics"]["phase_times"] == {"generate": 1.5}
    assert result["metrics"]["llm_calls"] == 5


def test_build_generation_result_defaults_missing_optional_fields() -> None:
    """Optional final-state fields missing entirely default sensibly."""
    final_state = _make_final_state()
    result = _build_generation_result(final_state, execution_time=1.0)

    assert result["meta_review"] == {}
    assert result["research_overview"] == {}
    assert result["research_plan"] == {}
    assert result["tournament_matchups"] == []
    assert result["evolution_details"] == []
    assert result["debate_transcripts"] is None

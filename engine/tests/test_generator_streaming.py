"""Offline contracts for generator streaming."""

from __future__ import annotations

from typing import Any, cast

import pytest

from co_scientist import mcp_client
from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.generator import (
    GeneratorOptions,
    HypothesisGenerator,
    run_setup,
)
from co_scientist.generator.streaming import (
    _build_generation_result,
    _build_stream_state_dict,
    _initial_cumulative_stream_state,
    _merge_node_state_into_cumulative,
)
from co_scientist.models import ExecutionMetrics
from co_scientist.state import WorkflowState
from tests._llm_fake import install_fake_llm, make_test_generator
from tests._mcp import stub_mcp_availability
from tests._state import collect_stream_events, make_article, make_hypothesis


async def testprepare_task_state_populates_core_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initial state carries the configured model names and counts."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator(
        model_name="m",
        max_iterations=2,
        initial_hypotheses_count=7,
        evolution_max_count=4,
        options=GeneratorOptions(
            supervisor_model_name="sup",
        ),
    )
    state = await gen.prepare_task_state("Cure X")
    assert state["research_goal"] == "Cure X"
    assert state["model_name"] == "m"
    assert state["supervisor_model_name"] == "sup"
    assert state["max_iterations"] == 2
    assert state["initial_hypotheses_count"] == 7
    assert state["evolution_max_count"] == 4
    assert state["hypotheses"] == []
    assert state["current_iteration"] == 0
    registry = state["tool_registry"]
    assert registry is gen._tool_registry
    assert registry is not None
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None and workflow.is_multi_source()


async def testprepare_task_state_generates_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run_id is auto-generated and threaded into the state when absent."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["run_id"]


async def testprepare_task_state_honors_explicit_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied run_id is used verbatim."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal", run_id="fixed-id")
    assert state["run_id"] == "fixed-id"


async def testprepare_task_state_passes_through_opts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional preferences/constraints and user inputs land in the state."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    opts = {
        "preferences": "pref-X",
        "attributes": ["attr-Y"],
        "constraints": ["cons-Z"],
        # K5: the interview's lab constraints thread opts -> state -> prompts.
        "lab_constraints": ["zebrafish only"],
        "user_inputs": {
            "starting_hypotheses": ["h1"],
            "literature": ["lit1"],
        },
    }
    state = await gen.prepare_task_state("goal", opts=opts)
    assert state["preferences"] == "pref-X"
    assert state["attributes"] == ["attr-Y"]
    assert state["constraints"] == ["cons-Z"]
    assert state["lab_constraints"] == ["zebrafish only"]
    assert state["starting_hypotheses"] == ["h1"]
    assert state["literature"] == ["lit1"]


async def testprepare_task_state_opt_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitted optional fields default to None / empty / False."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["preferences"] is None
    assert state["attributes"] is None
    assert state["constraints"] is None
    assert state["lab_constraints"] is None
    assert state["starting_hypotheses"] is None
    assert state["literature"] is None
    assert state["enable_tool_calling_generation"] is False
    assert state["dev_test_lit_tools_isolation"] is False


async def testprepare_task_state_dev_isolation_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dev lit-tools isolation flag is passed through to the state."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"dev_test_lit_tools_isolation": True}
    )
    assert state["dev_test_lit_tools_isolation"] is True


async def testprepare_task_state_reads_dev_mode_env_into_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COSCIENTIST_DEV_MODE is read here, at the boundary, and put in state.

    The literature review node consumes ``dev_mode`` from state, so this is
    the one place the env var is allowed to enter a run.
    """
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["dev_mode"] is True


async def testprepare_task_state_dev_mode_opt_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-run dev_mode opt beats the session-wide env var, either way."""
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal", opts={"dev_mode": False})
    assert state["dev_mode"] is False

    monkeypatch.delenv("COSCIENTIST_DEV_MODE", raising=False)
    state = await gen.prepare_task_state("goal", opts={"dev_mode": True})
    assert state["dev_mode"] is True


async def testprepare_task_state_dev_mode_defaults_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With neither an opt nor the env var, a run is not in dev mode."""
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.delenv("COSCIENTIST_DEV_MODE", raising=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["dev_mode"] is False


# --- prepare_task_state: MCP detection & graph selection --------------------


async def test_mcp_available_enables_lit_review_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When MCP is available the auto-detected graph includes lit review."""
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["mcp_available"] is True
    assert state["pubmed_available"] is True
    assert gen._graph is not None
    assert "literature_review" in gen._graph.nodes


async def test_mcp_unavailable_uses_simplified_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without MCP, lit review is dropped and flags reflect unavailability."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["mcp_available"] is False
    assert gen._graph is not None
    assert "literature_review" not in gen._graph.nodes


async def test_mcp_availability_cached_per_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP probes run once; the cached result persists across calls."""
    calls = {"n": 0}

    async def counting(**_: Any) -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(mcp_client, "check_mcp_available", counting)
    monkeypatch.setattr(
        mcp_client, "check_literature_source_available", counting
    )

    gen = HypothesisGenerator()
    await gen.prepare_task_state("goal")
    after_first = calls["n"]
    await gen.prepare_task_state("goal again")
    # No additional probe calls on the second preparation.
    assert calls["n"] == after_first
    assert gen._mcp_available is True


async def test_explicit_disable_skips_mcp_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicitly disabling lit review avoids invoking the MCP probes."""

    async def explode(**_: Any) -> bool:
        raise AssertionError("MCP probe should not be called")

    monkeypatch.setattr(mcp_client, "check_mcp_available", explode)
    monkeypatch.setattr(
        mcp_client, "check_literature_source_available", explode
    )

    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_literature_review_node": False}
    )
    assert state["mcp_available"] is False
    assert gen._graph is not None
    assert "literature_review" not in gen._graph.nodes


async def test_tool_calling_honored_when_mcp_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool-calling generation stays on when MCP + lit review are available."""
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_disabled_when_mcp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool-calling generation is silently disabled when MCP is unavailable."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_with_lit_disabled_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool calling + explicit lit-review-off degrades gracefully (no raise).

    Note: ``prepare_task_state`` documents a ValueError for this combination,
    but explicitly disabling the literature review forces ``mcp_available`` to
    False *before* the tool-calling validation runs, so the MCP-unavailable
    branch always fires first and the ValueError branch is never reached. This
    asserts the observed graceful-disable behavior rather than the documented
    raise.
    """
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal",
        opts={
            "enable_literature_review_node": False,
            "enable_tool_calling_generation": True,
        },
    )
    assert state["enable_tool_calling_generation"] is False
    assert state["mcp_available"] is False


# --- E11a: tool-calling generation is opt-in, even where tools exist ---


async def test_tool_calling_off_by_default_when_tools_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Available tools are not on their own a request for the agentic path.

    The draft agent spends one LLM round-trip per tool call and re-sends
    every prior result, so it costs roughly nine calls per hypothesis on
    prompts that grow past 12k tokens -- per hypothesis, per cycle. Live
    telemetry had it as the largest single line in an express run's token
    budget. Availability decides whether it *can* run; the caller decides
    whether it *should*, and the app opts in only for the deep tiers.
    """
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_opt_in_survives_prepare_task_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The durable-task entry point carries an explicit opt-in through.

    ``prepare_task_state`` is the exact call the app's durable executor
    makes before enqueueing node tasks, so the flag it writes decides
    whether the generation fan-out allocates the tool-based strategy.
    """
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_explicit_opt_out_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit False opts out even when tools are available."""
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": False}
    )
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_stays_off_by_default_without_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without MCP there are no literature tools, so the default is off."""
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_forced_off_for_offline_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline runs keep the plain deterministic path even with MCP.

    The offline responder never emits tool calls, so a tool loop would
    "finish" on its first canned reply and fail parsing; the capability
    default must not admit that.
    """
    from co_scientist.offline.llm import DEFAULT_OFFLINE_MODEL

    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator(model_name=DEFAULT_OFFLINE_MODEL)
    state = await gen.prepare_task_state("goal")
    assert state["enable_tool_calling_generation"] is False

    # An explicit request cannot override the offline backend either.
    gen2 = HypothesisGenerator(model_name=DEFAULT_OFFLINE_MODEL)
    state2 = await gen2.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state2["enable_tool_calling_generation"] is False


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


def test_offline_backend_runs_no_review_at_all() -> None:
    assert (
        run_setup._resolve_overview_review(
            {"enable_overview_review": True}, "offline/deterministic"
        )
        is False
    )


def test_a_real_model_asked_for_may_review() -> None:
    assert (
        run_setup._resolve_overview_review(
            {"enable_overview_review": True}, "deepseek/some-model"
        )
        is True
    )


def test_an_omitted_option_is_not_a_request() -> None:
    assert (
        run_setup._resolve_overview_review({}, "deepseek/some-model") is False
    )


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
    "deep_verification",
    "ranking",
    "orchestrator",
    "safety_screen",
    "deep_verification",
    "ranking",
    "orchestrator",
    "meta_review",
    "evolve",
    "review",
    "comprehensive_reflection",
    "safety_screen",
    "deep_verification",
    "ranking",
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
    first_ranking_state = events[6][1]
    assert events[6][0] == "ranking"
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


def _make() -> HypothesisGenerator:
    return HypothesisGenerator(
        model_name="fake/model",
        max_iterations=2,
        initial_hypotheses_count=2,
        evolution_max_count=2,
        options=GeneratorOptions(
            tournament_pairs=2,
            enable_cache=False,
        ),
    )


def _pre_orchestrator_index(states: list[dict[str, Any]]) -> int:
    """Return the first full state right before the orchestrator runs.

    That boundary has every hypothesis reviewed and a tournament recorded, but
    no scheduling decision yet (``next_task`` is None). Resuming from it
    re-enters the orchestrator for the first time — no completed node re-runs.
    """
    for i, s in enumerate(states):
        hyps = s.get("hypotheses") or []
        if (
            hyps
            and all(h.reviews for h in hyps)
            and s.get("tournament_matchups")
            and not s.get("next_task")
        ):
            return i
    raise AssertionError("no pre-orchestrator boundary found in the stream")


async def _stream_states(
    gen: HypothesisGenerator, goal: str
) -> list[dict[str, Any]]:
    """Run the graph in values mode, returning every full post-node state."""
    initial = await gen.prepare_task_state(
        goal, opts={"enable_literature_review_node": False}
    )
    assert gen._graph is not None
    states: list[dict[str, Any]] = []
    async for full_state in gen._graph.astream(
        initial, stream_mode="values", config={"recursion_limit": 100}
    ):
        states.append(full_state)
    return states


def _assert_preserves_and_completes(
    boundary: dict[str, Any], final: dict[str, Any]
) -> None:
    """Assert resume preserved the checkpointed pool and completed cleanly."""
    boundary_by_id = {h.id: h for h in boundary["hypotheses"]}
    final_ids = [h.id for h in final["hypotheses"]]

    # No duplicated hypotheses.
    assert len(final_ids) == len(set(final_ids))
    # Every checkpointed hypothesis survives byte-for-byte (id + text).
    for hyp in final["hypotheses"]:
        if hyp.id in boundary_by_id:
            assert hyp.text == boundary_by_id[hyp.id].text
    # Nothing checkpointed was lost.
    assert set(boundary_by_id) <= set(final_ids)
    # The resumed run reached a proper terminal state.
    assert final.get("termination_reason")
    assert final.get("research_overview")


async def test_resume_preserves_checkpointed_pool_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interrupt at a safe boundary, resume in a rebuilt generator, complete."""
    install_fake_llm(monkeypatch)

    states = await _stream_states(_make(), "Explain how protein X folds")
    boundary = states[_pre_orchestrator_index(states)]
    checkpoint = serialize_workflow_state(boundary, last_event_seq=10)

    # Simulate a process restart: a fresh generator rebuilds the graph.
    restarted = _make()
    await restarted.prepare_task_state(
        "Explain how protein X folds",
        opts={"enable_literature_review_node": False},
    )
    resumed_state = restore_workflow_state(
        checkpoint, tool_registry=restarted._tool_registry
    )
    assert resumed_state["resume"] is True
    assert restarted._graph is not None
    resumed_final = await restarted._graph.ainvoke(
        resumed_state, config={"recursion_limit": 100}
    )

    _assert_preserves_and_completes(boundary, resumed_final)


async def test_double_restart_preserves_pool_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive checkpoint/restore cycles still preserve and complete."""
    install_fake_llm(monkeypatch)

    gen = _make()
    states = await _stream_states(gen, "goal")
    boundary = states[_pre_orchestrator_index(states)]

    cp1 = serialize_workflow_state(boundary, last_event_seq=1)
    r1 = restore_workflow_state(cp1)
    cp2 = serialize_workflow_state(r1, last_event_seq=2)
    r2 = restore_workflow_state(cp2)

    assert gen._graph is not None
    final = await gen._graph.ainvoke(r2, config={"recursion_limit": 100})
    _assert_preserves_and_completes(boundary, final)

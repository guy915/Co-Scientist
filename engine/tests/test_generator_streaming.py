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
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["run_id"]


async def testprepare_task_state_honors_explicit_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal", run_id="fixed-id")
    assert state["run_id"] == "fixed-id"


async def testprepare_task_state_passes_through_opts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    opts = {
        "preferences": "pref-X",
        "attributes": ["attr-Y"],
        "constraints": ["cons-Z"],
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
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"dev_test_lit_tools_isolation": True}
    )
    assert state["dev_test_lit_tools_isolation"] is True


async def testprepare_task_state_reads_dev_mode_env_into_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment configuration enters at the run boundary, not inside node
    execution."""
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["dev_mode"] is True


async def testprepare_task_state_dev_mode_opt_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    stub_mcp_availability(monkeypatch, available=False)
    monkeypatch.delenv("COSCIENTIST_DEV_MODE", raising=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["dev_mode"] is False


async def test_mcp_available_enables_lit_review_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["mcp_available"] is False
    assert gen._graph is not None
    assert "literature_review" not in gen._graph.nodes


async def test_mcp_availability_cached_per_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert calls["n"] == after_first
    assert gen._mcp_available is True


async def test_explicit_disable_skips_mcp_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

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
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_disabled_when_mcp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_with_lit_disabled_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


async def test_tool_calling_off_by_default_when_tools_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Availability is not opt-in: tool transcripts multiply cost per
    hypothesis and cycle."""
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_opt_in_survives_prepare_task_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state["enable_tool_calling_generation"] is True


async def test_tool_calling_explicit_opt_out_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": False}
    )
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_stays_off_by_default_without_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_mcp_availability(monkeypatch, available=False)
    gen = HypothesisGenerator()
    state = await gen.prepare_task_state("goal")
    assert state["enable_tool_calling_generation"] is False


async def test_tool_calling_forced_off_for_offline_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offline responder emits no tool calls; a tool-loop reply cannot
    satisfy its parser."""
    from co_scientist.offline.llm import DEFAULT_OFFLINE_MODEL

    stub_mcp_availability(monkeypatch, available=True)
    gen = HypothesisGenerator(model_name=DEFAULT_OFFLINE_MODEL)
    state = await gen.prepare_task_state("goal")
    assert state["enable_tool_calling_generation"] is False

    gen2 = HypothesisGenerator(model_name=DEFAULT_OFFLINE_MODEL)
    state2 = await gen2.prepare_task_state(
        "goal", opts={"enable_tool_calling_generation": True}
    )
    assert state2["enable_tool_calling_generation"] is False


def test_merge_copies_streamed_keys_last_write_wins() -> None:
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
    cumulative = _initial_cumulative_stream_state()
    original_hypotheses = cumulative["hypotheses"]
    _merge_node_state_into_cumulative(cumulative, {})
    assert cumulative["hypotheses"] is original_hypotheses
    assert cumulative["current_iteration"] == 0


def test_merge_renames_supervisor_guidance_to_research_plan() -> None:
    cumulative = _initial_cumulative_stream_state()
    _merge_node_state_into_cumulative(
        cumulative, {"supervisor_guidance": {"plan": "do X"}}
    )
    assert cumulative["research_plan"] == {"plan": "do X"}
    assert "supervisor_guidance" not in cumulative


def test_merge_merges_metrics_instead_of_replacing() -> None:
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


def test_initial_cumulative_stream_state_seeds_every_field() -> None:
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


def test_build_stream_state_dict_serializes_hypotheses_and_articles() -> None:
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


def _make_final_state(**overrides: Any) -> WorkflowState:
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


# Owed coverage adds one settlement pass after a two-idea tournament.
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
# Charge judged matches, not offered rounds, to avoid an unnecessary later
# settlement.


def _assert_public_hypothesis_shape(hyp: dict[str, Any]) -> None:
    assert isinstance(hyp, dict)
    assert hyp["text"]
    assert isinstance(hyp["reviews"], list) and hyp["reviews"]
    assert hyp["elo_rating"] != 0
    assert "parent_id" in hyp and "origin" in hyp


def _assert_streaming_final_state(
    events: list[tuple[str, dict[str, Any]]],
) -> None:
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
    install_fake_llm(monkeypatch)
    gen = make_test_generator()

    result = await gen.generate_hypotheses(
        "Explain how protein X folds",
        opts={"enable_literature_review_node": False},
        stream=False,
    )

    hypotheses = result["hypotheses"]
    assert isinstance(hypotheses, list)
    assert len(hypotheses) == 4
    assert sorted(h["generation"] for h in hypotheses) == [0, 0, 1, 1]
    for hyp in hypotheses:
        _assert_public_hypothesis_shape(hyp)
    verdicts = [h["deep_verification_verdict"] for h in hypotheses]
    assert verdicts.count("holds") >= 1

    assert result["meta_review"]["summary"]
    assert result["research_overview"]["overview"]
    assert result["research_overview"]["nih_specific_aims"]
    assert result["research_plan"]
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
    install_fake_llm(monkeypatch)
    gen = make_test_generator()

    events = await collect_stream_events(
        gen, "Identify a synthetic-lethal target"
    )

    assert [name for name, _ in events] == _EXPECTED_NODE_SEQUENCE

    generate_state = dict(events)["generate"]
    assert len(generate_state["hypotheses"]) == 2
    assert all(isinstance(h, dict) for h in generate_state["hypotheses"])

    first_ranking_state = events[6][1]
    assert events[6][0] == "ranking"
    assert first_ranking_state["tournament_matchups"]

    meta_review_state = dict(events)["meta_review"]
    assert meta_review_state["meta_review"]["summary"]

    iterations = [state["current_iteration"] for _, state in events]
    assert iterations == sorted(iterations)
    assert iterations[-1] == 1

    _assert_streaming_final_state(events)


async def test_streaming_and_non_streaming_agree_on_final_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Independent fake runs draw different text from one global counter;
    compare structure."""
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
    """This boundary resumes before scheduling without rerunning completed
    nodes."""
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
    boundary_by_id = {h.id: h for h in boundary["hypotheses"]}
    final_ids = [h.id for h in final["hypotheses"]]

    assert len(final_ids) == len(set(final_ids))
    for hyp in final["hypotheses"]:
        if hyp.id in boundary_by_id:
            assert hyp.text == boundary_by_id[hyp.id].text
    assert set(boundary_by_id) <= set(final_ids)
    assert final.get("termination_reason")
    assert final.get("research_overview")


async def test_resume_preserves_checkpointed_pool_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_llm(monkeypatch)

    states = await _stream_states(_make(), "Explain how protein X folds")
    boundary = states[_pre_orchestrator_index(states)]
    checkpoint = serialize_workflow_state(boundary, last_event_seq=10)

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

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import (
    comprehensive_reflection as review_prompt_context,
)
from co_scientist.agents.reflection import deep_verification_evidence as dve
from co_scientist.agents.reflection import simulation_execution as se
from co_scientist.agents.reflection.review_evidence import (
    _researched_hypothesis_ids,
    _seed_questions,
    research_for_review,
)
from co_scientist.agents.reflection.review_gate import ReviewType
from co_scientist.evidence import search
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.generator import run_setup
from co_scientist.models import Hypothesis
from co_scientist.research import result_from_dict
from co_scientist.research_adapter import (
    review_budget_for_tier,
    reviewed_hypothesis_limit,
)
from co_scientist.workspace.session import WorkspaceSession
from tests._research_fakes import (
    FakeResearchClient,
    _ScriptedModel,
    install_research_client,
    make_search_config,
    research_registry,
)
from tests._state import make_hypothesis, make_state


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> _ScriptedModel:
    model = _ScriptedModel()
    monkeypatch.setattr("co_scientist.research_adapter.call_llm_json", model)
    return model


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> FakeResearchClient:
    return install_research_client(monkeypatch)


def _reflection_research_evidence_state(
    tmp_path: Path, hypotheses: list[Hypothesis], *, tier: str
) -> Any:
    return make_state(
        research_goal="reverse fibrosis",
        model_name="offline/test",
        run_id="run-1",
        hypotheses=hypotheses,
        mcp_available=True,
        research_tier=tier,
        tool_registry=research_registry(tmp_path),
    )


def _viable(text: str, *, elo: int) -> Hypothesis:
    hypothesis = make_hypothesis(text=text)
    hypothesis.review_disposition = "viable"
    hypothesis.elo_rating = elo
    return hypothesis


async def test_a_tier_that_funds_no_reviews_researches_none(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    hypothesis = _viable("mechanism X drives fibrosis", elo=1500)

    found = await research_for_review(
        _reflection_research_evidence_state(
            tmp_path, [hypothesis], tier="standard"
        ),
        hypothesis,
    )

    assert found is None
    assert client.calls == []
    assert scripted.prompts == []


async def test_only_the_best_ranked_hypotheses_are_researched(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    limit = reviewed_hypothesis_limit("extended")
    pool = [_viable(f"mechanism {n}", elo=1000 + n) for n in range(limit + 3)]
    state = _reflection_research_evidence_state(tmp_path, pool, tier="extended")

    funded = _researched_hypothesis_ids(state, "extended")

    assert len(funded) == limit
    assert funded == {h.id for h in pool[-limit:]}
    assert await research_for_review(state, pool[0]) is None
    assert client.calls == []


def test_before_any_tournament_the_review_score_decides(
    tmp_path: Path,
) -> None:
    """Cycle-one Elo is uniform; review scores make the funded set meaningful
    rather than arbitrary."""
    limit = reviewed_hypothesis_limit("extended")
    pool = []
    for n in range(limit + 3):
        hypothesis = _viable(f"mechanism {n}", elo=1200)
        hypothesis.score = 50.0 + n
        pool.append(hypothesis)

    funded = _researched_hypothesis_ids(
        _reflection_research_evidence_state(tmp_path, pool, tier="extended"),
        "extended",
    )

    assert funded == {h.id for h in pool[-limit:]}


async def test_a_funded_hypothesis_researches_and_names_its_searches(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    hypothesis = _viable("mechanism X drives fibrosis", elo=1600)

    found = await research_for_review(
        _reflection_research_evidence_state(
            tmp_path, [hypothesis], tier="extended"
        ),
        hypothesis,
    )

    assert found is not None
    assert [article.source_id for article in found.articles] == ["doc-a"]
    made = result_from_dict(found.ledger).calls
    assert found.articles[0].retrieval_call_id in {call.id for call in made}


async def test_research_asks_about_the_claim_not_only_the_goal(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    hypothesis = _viable("mechanism X drives fibrosis", elo=1600)

    await research_for_review(
        _reflection_research_evidence_state(
            tmp_path, [hypothesis], tier="extended"
        ),
        hypothesis,
    )

    assert any(
        "mechanism X drives fibrosis" in prompt for prompt in scripted.prompts
    )


async def test_the_first_questions_are_the_doubts_already_on_record(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    hypothesis = _viable("mechanism X drives fibrosis", elo=1600)
    hypothesis.enrichments["full"] = {
        "assumptions": [
            {
                "assumption": "the receptor is expressed in humans",
                "support": "uncertain",
            },
            {"assumption": "fibrosis is reversible", "support": "supported"},
        ]
    }

    found = await research_for_review(
        _reflection_research_evidence_state(
            tmp_path, [hypothesis], tier="extended"
        ),
        hypothesis,
    )

    assert found is not None
    asked = [thread["question"]["text"] for thread in found.ledger["threads"]]
    assert "the receptor is expressed in humans" in asked
    assert "fibrosis is reversible" not in asked
    assert not any("perspectives to research" in p for p in scripted.prompts)


async def test_a_hypothesis_with_no_recorded_doubts_plans_its_own(
    tmp_path: Path, scripted: _ScriptedModel, client: FakeResearchClient
) -> None:
    hypothesis = _viable("mechanism X drives fibrosis", elo=1600)

    found = await research_for_review(
        _reflection_research_evidence_state(
            tmp_path, [hypothesis], tier="extended"
        ),
        hypothesis,
    )

    assert found is not None
    assert any("perspectives to research" in p for p in scripted.prompts)


def test_a_simulation_failure_point_is_a_doubt_too() -> None:
    hypothesis = make_hypothesis(text="mechanism X")
    hypothesis.enrichments["simulation"] = {
        "failure_points": ["step 3 needs a cofactor nothing supplies"]
    }

    assert _seed_questions(hypothesis, 4) == [
        "step 3 needs a cofactor nothing supplies"
    ]


def test_seed_questions_stop_at_the_first_level_breadth() -> None:
    hypothesis = make_hypothesis(text="mechanism X")
    hypothesis.enrichments["full"] = {
        "assumptions": [
            {"assumption": f"doubt {n}", "support": "likely_false"}
            for n in range(5)
        ]
    }

    assert _seed_questions(hypothesis, 2) == ["doubt 0", "doubt 1"]


def test_the_run_can_quote_its_review_research_ceiling() -> None:
    for tier, threads in (("extended", 4), ("ultra", 5)):
        budget = review_budget_for_tier(tier, ("alpha",))
        assert budget is not None
        assert budget.max_threads() == threads
    assert review_budget_for_tier("standard", ("alpha",)) is None
    assert review_budget_for_tier("ultra", ()) is None
    assert reviewed_hypothesis_limit("standard") == 0


# Offer run_command explicitly so these tests exercise the loop on every host.
_RUNNABLE_TOOLS = [{"function": {"name": "run_command"}}]


def _reflection_simulation_execution_state(**overrides: Any) -> Any:
    state = make_state(hypotheses=[], current_iteration=0)
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


class TestWhenItRuns:
    async def test_it_is_off_unless_the_caller_asked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = AsyncMock(return_value="observed something")
        monkeypatch.setattr(cr, "simulation_observations", called)

        observations = await cr._observations_for(
            _reflection_simulation_execution_state(),
            make_hypothesis(text="a"),
            ReviewType.SIMULATION,
        )

        assert observations is None
        assert called.await_count == 0

    async def test_only_the_simulation_review_executes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Other review modes cannot answer their questions by execution; tools
        # would only add cost.
        called = AsyncMock(return_value="observed something")
        monkeypatch.setattr(cr, "simulation_observations", called)
        state = _reflection_simulation_execution_state(
            enable_simulation_execution=True
        )

        for review_type in ReviewType:
            if review_type is ReviewType.SIMULATION:
                continue
            assert (
                await cr._observations_for(
                    state, make_hypothesis(text="a"), review_type
                )
                is None
            )
        assert called.await_count == 0

    async def test_it_runs_when_asked_for_the_simulation_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cr,
            "simulation_observations",
            AsyncMock(return_value="the model diverged at step 3"),
        )

        observations = await cr._observations_for(
            _reflection_simulation_execution_state(
                enable_simulation_execution=True
            ),
            make_hypothesis(text="a"),
            ReviewType.SIMULATION,
        )

        assert observations == "the model diverged at step 3"


class TestTheOfflineBackendNeverExecutes:
    def test_an_offline_run_stays_mental(self) -> None:
        # Offline replies emit no tool calls, so an execution loop would observe
        # nothing.
        assert (
            run_setup._resolve_simulation_execution(
                {"enable_simulation_execution": True}, "offline/deterministic"
            )
            is False
        )

    def test_a_real_model_asked_for_may_execute(self) -> None:
        assert (
            run_setup._resolve_simulation_execution(
                {"enable_simulation_execution": True}, "deepseek/some-model"
            )
            is True
        )

    def test_an_omitted_option_is_not_a_request(self) -> None:
        assert (
            run_setup._resolve_simulation_execution({}, "deepseek/some-model")
            is False
        )


class TestDegradation:
    async def test_an_unconfinable_host_reviews_mentally(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An unavailable optional execution instrument must degrade to
        mental review."""
        monkeypatch.setattr(se, "workspace_tool_schemas", lambda policy: [])
        monkeypatch.setattr(
            se,
            "open_review_workspace",
            lambda *a, **k: WorkspaceSession(tmp_path),
        )
        loop = AsyncMock()
        monkeypatch.setattr(se, "call_llm_with_tools", loop)

        result = await se.simulation_observations(
            _reflection_simulation_execution_state(run_id="r1"),
            make_hypothesis(text="a"),
        )

        assert result is None
        assert loop.await_count == 0

    async def test_an_unopenable_workspace_reviews_mentally(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Directory creation can fail before loop guards; propagate that and
        durable retries lose the review."""

        def _no_space(*_args: Any, **_kwargs: Any) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(se, "open_review_workspace", _no_space)

        assert (
            await se.simulation_observations(
                _reflection_simulation_execution_state(run_id="r1"),
                make_hypothesis(text="a"),
            )
            is None
        )

    async def test_a_failing_close_does_not_lose_the_observations(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Cleanup runs in finally; errors there would erase an already completed
        # answer.
        session = WorkspaceSession(tmp_path)

        async def _wont_close() -> None:
            raise OSError("the sandbox is gone")

        monkeypatch.setattr(session.sessions, "close", _wont_close)
        monkeypatch.setattr(
            se, "open_review_workspace", lambda *a, **k: session
        )
        monkeypatch.setattr(
            se, "workspace_tool_schemas", lambda policy: _RUNNABLE_TOOLS
        )
        monkeypatch.setattr(
            se,
            "call_llm_with_tools",
            AsyncMock(return_value=("the model held", [])),
        )

        assert (
            await se.simulation_observations(
                _reflection_simulation_execution_state(run_id="r1"),
                make_hypothesis(text="a"),
            )
            == "the model held"
        )

    async def test_a_failing_loop_reviews_mentally(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            se, "workspace_tool_schemas", lambda policy: _RUNNABLE_TOOLS
        )
        monkeypatch.setattr(
            se,
            "open_review_workspace",
            lambda *a, **k: WorkspaceSession(tmp_path),
        )
        monkeypatch.setattr(
            se,
            "call_llm_with_tools",
            AsyncMock(side_effect=RuntimeError("provider fell over")),
        )

        assert (
            await se.simulation_observations(
                _reflection_simulation_execution_state(run_id="r1"),
                make_hypothesis(text="a"),
            )
            is None
        )

    async def test_an_empty_answer_is_not_an_observation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # No observation differs from executing successfully and observing
        # nothing.
        monkeypatch.setattr(
            se, "workspace_tool_schemas", lambda policy: _RUNNABLE_TOOLS
        )
        monkeypatch.setattr(
            se,
            "open_review_workspace",
            lambda *a, **k: WorkspaceSession(tmp_path),
        )
        monkeypatch.setattr(
            se, "call_llm_with_tools", AsyncMock(return_value=("  \n ", []))
        )

        assert (
            await se.simulation_observations(
                _reflection_simulation_execution_state(run_id="r1"),
                make_hypothesis(text="a"),
            )
            is None
        )


class TestTheSessionsItLeaves:
    async def test_a_command_still_running_is_ended_with_the_loop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Sessions outlive calls; the owning review loop must end its hung
        commands."""
        session = WorkspaceSession(tmp_path)
        monkeypatch.setattr(
            se, "open_review_workspace", lambda *a, **k: session
        )
        monkeypatch.setattr(
            se, "workspace_tool_schemas", lambda policy: _RUNNABLE_TOOLS
        )

        started: list[dict[str, Any]] = []

        async def _hang(**kwargs: Any) -> tuple[str, list[Any]]:
            message = await kwargs["loop"].executor(
                _tool_call(argv=["bash", "-lc", "sleep 60"], yield_seconds=0.05)
            )
            started.append(json.loads(message["content"]))
            return "the model did not converge", []

        monkeypatch.setattr(se, "call_llm_with_tools", _hang)

        await se.simulation_observations(
            _reflection_simulation_execution_state(run_id="r1"),
            make_hypothesis(text="a"),
        )

        # Assert outside the exception-swallowing loop so failures cannot
        # resemble a pass.
        assert started and started[0]["running"] is True
        assert session.sessions._sessions == {}


def _tool_call(**arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="run_command", arguments=json.dumps(arguments)
        ),
    )


class TestWhatTheReviewerSees:
    def test_observations_are_handed_to_the_reviewer(self) -> None:
        variables = cr._prompt_variables(
            _reflection_simulation_execution_state(),
            make_hypothesis(text="a"),
            ReviewType.SIMULATION,
            None,
            "peak concentration 4.1 uM at t=90s",
        )

        assert (
            "peak concentration 4.1 uM" in (variables["execution_observations"])
        )

    def test_no_execution_says_so_rather_than_leaving_a_gap(self) -> None:
        variables = cr._prompt_variables(
            _reflection_simulation_execution_state(),
            make_hypothesis(text="a"),
            ReviewType.SIMULATION,
            None,
        )

        assert (
            variables["execution_observations"]
            == review_prompt_context._NO_EXECUTION_NOTE
        )

    def test_the_template_carries_the_section(self) -> None:
        from co_scientist.prompts.loading import load_prompt

        prompt = load_prompt(
            "simulation_review",
            cr._prompt_variables(
                _reflection_simulation_execution_state(),
                make_hypothesis(text="a"),
                ReviewType.SIMULATION,
                None,
                "the rate constant is 40x too small",
            ),
        )

        assert "the rate constant is 40x too small" in prompt
        assert "{{" not in prompt


class TestProvenance:
    async def test_an_executed_review_is_marked_executed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cr, "call_llm_json", AsyncMock(return_value={"verdict": "holds"})
        )
        monkeypatch.setattr(
            cr,
            "simulation_observations",
            AsyncMock(return_value="it held to 3 sig figs"),
        )

        _, result, _ = await cr._run_review(
            _reflection_simulation_execution_state(
                enable_simulation_execution=True
            ),
            make_hypothesis(text="a"),
            ReviewType.SIMULATION,
        )

        assert result is not None
        assert result["executed"] is True
        assert result["execution_observations"] == "it held to 3 sig figs"

    async def test_a_mental_review_is_marked_not_executed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Executed and imagined breakdowns are different provenance claims.
        monkeypatch.setattr(
            cr,
            "call_llm_json",
            AsyncMock(return_value={"verdict": "breaks_down"}),
        )

        _, result, _ = await cr._run_review(
            _reflection_simulation_execution_state(),
            make_hypothesis(text="a"),
            ReviewType.SIMULATION,
        )

        assert result is not None
        assert result["executed"] is False
        assert "execution_observations" not in result

    async def test_other_reviews_carry_no_execution_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
        )

        _, result, _ = await cr._run_review(
            _reflection_simulation_execution_state(),
            make_hypothesis(text="a"),
            ReviewType.FULL,
        )

        assert result is not None
        assert "executed" not in result


class TestIsolation:
    def test_two_reviews_of_one_run_do_not_share_a_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Concurrent leased reviews sharing a directory would report
        observations of each other's models."""
        from co_scientist.workspace import run_workspace

        monkeypatch.setattr(run_workspace, "workspaces_root", lambda: tmp_path)

        first = run_workspace.open_review_workspace("run-1", "hyp-a")
        second = run_workspace.open_review_workspace("run-1", "hyp-b")

        assert first.root != second.root
        assert first.root.is_dir() and second.root.is_dir()


def test_the_simulation_loop_carries_its_own_spend_ceiling() -> None:
    """Measured simulations gained no observation quality above their own
    spend ceiling."""
    from co_scientist.agents.reflection.simulation_execution import (
        MAX_SIMULATION_TURNS,
        SIMULATION_TOKEN_BUDGET,
    )
    from co_scientist.llm import DEFAULT_TOOL_LOOP_TOKEN_BUDGET

    assert SIMULATION_TOKEN_BUDGET < DEFAULT_TOOL_LOOP_TOKEN_BUDGET
    assert 30_000 <= SIMULATION_TOKEN_BUDGET <= 60_000
    assert MAX_SIMULATION_TURNS == 14


def _config(*, semantic_relevance_enabled: bool) -> SearchConfig:
    return make_search_config(
        search_tool_name="search_pubmed",
        source_name="pubmed",
        papers_to_read_count=6,
        research_goal="a research goal",
        model_name="offline/deterministic",
        semantic_relevance_enabled=semantic_relevance_enabled,
    )


def _ranked() -> dict[str, dict[str, Any]]:
    return {
        "best": {"title": "Best", "retrieval_score": 5.0},
        "worst": {"title": "Worst", "retrieval_score": 1.5},
    }


async def test_disabled_pass_costs_nothing_and_keeps_lexical_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def _never(*args: Any, **kwargs: Any) -> dict[str, dict[str, Any]]:
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(search, "apply_semantic_relevance", _never)

    ranked = _ranked()
    result = await search._apply_semantic_relevance_if_enabled(
        ranked, _config(semantic_relevance_enabled=False)
    )

    assert calls == 0
    assert list(result.keys()) == ["best", "worst"]


async def test_enabled_pass_still_runs_for_the_run_level_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def _judge(
        ranked: dict[str, dict[str, Any]], *args: Any, **kwargs: Any
    ) -> dict[str, dict[str, Any]]:
        nonlocal calls
        calls += 1
        return ranked

    monkeypatch.setattr(search, "apply_semantic_relevance", _judge)

    await search._apply_semantic_relevance_if_enabled(
        _ranked(), _config(semantic_relevance_enabled=True)
    )

    assert calls == 1


async def test_probe_retrieval_opts_out_of_the_relevance_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[SearchConfig] = []

    async def _collect(
        queries: list[str],
        state: Any,
        config: SearchConfig,
        client: Any,
        errors: list[str],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        seen.append(config)
        return {}, {}

    monkeypatch.setattr(
        "co_scientist.evidence.search.collect_papers",
        _collect,
    )
    monkeypatch.setattr(
        "co_scientist.evidence.search_support.search_config_for",
        lambda state: _config(semantic_relevance_enabled=True),
    )

    async def _client(**kwargs: Any) -> Any:
        return object()

    monkeypatch.setattr("co_scientist.mcp_client.get_mcp_client", _client)

    await dve._retrieve_probe_evidence(
        make_state(mcp_available=True), ["a probe query"]
    )

    assert len(seen) == 1
    assert seen[0].semantic_relevance_enabled is False
    assert seen[0].papers_to_read_count == dve._MAX_PROBE_SOURCES

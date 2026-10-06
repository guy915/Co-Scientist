from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import simulation_execution as se
from co_scientist.agents.reflection.review_evidence import (
    _seed_questions,
    research_for_review,
)
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.generator import run_setup
from co_scientist.models import Hypothesis
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


def test_a_simulation_failure_point_is_a_doubt_too() -> None:
    hypothesis = make_hypothesis(text="mechanism X")
    hypothesis.enrichments["simulation"] = {
        "failure_points": ["step 3 needs a cofactor nothing supplies"]
    }

    assert _seed_questions(hypothesis, 4) == [
        "step 3 needs a cofactor nothing supplies"
    ]


# Offer run_command explicitly so these tests exercise the loop on every host.
_RUNNABLE_TOOLS = [{"function": {"name": "run_command"}}]


def _reflection_simulation_execution_state(**overrides: Any) -> Any:
    state = make_state(hypotheses=[], current_iteration=0)
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


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


class TestDegradation:
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


def _config(*, semantic_relevance_enabled: bool) -> SearchConfig:
    return make_search_config(
        search_tool_name="search_pubmed",
        source_name="pubmed",
        papers_to_read_count=6,
        research_goal="a research goal",
        model_name="offline/deterministic",
        semantic_relevance_enabled=semantic_relevance_enabled,
    )

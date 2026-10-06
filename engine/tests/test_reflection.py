from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

import co_scientist.agents.reflection.deep_verification as leaf
from co_scientist.agents.reflection import (
    ReviewRun,
    ReviewType,
    apply_initial_review_gate,
    deep_verification_evidence,
    observe_hypothesis,
    reflection,
    review_hypothesis,
    select_hypotheses_to_verify,
    verify_hypothesis,
)
from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import (
    comprehensive_reflection as review_prompt_context,
)
from co_scientist.agents.reflection import deep_verification as dv
from co_scientist.agents.reflection import reflection as observation
from co_scientist.agents.reflection import review_evidence as ev
from co_scientist.agents.reflection import simulation_execution as se
from co_scientist.agents.reflection.deep_verification import (
    mark_verification_issued,
    verification_fingerprint,
)
from co_scientist.agents.reflection.reflection import reflection_node
from co_scientist.agents.reflection.reflection_helpers import (
    extract_entity_names,
    fetch_indra_evidence,
    get_kg_tools_for_workflow,
)
from co_scientist.agents.reflection.review_evidence import (
    ReviewResearch,
    _seed_questions,
    research_for_review,
)
from co_scientist.config import ToolRegistry
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from co_scientist.generator import run_setup
from co_scientist.models import Article, Hypothesis
from co_scientist.workspace.session import WorkspaceSession
from tests._llm_fake import mock_call_llm_json, stub_call_llm_json
from tests._mcp import WorkflowToolRegistry
from tests._research_fakes import (
    FakeResearchClient,
    _ScriptedModel,
    install_research_client,
    make_search_config,
    research_registry,
)
from tests._state import make_article, make_hypothesis, make_review, make_state

_ARTICLES = "Article 1: observation A supports pathway X."


@pytest.mark.parametrize("pool", [[], [make_hypothesis(text="a hypothesis")]])
async def test_reflection_needs_hypotheses_and_literature_to_run(
    pool: list[Any],
) -> None:
    articles = _ARTICLES if not pool else None
    state = make_state(hypotheses=pool, articles_with_reasoning=articles)
    assert await reflection_node(state) == {}


async def test_empty_llm_response_defaults_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hyp = make_hypothesis(text="some hypothesis")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(monkeypatch, reflection, {})

    result = await reflection_node(state)

    assert result["hypotheses"][0].reflection_notes == (
        "\n\nClassification: neutral"
    )
    assert "indra_evidence" not in result["hypotheses"][0].enrichments


def _validation_article() -> Article:
    return Article(
        title="Targeted validation",
        source_id="validation-1",
        abstract="The proposed mechanism survived direct testing.",
        used_in_analysis=True,
    )


async def test_later_cycle_runs_recurrent_review_with_tournament_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = mock_call_llm_json(monkeypatch, cr, {"verdict": "needs_revision"})
    hypothesis = make_hypothesis(text="mature", elo_rating=1337)
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments.update({"full": {}, "simulation": {}})
    state = make_state(
        hypotheses=[hypothesis],
        current_iteration=2,
        meta_review={"common_weaknesses": ["missing control"]},
    )

    await cr.comprehensive_reflection_node(state)
    await cr.comprehensive_reflection_node(state)

    assert fake.await_count == 1
    call = fake.await_args
    assert call is not None
    prompt = call.kwargs["prompt"]
    assert "recurrent/tournament review" in prompt
    assert "1337" in prompt
    assert hypothesis.enrichments["recurrent_review_iteration"] == 2


async def test_missing_observation_review_appends_confirmed_strengths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hypothesis = make_hypothesis(
        text="evolved child",
        review_disposition="viable",
        enrichments={"full": {}, "simulation": {}},
    )
    observation = AsyncMock(
        return_value={
            "classification": "missing_piece",
            "reasoning": "explains x",
            "positive_observations": ["accounts for the late onset"],
        }
    )
    monkeypatch.setattr(cr, "observe_hypothesis", observation)
    mock_call_llm_json(monkeypatch, cr, {})

    await cr.comprehensive_reflection_node(
        make_state(
            hypotheses=[hypothesis],
            current_iteration=0,
            articles_with_reasoning="retrieved observations",
        )
    )

    notes = hypothesis.reflection_notes or ""
    assert "accounts for the late onset" in notes
    assert notes.index("accounts for the late onset") < notes.index(
        "Classification: missing_piece"
    )
    assert hypothesis.enrichments["observation"]["positive_observations"] == [
        "accounts for the late onset"
    ]


def _stub_review_research(
    monkeypatch: pytest.MonkeyPatch, *, fails: bool = False
) -> None:

    async def fake_research(_state: object, _hypothesis: object) -> object:
        if fails:
            raise RuntimeError("source unreachable")
        return ReviewResearch(
            articles=[
                Article(
                    title="Researched paper",
                    source_id="researched-1",
                    abstract="Human evidence for the mechanism.",
                    retrieval_call_id="call-1",
                )
            ],
            ledger={"goal": "g", "threads": [], "calls": [], "findings": []},
        )

    monkeypatch.setattr(ev, "research_for_review", fake_research)


async def test_a_review_whose_research_broke_is_still_a_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    monkeypatch.setattr(
        ev,
        "_retrieve_probe_evidence",
        AsyncMock(return_value=([_validation_article()], [])),
    )
    monkeypatch.setattr(
        ev,
        "_call_hypothesis_query_llm",
        AsyncMock(return_value={"queries": ["targeted query"]}),
    )
    mock_call_llm_json(monkeypatch, cr, {"verdict": "sound"})
    _stub_review_research(monkeypatch, fails=True)
    hypothesis = make_hypothesis(text="a mechanism worth reviewing")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    reviewed, ledgers = await cr._review_hypothesis(state, hypothesis)

    assert reviewed == 2
    assert ledgers == []
    stored = hypothesis.enrichments["full"]["retrieved_articles"]
    assert [item["source_id"] for item in stored] == ["validation-1"]


async def test_the_node_carries_every_hypothesis_ledger_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ledgers kept inside reviews never reach the persistence drain."""
    mock_call_llm_json(monkeypatch, cr, {"verdict": "sound"})
    _stub_review_research(monkeypatch)
    viable = [make_hypothesis(text="a"), make_hypothesis(text="b")]
    for hypothesis in viable:
        hypothesis.review_disposition = "viable"

    result = await cr.comprehensive_reflection_node(
        make_state(hypotheses=viable, current_iteration=0)
    )

    assert len(result["research_ledgers"]) == 2


def _fake(
    tool_ids: list[str],
    mcp_names: list[str],
    raise_on_workflow: bool = False,
    source_type: str = "knowledge_graph",
) -> ToolRegistry:
    return cast(
        ToolRegistry,
        WorkflowToolRegistry(
            tool_ids, mcp_names, raise_on_workflow, source_type
        ),
    )


_REGISTRY_CASES = [
    (None, []),
    (_fake(tool_ids=[], mcp_names=["unused"]), []),
    (
        _fake(
            tool_ids=["indra_a", "indra_b"],
            mcp_names=["get_relations", "get_complexes"],
        ),
        ["get_relations", "get_complexes"],
    ),
    (_fake(["x"], ["y"], raise_on_workflow=True), []),
    # INDRA entity arguments are invalid for literature tools.
    (
        _fake(
            ["pubmed_fulltext"],
            ["pubmed_search_with_fulltext"],
            source_type="academic",
        ),
        [],
    ),
]


@pytest.mark.parametrize(("registry", "tools"), _REGISTRY_CASES)
def test_only_knowledge_graph_tools_are_selected_for_reflection(
    registry: ToolRegistry | None, tools: list[str]
) -> None:
    assert get_kg_tools_for_workflow(registry, "reflection") == tools


@pytest.mark.parametrize(
    ("text", "entities"),
    [
        ("IL-6 activates TREM2 in microglia", ["IL6", "TREM2"]),
        ("Kras drives growth", []),
        ("DNA and RNA bind", []),
        ("KRAS G12C variant", ["KRAS"]),
        ("P53 pathway", []),
        ("RAGE signaling", ["AGER"]),
        ("IL-6 and IL together", ["IL6"]),
        ("YKL-40 and YKL-40 again", ["CHI3L1"]),
    ],
)
def test_entity_extraction_keeps_gene_symbols_only(
    text: str, entities: list[str]
) -> None:
    assert extract_entity_names(text) == entities
    assert (
        len(extract_entity_names("KRAS TREM2 APOE TP53", max_entities=2)) == 2
    )


def _fake_registry() -> ToolRegistry:
    """Knowledge-graph source typing is required because literature tools
    reject INDRA arguments."""
    return cast(
        ToolRegistry,
        WorkflowToolRegistry(
            ["indra_relations"],
            ["get_relations"],
            tool_mcp_names={"indra_relations": "get_relations"},
        ),
    )


class _FakeMcpClient:
    def __init__(
        self,
        available_tools: set[str],
        responses: dict[str, Any] | None = None,
    ) -> None:
        self._available_tools = available_tools
        self._responses = responses or {}

    def has_tool(self, name: str) -> bool:
        return name in self._available_tools

    async def call_tool(self, _tool_name: str, **kwargs: Any) -> Any:
        entity = kwargs["agent"]
        if entity not in self._responses:
            return {"statements": []}
        response = self._responses[entity]
        if response is None:
            raise RuntimeError(f"simulated query failure for {entity}")
        return response


_ACTIVATION_STATEMENT = {
    "type": "Activation",
    "belief": 0.9,
    "evidence": [1, 2],
    "subj": {"name": "KRAS"},
    "obj": {"name": "BRAF"},
}


async def test_fetch_indra_evidence_returns_client_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeMcpClient(
        available_tools={"get_relations"},
        responses={
            "KRAS": json.dumps({"statements": [_ACTIVATION_STATEMENT]}),
        },
    )

    async def fake_get_mcp_client(**_: Any) -> _FakeMcpClient:
        return fake_client

    monkeypatch.setattr(
        "co_scientist.mcp_client.get_mcp_client", fake_get_mcp_client
    )

    result = await fetch_indra_evidence(
        "KRAS drives tumor growth", tool_registry=_fake_registry()
    )

    assert "KRAS --[Activation]--> BRAF" in result["prompt_text"]
    assert result["enrichment_items"]


def test_retracted_evidence_never_reaches_a_prompt() -> None:
    """Retraction checks belong at every formatting boundary, not only
    retrieval."""
    retracted = make_article(
        "Retracted paper",
        abstract="Withdrawn mechanistic claim.",
        used_in_analysis=True,
        is_retracted=True,
    )
    only_retracted = make_state(articles=[retracted])
    assert (
        review_prompt_context._build_domain_context(only_retracted, None) == ""
    )
    assert (
        deep_verification_evidence._retrieved_evidence_context([retracted])
        == ""
    )
    state = make_state(
        articles=[
            make_article(
                "Retracted paper",
                abstract="Withdrawn mechanistic claim.",
                used_in_analysis=True,
                is_retracted=True,
            ),
            make_article(
                "Standing paper",
                abstract="Replicated mechanistic finding.",
                used_in_analysis=True,
            ),
        ]
    )

    context = dv._verification_evidence_context(state)

    assert "Standing paper" in context
    assert "Retracted paper" not in context
    assert "Withdrawn mechanistic claim" not in context


def test_gate_honors_scientist_criteria_and_safety() -> None:
    ideas = [make_hypothesis(), make_hypothesis()]
    reviews = [
        make_review(scores={"novelty": 1, "testability": 8, "safety": 8}),
        make_review(scores={"testability": 8, "safety": 1}),
    ]
    apply_initial_review_gate(ideas, reviews, ["Experimental feasibility"])
    assert [idea.review_disposition for idea in ideas] == ["viable", "unsafe"]


def test_selection_preserves_pool_order_and_once_ever_markers() -> None:
    pending = make_hypothesis()
    blocked = make_hypothesis(review_disposition="unsafe")
    issued = make_hypothesis()
    mark_verification_issued(issued)
    current = make_hypothesis()
    current.deep_verification_fingerprint = verification_fingerprint(
        current, "m"
    )
    next_pending = make_hypothesis()
    assert select_hypotheses_to_verify(
        [pending, blocked, issued, current, next_pending], "m"
    ) == [pending, next_pending]
    assert not pending.enrichments


@pytest.mark.asyncio
async def test_single_verification_assembles_bounded_context_and_local_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semaphores: list[asyncio.Semaphore] = []
    contexts: list[str] = []

    async def capture(
        semaphore: asyncio.Semaphore,
        hypothesis: Any,
        context: Any,
        evidence: str,
    ) -> dict[str, Any]:
        assert context.state is state
        semaphores.append(semaphore)
        contexts.append(evidence)
        return {"verdict": "holds"}

    state = make_state(
        articles=[
            make_article(
                "Long evidence", abstract="x" * 100000, used_in_analysis=True
            )
        ],
        context_enrichment_sources=[{"display": "y" * 100000}],
        meta_review={"common_weaknesses": ["Recurring assumption error"]},
    )
    monkeypatch.setattr(leaf, "_verify_within_semaphore", capture)
    for _ in range(2):
        assert await verify_hypothesis(state, make_hypothesis()) == {
            "verdict": "holds"
        }
    assert semaphores[0] is not semaphores[1]
    assert all(semaphore._value == 1 for semaphore in semaphores)
    assert all(len(context) < 20000 for context in contexts)
    assert "Long evidence" in contexts[0]
    assert "Recurring assumption error" in contexts[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,owner",
    [
        (verify_hypothesis, leaf),
        (observe_hypothesis, observation),
        (review_hypothesis, cr),
    ],
)
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("ordinary"),
        LLMRateLimitParkError(9999, "cap"),
        LLMCallBudgetExceededError(2, 1),
    ],
)
async def test_failures_degrade_but_task_control_propagates(
    monkeypatch: pytest.MonkeyPatch,
    operation: Any,
    owner: Any,
    error: Exception,
) -> None:
    mock_call_llm_json(monkeypatch, owner, side_effect=error)
    state = make_state(articles_with_reasoning="Retrieved literature")
    args = (
        (state, make_hypothesis(), ReviewType.FULL)
        if operation is review_hypothesis
        else (state, make_hypothesis())
    )
    if isinstance(error, RuntimeError):
        result = await operation(*args)
        assert (
            result.result if isinstance(result, ReviewRun) else result
        ) is None
    else:
        with pytest.raises(type(error)) as caught:
            await operation(*args)
        assert caught.value is error


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

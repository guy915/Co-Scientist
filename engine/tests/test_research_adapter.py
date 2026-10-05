from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from co_scientist.agents.generation.expansion_research import (
    EXPANSION_EXTRA_DRAFT_ITERATIONS,
    EXPANSION_POOL_ITEM_CHARS,
    EXPANSION_POOL_SAMPLE_SIZE,
    ExpansionResearch,
    build_expansion_section,
    explored_hypothesis_summaries,
    is_research_expansion,
    research_for_expansion,
)
from co_scientist.agents.generation.literature_tools.draft import (
    _compute_draft_iteration_budget,
)
from co_scientist.agents.reflection.review_evidence import research_for_review
from co_scientist.constants import get_draft_max_iterations
from co_scientist.generator.run_setup import _resolve_research_tier
from co_scientist.mcp_client import MCPToolClient
from co_scientist.prompts import DraftPromptRequest, get_draft_prompt_with_tools
from co_scientist.research import (
    CallStatus,
    Document,
    Finding,
    Question,
    ResearchBudget,
    ResearchResult,
    RetrievalError,
    SearchCall,
    SourceHit,
    StopReason,
    ThreadRecord,
    ThreadStatus,
    result_from_dict,
    result_to_dict,
)
from co_scientist.research.loop import admit_within_budget
from co_scientist.research_adapter import (
    LlmResearchModel,
    McpRetrieval,
    ResearchRun,
    budget_for_tier,
)
from tests._research_fakes import (
    FakeResearchClient,
    _hits,
    _ScriptedModel,
    install_research_client,
    research_registry,
    research_workflow,
)
from tests._state import make_hypothesis, make_state


def _retrieval(tmp_path: Path, client: Any) -> McpRetrieval:
    registry = research_registry(tmp_path)
    workflow = research_workflow(registry)
    return McpRetrieval(
        client,
        registry,
        workflow,
        ResearchRun(run_id="run-1", research_goal="fibrosis reversal"),
    )


_HITS = {
    "doc-a": {"title": "First", "abstract": "About a", "pdf_url": "u/a"},
    "doc-b": {"title": "Second", "abstract": "About b", "doi": "10.1/b"},
}


async def test_search_keeps_the_source_ordering_and_the_limit(
    tmp_path: Path,
) -> None:
    retrieval = _retrieval(
        tmp_path, FakeResearchClient({"search_alpha": _HITS})
    )

    hits = await retrieval.search(query="fibrosis", source="alpha", limit=5)
    first_only = await retrieval.search(
        query="fibrosis", source="alpha", limit=1
    )

    assert [hit.locator for hit in hits] == ["doc-a", "doc-b"]
    assert [hit.rank for hit in hits] == [0, 1]
    assert hits[1].metadata["doi"] == "10.1/b"
    assert hits[0].metadata["source"] == "alpha"
    assert [hit.locator for hit in first_only] == ["doc-a"]
    assert retrieval.sources == ("alpha",)


async def test_an_unconfigured_source_is_a_retrieval_error(
    tmp_path: Path,
) -> None:
    retrieval = _retrieval(tmp_path, FakeResearchClient({}))

    with pytest.raises(RetrievalError) as caught:
        await retrieval.search(query="q", source="gamma", limit=2)

    assert caught.value.source == "gamma"


async def test_a_broken_source_is_a_retrieval_error_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "co_scientist.evidence.search_query._search_retry_delay",
        lambda attempt: 0.0,
    )
    client = FakeResearchClient(
        {"search_alpha": RuntimeError("connection refused")}
    )
    retrieval = _retrieval(tmp_path, client)

    with pytest.raises(RetrievalError) as caught:
        await retrieval.search(query="q", source="alpha", limit=2)

    assert caught.value.source == "alpha"
    assert "connection refused" in str(caught.value)


async def test_reading_a_hit_fetches_its_full_text(tmp_path: Path) -> None:
    client = FakeResearchClient(
        {"search_alpha": _HITS, "read_pdf": {"content": "the whole paper"}}
    )
    retrieval = _retrieval(tmp_path, client)
    await retrieval.search(query="fibrosis", source="alpha", limit=5)

    text = await retrieval.read(locator="doc-a")

    assert text == "the whole paper"
    assert client.calls[-1][1]["url"] == "u/a"


@pytest.mark.parametrize(
    ("locator", "read_pdf"),
    [
        ("doc-b", {"content": "x"}),
        ("never-seen", {"content": "x"}),
        ("doc-a", RuntimeError("timeout")),
    ],
    ids=["no-url", "never-searched", "failed-read"],
)
async def test_an_unreadable_hit_reads_as_nothing_not_as_an_error(
    tmp_path: Path, locator: str, read_pdf: object
) -> None:
    client = FakeResearchClient({"search_alpha": _HITS, "read_pdf": read_pdf})
    retrieval = _retrieval(tmp_path, client)
    await retrieval.search(query="fibrosis", source="alpha", limit=5)

    assert await retrieval.read(locator=locator) is None


class _FakeLlm:
    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.specs: list[Any] = []

    async def __call__(
        self, prompt: str, spec: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.specs.append(spec)
        return self.answers.pop(0) if self.answers else {}


def _model(
    monkeypatch: pytest.MonkeyPatch, *answers: dict[str, Any]
) -> tuple[LlmResearchModel, _FakeLlm]:
    fake = _FakeLlm(*answers)
    monkeypatch.setattr("co_scientist.research_adapter.call_llm_json", fake)
    return LlmResearchModel("offline/test", run_id="run-1"), fake


def _document(locator: str, text: str = "body") -> Document:
    return Document(
        hit=SourceHit(
            locator=locator, title=f"T {locator}", snippet="s", rank=0
        ),
        text=text,
        full_text=True,
    )


async def test_stances_and_questions_stay_inside_their_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, _ = _model(
        monkeypatch,
        {"stances": ["mechanism", "counter-evidence", "prior art", "extra"]},
        {"questions": ["q1", "q2", "q3"]},
    )

    stances = await model.plan_stances(goal="fibrosis", limit=3)
    questions = await model.ask_questions(
        goal="fibrosis", stance="mechanism", limit=2
    )

    assert list(stances) == ["mechanism", "counter-evidence", "prior art"]
    assert list(questions) == ["q1", "q2"]


async def test_a_query_the_model_would_not_write_falls_back_to_the_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, _ = _model(monkeypatch, {})

    assert await model.to_query(question="What drives fibrosis?") == (
        "What drives fibrosis?"
    )


async def test_findings_are_bound_by_index_not_by_echoed_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Echoed document titles scale output with the pool and truncate
    identical retries."""
    model, fake = _model(
        monkeypatch,
        {
            "findings": [
                {"document": 1, "claim": "B causes X", "quote": "b says so"}
            ],
            "follow_ups": ["what about Y?"],
        },
    )
    documents = [_document("doc-a"), _document("doc-b")]

    extraction = await model.extract(question="why X?", documents=documents)

    assert "[0] T doc-a" in fake.prompts[0]
    assert "[1] T doc-b" in fake.prompts[0]
    assert [f.locator for f in extraction.findings] == ["doc-b"]
    assert extraction.findings[0].span == "b says so"
    assert extraction.follow_ups == ("what about Y?",)


async def test_extraction_prompt_strips_citation_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Copied document citations can misattribute generated findings to real
    sources."""
    model, fake = _model(monkeypatch, {"findings": [], "follow_ups": []})
    original = "This confirms prior work (Smith et al. 2019) [12]."
    documents = [_document("doc-a", text=original)]

    await model.extract(question="why X?", documents=documents)

    assert "(Smith et al. 2019)" not in fake.prompts[0]
    assert "[12]" not in fake.prompts[0]
    assert documents[0].text == original


async def test_a_finding_that_names_no_real_document_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, _ = _model(
        monkeypatch,
        {
            "findings": [
                {"document": 7, "claim": "c", "quote": "q"},
                {"document": 0, "claim": "kept", "quote": "q"},
                {"document": 0, "claim": "no quote", "quote": "  "},
            ]
        },
    )

    extraction = await model.extract(
        question="why X?", documents=[_document("doc-a")]
    )

    assert [f.text for f in extraction.findings] == ["kept"]


async def test_nothing_to_read_or_summarize_costs_no_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, fake = _model(monkeypatch)

    assert await model.extract(question="q", documents=[]) == (
        await model.extract(question="q", documents=[])
    )
    assert await model.compress(question="q", findings=[]) == ""
    assert fake.prompts == []


async def test_every_call_sets_its_own_token_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset budgets use provider defaults; document extraction needs a
    larger answer allowance."""
    model, fake = _model(
        monkeypatch, {"query": "fibrosis mechanism"}, {"findings": []}
    )

    await model.to_query(question="what drives fibrosis?")
    await model.extract(question="q", documents=[_document("doc-a")])

    assert all(spec.max_tokens > 0 for spec in fake.specs)
    assert fake.specs[1].max_tokens > fake.specs[0].max_tokens


@pytest.mark.parametrize(
    ("tier", "sources", "threads"),
    [
        ("express", ["alpha"], None),
        ("standard", ["alpha"], None),
        ("unknown-tier", ["alpha"], None),
        ("ultra", [], None),
        ("extended", ["alpha"], 6),
        ("ultra", ["alpha", "beta"], 11),
    ],
)
def test_only_the_deep_tiers_with_a_source_buy_research_and_state_their_cost(
    tier: str, sources: list[str], threads: int | None
) -> None:
    budget = budget_for_tier(tier, sources)

    if threads is None:
        assert budget is None
    else:
        assert budget is not None
        assert budget.max_threads() == threads
        assert budget.sources == tuple(sources)


@pytest.mark.parametrize(
    ("options", "mcp_available", "tier"),
    [
        ({}, True, ""),
        ({"research_tier": ""}, True, ""),
        ({"research_tier": "ultra"}, False, ""),
        ({"research_tier": "ultra"}, True, "ultra"),
    ],
    ids=["no-tier", "empty-tier", "no-mcp", "offline-backend-researches"],
)
def test_research_is_requested_only_where_there_is_something_to_search(
    options: dict[str, str], mcp_available: bool, tier: str
) -> None:
    assert _resolve_research_tier(options, mcp_available) == tier


@pytest.fixture
def expansion_model(monkeypatch: pytest.MonkeyPatch) -> _ScriptedModel:
    model = _ScriptedModel()
    monkeypatch.setattr("co_scientist.research_adapter.call_llm_json", model)
    return model


@pytest.fixture
def expansion_client(monkeypatch: pytest.MonkeyPatch) -> FakeResearchClient:
    return install_research_client(monkeypatch)


@pytest.mark.parametrize(
    ("iteration", "expansion"),
    [(None, False), (0, False), (1, True), (3, True)],
)
def test_only_later_generate_cycles_are_expansion(
    iteration: int | None, expansion: bool
) -> None:
    state = (
        make_state()
        if iteration is None
        else make_state(current_iteration=iteration)
    )

    assert is_research_expansion(state) is expansion
    assert (build_expansion_section(state) != "") is expansion


def test_expansion_section_names_the_explored_pool_bounded() -> None:
    long_text = "explored direction " + "x" * 500
    hypotheses = [make_hypothesis(text=f"hyp {i}") for i in range(20)]
    hypotheses.append(make_hypothesis(text=long_text))
    state = make_state(current_iteration=1, hypotheses=hypotheses)

    summaries = explored_hypothesis_summaries(state)
    section = build_expansion_section(state)

    assert len(summaries) == EXPANSION_POOL_SAMPLE_SIZE
    assert all(len(s) <= EXPANSION_POOL_ITEM_CHARS + 3 for s in summaries)
    assert "Research Expansion Cycle" in section
    assert "hyp 0" in section
    assert "hyp 15" not in section
    assert "do NOT re-derive" in section


def test_expansion_section_without_a_pool_or_findings_names_no_ground() -> None:
    section = build_expansion_section(
        make_state(current_iteration=1, hypotheses=[])
    )

    assert "Research Expansion Cycle" in section
    assert "already explored" not in section
    assert "Ground new hypotheses in this material" not in section


def test_explored_findings_reach_the_expansion_section() -> None:
    explored = ExpansionResearch(
        section="- collagen crosslinking is under-studied [PMID:1]\n",
        articles=[],
        ledger={},
    )
    state = explored.applied_to(make_state(current_iteration=1))

    assert "collagen crosslinking is under-studied [PMID:1]" in (
        build_expansion_section(state)
    )


def test_draft_prompt_renders_the_expansion_and_falsified_sections() -> None:
    request = DraftPromptRequest(
        research_goal="repurpose a kinase inhibitor",
        hypotheses_count=2,
        research_expansion_section=build_expansion_section(
            make_state(current_iteration=1)
        ),
        falsified_assumptions_section=(
            "## Assumptions Verified Incorrect (avoid or rework)\n"
            "- Does efflux matter? -- finding: no.\n"
        ),
    )
    plain, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="repurpose a kinase inhibitor", hypotheses_count=2
        )
    )

    prompt, _ = get_draft_prompt_with_tools(request)

    assert "Research Expansion Cycle" in prompt
    assert "Does efflux matter?" in prompt
    assert "{{MISSING" not in prompt
    assert "Research Expansion Cycle" not in plain
    assert "Verified Incorrect" not in plain
    assert "{{MISSING" not in plain


def test_expansion_draft_budget_gets_extra_retrieval_rounds() -> None:
    base = _compute_draft_iteration_budget(3)

    assert base == get_draft_max_iterations(3)
    assert _compute_draft_iteration_budget(3, is_expansion=True) == (
        base + EXPANSION_EXTRA_DRAFT_ITERATIONS
    )


@pytest.mark.parametrize(
    ("iteration", "tier"), [(0, "extended"), (1, "standard")]
)
async def test_no_exploration_without_an_expansion_cycle_or_a_funded_tier(
    iteration: int, tier: str
) -> None:
    state = make_state(current_iteration=iteration, research_tier=tier)

    assert await research_for_expansion(state) is None


@pytest.mark.parametrize("consumer", ["expansion", "review"])
async def test_unavailable_mcp_stops_research_before_client_acquisition(
    consumer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable(**kwargs: Any) -> MCPToolClient:
        pytest.fail("Research must not open an unavailable MCP client")

    monkeypatch.setattr("co_scientist.mcp_client.get_mcp_client", unavailable)
    hypothesis = make_hypothesis(text="TGF-beta drives fibrosis")
    state = make_state(
        current_iteration=1,
        research_tier="extended",
        mcp_available=False,
        hypotheses=[hypothesis],
    )
    found = (
        await research_for_expansion(state)
        if consumer == "expansion"
        else await research_for_review(state, hypothesis)
    )
    assert found is None


async def test_an_expansion_cycle_explores_and_grounds_the_next_draft(
    tmp_path: Path,
    expansion_model: _ScriptedModel,
    expansion_client: FakeResearchClient,
) -> None:
    state = make_state(
        current_iteration=1,
        research_goal="reverse fibrosis",
        model_name="offline/test",
        run_id="run-1",
        mcp_available=True,
        research_tier="extended",
        tool_registry=research_registry(tmp_path),
        hypotheses=[make_hypothesis(text="TGF-beta drives it")],
    )

    explored = await research_for_expansion(state)

    assert explored is not None
    assert "Blockade reduced fibrosis in humans" in explored.section
    assert explored.articles
    assert explored.ledger["findings"]
    assert "TGF-beta drives it" in expansion_model.prompts[0]
    assert "Blockade reduced fibrosis in humans" in build_expansion_section(
        explored.applied_to(state)
    )


def test_explored_articles_are_merged_before_the_citation_namespace() -> None:
    existing = object()
    found = object()
    state = ExpansionResearch("s", [found], {}).applied_to(
        make_state(current_iteration=1, articles=[existing])
    )

    assert state["articles"] == [existing, found]


def _result() -> ResearchResult:
    call = SearchCall(
        question="What drives fibrosis?",
        query="fibrosis mechanism",
        source="pubmed",
        status=CallStatus.OK,
        hits=(
            SourceHit(
                locator="doc-a",
                title="First",
                snippet="about a",
                rank=0,
                score=0.9,
                metadata={"doi": "10.1/a"},
            ),
            SourceHit(
                locator="doc-b", title="Second", snippet="about b", rank=1
            ),
        ),
        admitted=("doc-a",),
        dropped=("doc-b",),
        duration_seconds=0.4,
    )
    finding = Finding(
        text="TGF-beta drives it",
        question="What drives fibrosis?",
        locator="doc-a",
        span="TGF-beta signalling drives fibrosis",
        call_id=call.id,
    )
    return ResearchResult(
        goal="reverse fibrosis",
        stances=("mechanism", "counter-evidence"),
        threads=(
            ThreadRecord(
                question=Question(
                    text="What drives fibrosis?", stance="mechanism"
                ),
                depth=1,
                status=ThreadStatus.OK,
                call_ids=(call.id,),
                finding_ids=(finding.id,),
                follow_ups=("what blocks it?",),
                summary="TGF-beta is the consensus driver.",
            ),
            ThreadRecord(
                question=Question(text="what blocks it?", stance="mechanism"),
                depth=2,
                status=ThreadStatus.DECLINED,
                note="breadth exhausted",
                retry_breadth=4,
            ),
        ),
        calls=(call,),
        findings=(finding,),
        stop_reason=StopReason.NO_FOLLOW_UPS,
        levels_run=2,
    )


def test_a_result_survives_the_trip_through_plain_data() -> None:
    original = _result()

    restored = result_from_dict(result_to_dict(original))

    assert restored == original


def test_ids_are_re_derived_rather_than_stored() -> None:
    original = _result()

    payload = result_to_dict(original)
    restored = result_from_dict(payload)

    assert "id" not in payload["calls"][0]
    assert "id" not in payload["findings"][0]
    assert restored.calls[0].id == original.calls[0].id
    assert restored.findings[0].call_id == original.calls[0].id


def test_a_payload_from_an_older_build_still_loads() -> None:
    payload: dict[str, Any] = {
        "goal": "reverse fibrosis",
        "calls": [
            {
                "question": "q",
                "query": "q terms",
                "source": "pubmed",
                "status": "ok",
                "something_new": 1,
            }
        ],
        "stop_reason": "invented_reason",
    }

    restored = result_from_dict(payload)

    assert restored.goal == "reverse fibrosis"
    assert restored.calls[0].hits == ()
    assert restored.stop_reason is StopReason.DEPTH_EXHAUSTED
    assert restored.threads == ()


_NETWORK = "pubmed"
_RESERVED = "reserved_source"


def _call(source: str, *locators: str) -> SearchCall:
    return SearchCall(
        question="what is known?",
        query="known",
        source=source,
        status=CallStatus.OK,
        hits=tuple(_hits(*locators)),
    )


def _budget(reserved: tuple[tuple[str, int], ...]) -> ResearchBudget:
    return ResearchBudget(
        hits_per_question=3,
        sources=(_NETWORK, _RESERVED),
        reserved_slots=reserved,
    )


@pytest.mark.parametrize(
    ("network", "reserved", "reservation", "expected"),
    [
        (("n1", "n2", "n3", "n4"), ("c1",), (), ["n1", "n2", "n3"]),
        (
            ("n1", "n2", "n3", "n4"),
            ("c1", "c2"),
            ((_RESERVED, 1),),
            ["c1", "n1", "n2"],
        ),
        (
            ("n1", "n2", "n3", "n4"),
            (),
            ((_RESERVED, 1),),
            ["n1", "n2", "n3"],
        ),
        (
            ("shared", "n1", "n2"),
            ("shared", "c1"),
            ((_RESERVED, 1),),
            ["c1", "shared", "n1"],
        ),
    ],
    ids=["no-reservation", "reserved-seat", "empty-source-not-padded", "dedup"],
)
def test_a_reservation_seats_its_source_ahead_of_the_network(
    network: tuple[str, ...],
    reserved: tuple[str, ...],
    reservation: tuple[tuple[str, int], ...],
    expected: list[str],
) -> None:
    calls = [_call(_NETWORK, *network), _call(_RESERVED, *reserved)]

    admitted, _ = admit_within_budget(calls, _budget(reservation))

    assert [hit.locator for hit in admitted] == expected


@pytest.mark.parametrize(
    ("budget", "message"),
    [
        (
            {
                "hits_per_question": 2,
                "sources": (_NETWORK, _RESERVED),
                "reserved_slots": ((_RESERVED, 2),),
            },
            "claim all",
        ),
        (
            {"sources": (_NETWORK,), "reserved_slots": (("nope", 1),)},
            "unsearched",
        ),
    ],
)
def test_an_impossible_reservation_is_refused(
    budget: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ResearchBudget(**budget)


def test_the_descent_carries_a_reservation_down() -> None:
    budget = ResearchBudget(
        depth=3,
        hits_per_question=3,
        sources=(_NETWORK, _RESERVED),
        reserved_slots=((_RESERVED, 1),),
    )

    second = budget.descend()

    assert second is not None
    assert second.reserved_slots == ((_RESERVED, 1),)

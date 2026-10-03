from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from co_scientist.agents.generation.expansion_research import (
    EXPANSION_EXTRA_DRAFT_ITERATIONS,
    EXPANSION_POOL_ITEM_CHARS,
    EXPANSION_POOL_SAMPLE_SIZE,
    ExpansionResearch,
    _expansion_goal,
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
    review_budget_for_tier,
)
from tests._research_fakes import (
    _PAPERS,
    FakeResearchClient,
    _hits,
    _ScriptedModel,
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


async def test_search_keeps_the_source_ordering_it_was_given(
    tmp_path: Path,
) -> None:
    retrieval = _retrieval(
        tmp_path, FakeResearchClient({"search_alpha": _HITS})
    )

    hits = await retrieval.search(query="fibrosis", source="alpha", limit=5)

    assert [hit.locator for hit in hits] == ["doc-a", "doc-b"]
    assert [hit.rank for hit in hits] == [0, 1]
    assert hits[0].title == "First"
    assert hits[1].metadata["doi"] == "10.1/b"
    assert hits[0].metadata["source"] == "alpha"


async def test_search_takes_no_more_hits_than_it_was_asked_for(
    tmp_path: Path,
) -> None:
    retrieval = _retrieval(
        tmp_path, FakeResearchClient({"search_alpha": _HITS})
    )

    hits = await retrieval.search(query="fibrosis", source="alpha", limit=1)

    assert [hit.locator for hit in hits] == ["doc-a"]


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


async def test_only_enabled_sources_are_offered_to_the_caller(
    tmp_path: Path,
) -> None:
    retrieval = _retrieval(tmp_path, FakeResearchClient({}))

    assert retrieval.sources == ("alpha",)


async def test_reading_a_hit_fetches_its_full_text(tmp_path: Path) -> None:
    client = FakeResearchClient(
        {"search_alpha": _HITS, "read_pdf": {"content": "the whole paper"}}
    )
    retrieval = _retrieval(tmp_path, client)
    await retrieval.search(query="fibrosis", source="alpha", limit=5)

    text = await retrieval.read(locator="doc-a")

    assert text == "the whole paper"
    assert client.calls[-1][1]["url"] == "u/a"


async def test_a_hit_with_no_url_reads_as_nothing_not_as_an_error(
    tmp_path: Path,
) -> None:
    client = FakeResearchClient(
        {"search_alpha": _HITS, "read_pdf": {"content": "x"}}
    )
    retrieval = _retrieval(tmp_path, client)
    await retrieval.search(query="fibrosis", source="alpha", limit=5)

    assert await retrieval.read(locator="doc-b") is None
    assert await retrieval.read(locator="never-seen") is None


async def test_a_failed_read_does_not_lose_the_document(
    tmp_path: Path,
) -> None:
    client = FakeResearchClient(
        {"search_alpha": _HITS, "read_pdf": RuntimeError("timeout")}
    )
    retrieval = _retrieval(tmp_path, client)
    await retrieval.search(query="fibrosis", source="alpha", limit=5)

    assert await retrieval.read(locator="doc-a") is None


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


def test_only_the_deep_tiers_buy_research() -> None:
    assert budget_for_tier("express", ["alpha"]) is None
    assert budget_for_tier("standard", ["alpha"]) is None
    assert budget_for_tier("unknown-tier", ["alpha"]) is None


def test_a_tier_states_its_thread_count_before_spending_anything() -> None:
    extended = budget_for_tier("extended", ["alpha"])
    ultra = budget_for_tier("ultra", ["alpha", "beta"])

    assert extended is not None and ultra is not None
    assert extended.max_threads() == 6
    assert ultra.max_threads() == 11
    assert ultra.sources == ("alpha", "beta")


def test_a_run_with_no_search_source_researches_nothing() -> None:
    assert budget_for_tier("ultra", []) is None


def test_a_run_that_names_no_tier_researches_nothing() -> None:
    assert _resolve_research_tier({}, True) == ""
    assert _resolve_research_tier({"research_tier": ""}, True) == ""


def test_research_is_refused_where_there_is_nothing_to_search() -> None:
    """Without MCP there is no reachable source; literature-node disable
    alone is not a refusal."""
    assert _resolve_research_tier({"research_tier": "ultra"}, False) == ""


def test_the_offline_backend_still_researches() -> None:
    """Ordinary schema-shaped research calls are supported by the
    deterministic offline backend."""
    assert _resolve_research_tier({"research_tier": "ultra"}, True) == "ultra"


@pytest.fixture
def expansion_model(monkeypatch: pytest.MonkeyPatch) -> _ScriptedModel:
    model = _ScriptedModel()
    monkeypatch.setattr("co_scientist.research_adapter.call_llm_json", model)
    return model


@pytest.fixture
def expansion_client(monkeypatch: pytest.MonkeyPatch) -> FakeResearchClient:
    fake = FakeResearchClient(
        {
            "search_alpha": _PAPERS,
            "read_pdf": {
                "content": "TGF-beta blockade reduced fibrosis in a"
                " human cohort."
            },
        }
    )

    async def get_client(**_: Any) -> MCPToolClient:
        return cast(MCPToolClient, fake)

    monkeypatch.setattr("co_scientist.mcp_client.get_mcp_client", get_client)
    return fake


def test_initial_generation_cycle_is_not_expansion() -> None:
    assert not is_research_expansion(make_state(current_iteration=0))
    assert not is_research_expansion(make_state())


def test_later_generate_cycles_are_expansion() -> None:
    assert is_research_expansion(make_state(current_iteration=1))
    assert is_research_expansion(make_state(current_iteration=3))


def test_expansion_section_absent_on_initial_cycle() -> None:
    assert build_expansion_section(make_state(current_iteration=0)) == ""


def test_expansion_section_switches_to_broad_retrieval() -> None:
    state = make_state(current_iteration=2)
    section = build_expansion_section(state)
    assert "Research Expansion Cycle" in section
    assert "DIVERSE" in section
    assert "before" in section.lower()


def test_expansion_section_names_the_explored_pool_bounded() -> None:
    long_text = "explored direction " + "x" * 500
    hypotheses = [make_hypothesis(text=f"hyp {i}") for i in range(20)]
    hypotheses.append(make_hypothesis(text=long_text))
    state = make_state(current_iteration=1, hypotheses=hypotheses)

    summaries = explored_hypothesis_summaries(state)
    assert len(summaries) == EXPANSION_POOL_SAMPLE_SIZE
    assert all(len(s) <= EXPANSION_POOL_ITEM_CHARS + 3 for s in summaries)

    section = build_expansion_section(state)
    assert "hyp 0" in section
    assert "hyp 15" not in section
    assert "do NOT re-derive" in section


def test_expansion_section_with_empty_pool_omits_coverage() -> None:
    state = make_state(current_iteration=1, hypotheses=[])
    section = build_expansion_section(state)
    assert "Research Expansion Cycle" in section
    assert "already explored" not in section


def test_draft_prompt_renders_expansion_section() -> None:
    section = build_expansion_section(make_state(current_iteration=1))
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="repurpose a kinase inhibitor",
            hypotheses_count=2,
            research_expansion_section=section,
        )
    )
    assert "Research Expansion Cycle" in prompt
    assert "{{MISSING" not in prompt


def test_draft_prompt_without_sections_is_unchanged() -> None:
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="repurpose a kinase inhibitor",
            hypotheses_count=2,
        )
    )
    assert "Research Expansion Cycle" not in prompt
    assert "Verified Incorrect" not in prompt
    assert "{{MISSING" not in prompt


def test_draft_prompt_renders_falsified_assumptions_section() -> None:
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="repurpose a kinase inhibitor",
            hypotheses_count=2,
            falsified_assumptions_section=(
                "## Assumptions Verified Incorrect (avoid or rework)\n"
                "- Does efflux matter? -- finding: no.\n"
            ),
        )
    )
    assert "Verified Incorrect" in prompt
    assert "Does efflux matter?" in prompt


def test_expansion_draft_budget_gets_extra_retrieval_rounds() -> None:
    base = _compute_draft_iteration_budget(3)
    expanded = _compute_draft_iteration_budget(3, is_expansion=True)
    assert base == get_draft_max_iterations(3)
    assert expanded == base + EXPANSION_EXTRA_DRAFT_ITERATIONS


async def test_the_initial_cycle_buys_no_exploration(tmp_path: Path) -> None:
    state = make_state(current_iteration=0, research_tier="extended")

    assert await research_for_expansion(state) is None


async def test_a_tier_that_funds_no_research_explores_nothing(
    tmp_path: Path,
) -> None:
    state = make_state(current_iteration=1, research_tier="standard")

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


def test_the_expansion_goal_names_the_explored_ground_to_avoid() -> None:
    state = make_state(
        current_iteration=1,
        research_goal="why does fibrosis progress?",
        hypotheses=[make_hypothesis(text="TGF-beta drives it")],
    )

    goal = _expansion_goal(state)

    assert goal.startswith("why does fibrosis progress?")
    assert "TGF-beta drives it" in goal
    assert "do NOT cover" in goal or "NOT cover" in goal


def test_the_expansion_goal_is_the_bare_goal_before_any_hypothesis() -> None:
    state = make_state(current_iteration=1, research_goal="why fibrosis?")

    assert _expansion_goal(state) == "why fibrosis?"


def test_findings_reach_the_generation_prompt() -> None:
    explored = ExpansionResearch(
        section="- collagen crosslinking is under-studied [PMID:1]\n",
        articles=[],
        ledger={},
    )
    state = explored.applied_to(make_state(current_iteration=1))

    section = build_expansion_section(state)

    assert "collagen crosslinking is under-studied [PMID:1]" in section


def test_the_prompt_carries_no_evidence_block_when_nothing_explored() -> None:
    section = build_expansion_section(make_state(current_iteration=1))

    assert "Research Expansion Cycle" in section
    assert "Ground new hypotheses in this material" not in section


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


def test_the_source_ranking_comes_back_intact() -> None:
    restored = result_from_dict(result_to_dict(_result()))

    hits = restored.calls[0].hits
    assert [hit.locator for hit in hits] == ["doc-a", "doc-b"]
    assert [hit.rank for hit in hits] == [0, 1]
    assert hits[0].score == 0.9
    assert hits[0].metadata["doi"] == "10.1/a"
    assert restored.calls[0].dropped == ("doc-b",)


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


def test_without_a_reservation_the_first_source_takes_everything() -> None:
    calls = [
        _call(_NETWORK, "n1", "n2", "n3", "n4"),
        _call(_RESERVED, "c1"),
    ]

    admitted, _ = admit_within_budget(calls, _budget(()))

    assert [hit.locator for hit in admitted] == ["n1", "n2", "n3"]


def test_a_reservation_seats_the_reserved_source_ahead_of_the_network() -> None:
    calls = [
        _call(_NETWORK, "n1", "n2", "n3", "n4"),
        _call(_RESERVED, "c1", "c2"),
    ]

    admitted, recorded = admit_within_budget(calls, _budget(((_RESERVED, 1),)))

    assert [hit.locator for hit in admitted] == ["c1", "n1", "n2"]
    assert recorded[1].admitted == ("c1",)
    assert recorded[1].dropped == ("c2",)


def test_a_reservation_is_never_padded_when_the_source_is_empty() -> None:
    calls = [
        _call(_NETWORK, "n1", "n2", "n3", "n4"),
        _call(_RESERVED),
    ]

    admitted, _ = admit_within_budget(calls, _budget(((_RESERVED, 1),)))

    assert [hit.locator for hit in admitted] == ["n1", "n2", "n3"]


def test_a_paper_both_sources_returned_is_seated_once() -> None:
    """Dedup before reservations and ranked filling prevents seating a shared
    paper twice."""
    calls = [
        _call(_NETWORK, "shared", "n1", "n2"),
        _call(_RESERVED, "shared", "c1"),
    ]

    admitted, _ = admit_within_budget(calls, _budget(((_RESERVED, 1),)))

    assert [hit.locator for hit in admitted] == ["c1", "shared", "n1"]


def test_a_reservation_cannot_claim_every_document() -> None:
    with pytest.raises(ValueError, match="claim all"):
        ResearchBudget(
            hits_per_question=2,
            sources=(_NETWORK, _RESERVED),
            reserved_slots=((_RESERVED, 2),),
        )


def test_a_reservation_for_an_unsearched_source_is_refused() -> None:
    with pytest.raises(ValueError, match="unsearched"):
        ResearchBudget(sources=(_NETWORK,), reserved_slots=(("nope", 1),))


@pytest.mark.parametrize("tier", ["extended", "ultra"])
@pytest.mark.parametrize(
    "resolve", [budget_for_tier, review_budget_for_tier], ids=["run", "review"]
)
def test_every_researching_budget_reserves_nothing_by_default(
    tier: str, resolve: object
) -> None:
    budget = resolve(tier, (_NETWORK, _RESERVED))  # type: ignore[operator]

    assert budget is not None
    assert budget.reserved_slots == ()


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

from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import reflection
from co_scientist.agents.reflection import review_evidence as ev
from co_scientist.agents.reflection.reflection import reflection_node
from co_scientist.agents.reflection.reflection_helpers import (
    _build_enrichment_items,
    _format_single_statement,
    extract_entity_names,
    fetch_indra_evidence,
    get_kg_tools_for_workflow,
)
from co_scientist.agents.reflection.review_evidence import ReviewResearch
from co_scientist.agents.reflection.review_gate import ReviewType
from co_scientist.config import ToolRegistry
from co_scientist.models import Article
from tests._llm_fake import mock_call_llm_json, stub_call_llm_json
from tests._mcp import WorkflowToolRegistry
from tests._state import make_hypothesis, make_state

_ARTICLES = "Article 1: observation A supports pathway X."


@pytest.mark.parametrize("pool", [[], [make_hypothesis(text="a hypothesis")]])
async def test_reflection_needs_hypotheses_and_literature_to_run(
    pool: list[Any],
) -> None:
    articles = _ARTICLES if not pool else None
    state = make_state(hypotheses=pool, articles_with_reasoning=articles)
    assert await reflection_node(state) == {}


async def test_hypotheses_get_reflection_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hyp_a = make_hypothesis(text="alpha pathway drives growth")
    hyp_b = make_hypothesis(text="beta pathway drives growth")
    state = make_state(
        hypotheses=[hyp_a, hyp_b], articles_with_reasoning=_ARTICLES
    )
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {
            "classification": "missing piece",
            "reasoning": "fills a gap",
        },
    )

    result = await reflection_node(state)

    returned = result["hypotheses"]
    expected_notes = "fills a gap\n\nClassification: missing piece"
    assert len(returned) == 2
    for hyp in returned:
        assert hyp.reflection_notes == expected_notes
        assert "indra_evidence" not in hyp.enrichments
    assert hyp_a.reflection_notes == expected_notes
    assert hyp_b.reflection_notes == expected_notes
    assert result["messages"][0]["metadata"]["phase"] == "reflection"


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


async def test_positive_observations_accumulate_on_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Strengths precede the classification suffix that downstream ranking
    parses."""
    hyp = make_hypothesis(text="alpha pathway drives growth")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {
            "classification": "missing piece",
            "reasoning": "fills a gap",
            "positive_observations": ["explains the resistance phenotype"],
        },
    )

    result = await reflection_node(state)

    returned = result["hypotheses"][0]
    notes = returned.reflection_notes or ""
    assert "fills a gap" in notes
    assert "explains the resistance phenotype" in notes
    assert notes.index("explains the resistance phenotype") < notes.index(
        "Classification: missing piece"
    )
    assert notes.endswith("Classification: missing piece")
    assert returned.enrichments["observation"]["positive_observations"] == [
        "explains the resistance phenotype"
    ]


async def test_blank_positive_observations_are_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hyp = make_hypothesis(text="alpha pathway drives growth")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {
            "classification": "neutral",
            "reasoning": "no signal",
            "positive_observations": ["", "   "],
        },
    )

    result = await reflection_node(state)

    returned = result["hypotheses"][0]
    assert returned.reflection_notes == "no signal\n\nClassification: neutral"
    assert "positive_observations" not in returned.enrichments["observation"]


def _validation_article() -> Article:
    return Article(
        title="Targeted validation",
        source_id="validation-1",
        abstract="The proposed mechanism survived direct testing.",
        used_in_analysis=True,
    )


async def test_full_and_simulation_run_for_every_viable_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = mock_call_llm_json(monkeypatch, cr, {"verdict": "sound"})
    viable = [make_hypothesis(text="a"), make_hypothesis(text="b")]
    for hypothesis in viable:
        hypothesis.review_disposition = "viable"
    rejected = make_hypothesis(text="rejected")
    rejected.review_disposition = "non_novel"

    result = await cr.comprehensive_reflection_node(
        make_state(hypotheses=[*viable, rejected], current_iteration=0)
    )

    assert fake.await_count == 5
    assert all("full" in h.enrichments for h in viable)
    assert all("simulation" in h.enrichments for h in viable)
    assert "full" not in rejected.enrichments
    assert "recurrent" in rejected.enrichments
    assert result["metrics"].llm_calls == 5


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


async def test_a_fatal_full_review_changes_the_disposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def fake_llm(**kwargs: object) -> dict[str, object]:
        prompt = str(kwargs.get("prompt", ""))
        if "simulation review" in prompt:
            return {"verdict": "holds"}
        return {"verdict": "rejected", "justification": "circular mechanism"}

    mock_call_llm_json(monkeypatch, cr, side_effect=fake_llm)
    hypothesis = make_hypothesis(text="idea")
    hypothesis.review_disposition = "viable"

    await cr.comprehensive_reflection_node(
        make_state(hypotheses=[hypothesis], current_iteration=0)
    )

    assert hypothesis.enrichments["full"]["verdict"] == "rejected"
    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


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


@pytest.mark.asyncio
async def test_full_review_executes_targeted_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Literature search ANDs terms; querying hypothesis prose would retrieve
    nothing."""
    call = mock_call_llm_json(monkeypatch, cr, {"verdict": "sound"})
    retrieve = AsyncMock(return_value=([_validation_article()], []))
    monkeypatch.setattr(
        ev,
        "call_llm_json",
        AsyncMock(return_value={"queries": ["mechanism X response Y"]}),
    )
    monkeypatch.setattr(ev, "_retrieve_probe_evidence", retrieve)
    hypothesis = make_hypothesis(text="Mechanism X controls response Y")
    state = make_state(
        hypotheses=[hypothesis],
        research_goal="Understand response Y",
        mcp_available=True,
    )

    _, result, _ = await cr._run_review(state, hypothesis, ReviewType.FULL)

    retrieve.assert_awaited_once_with(state, ["mechanism X response Y"])
    assert result is not None
    assert result["retrieval_queries"] == ["mechanism X response Y"]
    assert result["retrieved_articles"][0]["source_id"] == "validation-1"
    prompt = call.await_args_list[-1].kwargs["prompt"]
    assert "Targeted validation" in prompt
    assert "survived direct testing" in prompt


async def test_full_and_simulation_share_one_targeted_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both modes ask the same literature question; separate retrieval pays
    twice."""
    query_calls = 0
    retrievals = 0

    async def _queries(
        _state: object, _hypothesis: object
    ) -> dict[str, object]:
        nonlocal query_calls
        query_calls += 1
        # Yield to expose a second caller starting before the first retrieval
        # completes.
        await asyncio.sleep(0)
        return {"queries": ["targeted query"]}

    async def _retrieve(
        _state: object, _queries: list[str]
    ) -> tuple[list[Article], list[str]]:
        nonlocal retrievals
        retrievals += 1
        await asyncio.sleep(0)
        return [_validation_article()], []

    monkeypatch.setattr(ev, "_call_hypothesis_query_llm", _queries)
    monkeypatch.setattr(ev, "_retrieve_probe_evidence", _retrieve)
    monkeypatch.setattr(
        cr,
        "call_llm_json",
        AsyncMock(return_value={"assessment": "ok", "score": 4}),
    )

    hypothesis = make_hypothesis(text="a mechanism worth reviewing")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    reviewed, _ = await cr._review_hypothesis(state, hypothesis)

    assert reviewed == 2
    assert query_calls == 1
    assert retrievals == 1
    # Persist shared evidence independently of the in-process flight cache.
    for mode in (ReviewType.FULL, ReviewType.SIMULATION):
        stored = hypothesis.enrichments[mode.value]["retrieved_articles"]
        assert [item["source_id"] for item in stored] == ["validation-1"]


async def test_rewritten_hypothesis_does_not_reuse_stale_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hypothesis = make_hypothesis(text="original claim")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    before = ev._evidence_key(state, hypothesis)
    hypothesis.text = "a materially different claim"

    assert ev._evidence_key(state, hypothesis) != before


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


async def test_research_adds_to_the_probe_round_rather_than_replacing_it(
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
    _stub_review_research(monkeypatch)
    hypothesis = make_hypothesis(text="a mechanism worth reviewing")
    state = make_state(hypotheses=[hypothesis], mcp_available=True)

    reviewed, ledgers = await cr._review_hypothesis(state, hypothesis)

    assert reviewed == 2
    stored = hypothesis.enrichments["full"]["retrieved_articles"]
    assert [item["source_id"] for item in stored] == [
        "validation-1",
        "researched-1",
    ]
    assert len(ledgers) == 1


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


async def test_fetch_indra_evidence_none_registry_short_circuits() -> None:
    result = await fetch_indra_evidence(
        "KRAS drives tumor growth", tool_registry=None
    )
    assert result == {"prompt_text": "", "enrichment_items": []}


def test_build_enrichment_items_injects_queried_entities_on_first() -> None:
    items = _build_enrichment_items(
        [
            {
                "type": "Activation",
                "belief": 0.9,
                "evidence": [1, 2],
                "subj": {"name": "KRAS"},
                "obj": {"name": "BRAF"},
            },
            {
                "type": "Complex",
                "belief": 0.8,
                "evidence": [],
                "members": [{"name": "A"}, {"name": "B"}],
            },
        ],
        ["KRAS", "TREM2"],
    )
    assert len(items) == 2
    assert items[0]["relationship"] == "KRAS → BRAF"
    assert items[0]["belief"] == "90%"
    assert items[0]["evidence_count"] == "2"
    assert items[0]["queried_entities"] == "KRAS, TREM2"
    assert items[1]["relationship"] == "Complex(A, B)"
    assert "queried_entities" not in items[1]


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


def test_statements_become_readable_enrichment_items() -> None:
    items = _build_enrichment_items(
        [
            {
                "type": "Activation",
                "belief": 0.9,
                "evidence": [1, 2],
                "subj": {"name": "KRAS"},
                "obj": {"name": "BRAF"},
            },
            {
                "type": "Complex",
                "belief": 0.8,
                "evidence": [],
                "members": [{"name": "A"}, {"name": "B"}],
            },
            {"type": "Unknown"},
        ],
        ["KRAS", "TREM2"],
    )

    assert [item["relationship"] for item in items] == [
        "KRAS → BRAF",
        "Complex(A, B)",
    ]
    assert (items[0]["belief"], items[0]["evidence_count"]) == ("90%", "2")
    assert items[0]["queried_entities"] == "KRAS, TREM2"
    assert "queried_entities" not in items[1]
    assert _format_single_statement({"type": "Unknown"}) == ""

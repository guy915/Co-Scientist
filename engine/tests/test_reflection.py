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
    _ev_count_str,
    _format_single_statement,
    _normalize_entity,
    _parse_tool_result,
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


async def test_empty_hypotheses_returns_empty() -> None:
    state = make_state(hypotheses=[], articles_with_reasoning=_ARTICLES)
    result = await reflection_node(state)
    assert result == {}


async def test_missing_articles_skips_node() -> None:
    state = make_state(hypotheses=[make_hypothesis(text="a hypothesis")])
    result = await reflection_node(state)
    assert result == {}


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


async def test_no_positive_observations_keeps_notes_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hyp = make_hypothesis(text="alpha pathway drives growth")
    state = make_state(hypotheses=[hyp], articles_with_reasoning=_ARTICLES)
    stub_call_llm_json(
        monkeypatch,
        reflection,
        {"classification": "missing piece", "reasoning": "fills a gap"},
    )

    result = await reflection_node(state)

    returned = result["hypotheses"][0]
    assert returned.reflection_notes == (
        "fills a gap\n\nClassification: missing piece"
    )
    assert "positive_observations" not in returned.enrichments["observation"]


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


def test_observation_schema_bounds_positive_observations() -> None:
    from co_scientist.schemas.review import (
        REFLECTION_MAX_POSITIVE_OBSERVATIONS,
        REFLECTION_SCHEMA,
    )

    properties = REFLECTION_SCHEMA["schema"]["properties"]
    field = properties["positive_observations"]
    assert field["type"] == "array"
    assert field["items"] == {"type": "string"}
    assert field["maxItems"] == REFLECTION_MAX_POSITIVE_OBSERVATIONS
    assert (
        "positive_observations" not in REFLECTION_SCHEMA["schema"]["required"]
    )


def test_observation_prompt_asks_for_positive_observations() -> None:
    from co_scientist.prompts import get_reflection_prompt

    prompt, _ = get_reflection_prompt(
        articles_with_reasoning="lit", hypothesis_text="H"
    )
    assert "Positive observations" in prompt


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


async def test_evolved_hypothesis_receives_missing_observation_review(
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

    observation.assert_awaited_once()
    assert (
        hypothesis.enrichments["observation"]["classification"]
        == "missing_piece"
    )
    assert "explains x" in (hypothesis.reflection_notes or "")


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


@pytest.mark.asyncio
async def test_query_generation_is_skipped_without_a_search_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = mock_call_llm_json(monkeypatch, cr, {"verdict": "sound"})
    hypothesis = make_hypothesis(text="Mechanism X controls response Y")
    state = make_state(
        hypotheses=[hypothesis],
        research_goal="Understand response Y",
        mcp_available=False,
    )

    _, result, _ = await cr._run_review(state, hypothesis, ReviewType.FULL)

    assert result is not None
    assert result["retrieval_queries"] == []
    assert call.await_count == 1


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


def test_extract_entity_names_basic() -> None:
    result = extract_entity_names("IL-6 activates TREM2 in microglia")
    assert result == ["IL6", "TREM2"]


def test_extract_entity_names_requires_all_caps() -> None:
    assert extract_entity_names("Kras drives growth") == []


def test_extract_entity_names_no_entities_returns_empty() -> None:
    assert extract_entity_names("the quick brown fox jumps") == []


def test_extract_entity_names_filters_stopwords() -> None:
    assert extract_entity_names("DNA and RNA bind") == []


def test_extract_entity_names_skips_mutation_notation() -> None:
    assert extract_entity_names("KRAS G12C variant") == ["KRAS"]


def test_extract_entity_names_digit_skip_precedes_alias() -> None:
    assert extract_entity_names("P53 pathway") == []


def test_extract_entity_names_applies_alias_map() -> None:
    assert extract_entity_names("RAGE signaling") == ["AGER"]


def test_extract_entity_names_two_letter_only_via_hyphen() -> None:
    assert extract_entity_names("IL-6 and IL together") == ["IL6"]


def test_extract_entity_names_deduplicates() -> None:
    assert extract_entity_names("YKL-40 and YKL-40 again") == ["CHI3L1"]


def test_extract_entity_names_respects_max_entities_cap() -> None:
    text = "KRAS TREM2 APOE TP53 BRAF"
    assert extract_entity_names(text, max_entities=2) == ["KRAS", "TREM2"]
    assert len(extract_entity_names(text, max_entities=4)) == 4


def test_normalize_entity_strips_hyphen() -> None:
    assert _normalize_entity("IL-6") == "IL6"


def test_normalize_entity_applies_alias() -> None:
    assert _normalize_entity("RAGE") == "AGER"


def test_get_kg_tools_none_registry_returns_empty() -> None:
    assert get_kg_tools_for_workflow(None, "reflection") == []


def test_get_kg_tools_no_tool_ids_returns_empty() -> None:
    registry = _fake(tool_ids=[], mcp_names=["unused"])
    assert get_kg_tools_for_workflow(registry, "reflection") == []


def test_get_kg_tools_returns_mcp_names() -> None:
    registry = _fake(
        tool_ids=["indra_a", "indra_b"],
        mcp_names=["get_relations", "get_complexes"],
    )
    assert get_kg_tools_for_workflow(registry, "reflection") == [
        "get_relations",
        "get_complexes",
    ]


def test_get_kg_tools_swallows_exception() -> None:
    registry = _fake(tool_ids=["x"], mcp_names=["y"], raise_on_workflow=True)
    assert get_kg_tools_for_workflow(registry, "reflection") == []


async def test_fetch_indra_evidence_none_registry_short_circuits() -> None:
    result = await fetch_indra_evidence(
        "KRAS drives tumor growth", tool_registry=None
    )
    assert result == {"prompt_text": "", "enrichment_items": []}


def test_parse_tool_result_valid_json_string() -> None:
    assert _parse_tool_result('{"statements": [1, 2]}') == {
        "statements": [1, 2]
    }


def test_parse_tool_result_invalid_json_string() -> None:
    assert _parse_tool_result("not json") == {}


def test_parse_tool_result_dict_passthrough() -> None:
    payload: dict[str, Any] = {"statements": []}
    assert _parse_tool_result(payload) == payload


def test_parse_tool_result_other_type_returns_empty() -> None:
    assert _parse_tool_result(42) == {}


def test_ev_count_str_below_limit() -> None:
    assert _ev_count_str(24) == "24"


def test_ev_count_str_at_limit_marks_truncation() -> None:
    assert _ev_count_str(25) == "25+"


def test_format_single_statement_subject_object() -> None:
    line = _format_single_statement(
        {
            "type": "Activation",
            "belief": 0.9,
            "evidence": [1, 2],
            "subj": {"name": "KRAS"},
            "obj": {"name": "BRAF"},
        }
    )
    assert line == "- KRAS --[Activation]--> BRAF (belief: 0.90, 2 papers)"


def test_format_single_statement_complex_members() -> None:
    line = _format_single_statement(
        {
            "type": "Complex",
            "belief": 0.8,
            "evidence": [],
            "members": [{"name": "A"}, {"name": "B"}],
        }
    )
    assert line == "- Complex(A, B) [Complex] (belief: 0.80, 0 papers)"


def test_format_single_statement_empty_when_no_agents() -> None:
    assert _format_single_statement({"type": "Unknown"}) == ""


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


def test_build_enrichment_items_empty_input_returns_empty() -> None:
    assert _build_enrichment_items([], ["KRAS"]) == []
    assert _build_enrichment_items([{"type": "X"}], ["KRAS"]) == []


def test_get_kg_tools_skips_tools_that_are_not_knowledge_graphs() -> None:
    """Workflow lists mix tool kinds; INDRA entity arguments are invalid for
    literature tools."""
    registry = _fake(
        tool_ids=["pubmed_fulltext"],
        mcp_names=["pubmed_search_with_fulltext"],
        source_type="academic",
    )
    assert get_kg_tools_for_workflow(registry, "reflection") == []

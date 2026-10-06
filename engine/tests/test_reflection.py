from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import reflection
from co_scientist.agents.reflection import review_evidence as ev
from co_scientist.agents.reflection.reflection import reflection_node
from co_scientist.agents.reflection.reflection_helpers import (
    extract_entity_names,
    get_kg_tools_for_workflow,
)
from co_scientist.agents.reflection.review_evidence import ReviewResearch
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

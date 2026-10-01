"""The drain closing the loop on retrieval provenance.

The store has held a ``retrieval_calls`` table and a
``evidence.retrieval_call_id`` column since the schema change that made
room for them, and until a run actually wrote both the column stayed
NULL. These tests pin the end of that path: a run whose literature review
went back for its open questions leaves searches on record, and every
piece of evidence it found names the search that found it.

The final states here are synthetic, in the shape the engine's literature
review and its deep reviews produce -- a ``research_ledgers`` list, one
entry per research request, and articles stamped with the call that
surfaced them.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review.collection import (
    _CollectionResult,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _ReviewSynthesis,
)
from co_scientist.agents.generation.literature_review.queries import (
    QueryPhaseResult,
)
from co_scientist.agents.generation.literature_review.research_phase import (
    ResearchOutcome,
)
from co_scientist.cache import NodeCache
from co_scientist.cache import nodes as cache_nodes
from co_scientist.models import Article
from co_scientist.research import (
    CallStatus,
    Finding,
    Question,
    ResearchResult,
    SearchCall,
    SourceHit,
    StopReason,
    ThreadRecord,
    ThreadStatus,
    result_to_dict,
)
from co_scientist.state import WorkflowState

from app import store
from tests._drain_helpers import (
    _build_report,
    _engine_hypothesis,
    _persist_and_finalize,
)

_CALL = SearchCall(
    question="What blocks TGF-beta signalling in humans?",
    query="TGF-beta blockade human fibrosis",
    source="pubmed",
    status=CallStatus.OK,
    hits=(
        SourceHit(
            locator="12345678",
            title="A researched paper",
            snippet="TGF-beta blockade reduced fibrosis.",
            rank=0,
            score=0.8,
        ),
        SourceHit(locator="99999999", title="Also seen", snippet="", rank=1),
    ),
    admitted=("12345678",),
    dropped=("99999999",),
    duration_seconds=0.6,
)


def _ledger() -> dict[str, Any]:
    """One research request, as the engine carries it out on the state."""
    finding = Finding(
        text="TGF-beta blockade reduced fibrosis in a human cohort",
        question=_CALL.question,
        locator="12345678",
        span="TGF-beta blockade reduced fibrosis.",
        call_id=_CALL.id,
    )
    ledger: dict[str, Any] = result_to_dict(
        ResearchResult(
            goal="reverse fibrosis",
            stances=(),
            threads=(
                ThreadRecord(
                    question=Question(text=_CALL.question, stance="seed"),
                    depth=1,
                    status=ThreadStatus.OK,
                    call_ids=(_CALL.id,),
                    finding_ids=(finding.id,),
                    summary="Human evidence exists but is thin.",
                ),
            ),
            calls=(_CALL,),
            findings=(finding,),
            stop_reason=StopReason.NO_FOLLOW_UPS,
            levels_run=1,
        )
    )
    return ledger


def _final_state(*, researched: bool) -> dict[str, Any]:
    """A drained run, with or without a research phase behind it."""
    article: dict[str, Any] = {
        "title": "A researched paper",
        "source": "pubmed",
        "source_id": "12345678",
        "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "abstract": "TGF-beta blockade reduced fibrosis.",
    }
    state: dict[str, Any] = {
        "hypotheses": [],
        "articles": [article],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }
    if researched:
        article["retrieval_call_id"] = _CALL.id
        state["research_ledgers"] = [_ledger()]
    return state


def test_evidence_resolves_to_the_search_that_found_it(
    isolated_db: str,
) -> None:
    """The join the whole provenance change exists to make possible.

    Both halves have to land in the same drain: the search on record,
    and the evidence row naming it. Either alone is unusable -- a call
    nothing points at, or an id pointing at nothing.
    """
    run = store.create_run("provenance goal", "extended", "engine", {})

    _persist_and_finalize(run, _final_state(researched=True), isolated_db)

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    calls = store.list_retrieval_calls(run.id, db_path=isolated_db)
    assert len(evidence) == 1
    assert len(calls) == 1
    by_id = {call["id"]: call for call in calls}
    found_by = by_id[evidence[0]["retrieval_call_id"]]
    assert found_by["query"] == "TGF-beta blockade human fibrosis"
    assert found_by["question"] == _CALL.question
    assert found_by["source"] == "pubmed"


def test_cached_literature_review_keeps_provenance_through_the_report(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A cache hit preserves searches and article links without another search.

    The engine cache and app drain/report are joined here so a cache payload
    missing its ledger cannot silently publish evidence with no data source.
    """
    from co_scientist.agents.generation.literature_review import (
        literature_review_node,
    )

    cache = NodeCache(str(tmp_path), enabled=True, ttl_seconds=None)
    monkeypatch.setattr(cache_nodes, "campaign_free_mode", lambda: False)
    monkeypatch.setattr(cache_nodes, "current_api_key", lambda: None)
    monkeypatch.setattr(lr, "get_node_cache", lambda: cache)
    collect = AsyncMock(
        return_value=_CollectionResult(
            all_paper_metadata={
                "ordinary-1": {
                    "title": "Ordinary search paper",
                    "abstract": "A normal Phase 2 result.",
                }
            },
            paper_source_map={},
            search_errors=[],
            background_context="",
            context_enrichment_sources=[],
        )
    )
    monkeypatch.setattr(lr, "check_mcp_available", AsyncMock(return_value=True))
    monkeypatch.setattr(lr, "get_mcp_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        lr,
        "_phase1_generate_queries",
        AsyncMock(
            return_value=QueryPhaseResult(
                queries=["TGF-beta blockade"], llm_calls=0
            )
        ),
    )
    monkeypatch.setattr(lr, "_collect_and_enrich_papers", collect)
    monkeypatch.setattr(
        lr,
        "_analyze_and_synthesize",
        AsyncMock(return_value=_ReviewSynthesis("SYNTHESIZED REVIEW", 0, [])),
    )
    monkeypatch.setattr(
        lr,
        "run_research_phase",
        AsyncMock(
            return_value=ResearchOutcome(
                ledger=_ledger(),
                records={
                    "12345678": {
                        "title": "A researched paper",
                        "abstract": "TGF-beta blockade reduced fibrosis.",
                        "retrieval_call_id": _CALL.id,
                    }
                },
                section=(
                    "\n\n## Research\nA human cohort supports the finding."
                ),
            )
        ),
    )

    state = cast(
        WorkflowState,
        {
            "research_goal": "reverse fibrosis",
            "model_name": "test-model",
            "research_tier": "extended",
        },
    )
    cache.set(
        "literature_review",
        {
            "articles": [
                Article(
                    title="Legacy researched paper",
                    retrieval_call_id=_CALL.id,
                )
            ],
            "articles_with_reasoning": "LEGACY CACHE",
        },
        **lr._literature_cache_params(state, lr._get_search_config(state)),
    )
    asyncio.run(literature_review_node(state))
    cached = asyncio.run(literature_review_node(state))
    assert collect.await_count == 1

    final_state = {
        "hypotheses": [
            _engine_hypothesis("h1", "TGF-beta blockade reduces fibrosis.")
        ],
        "articles": [article.to_dict() for article in cached["articles"]],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
        "research_ledgers": cached.get("research_ledgers", []),
    }
    run = store.create_run("provenance goal", "extended", "engine", {})
    _persist_and_finalize(run, final_state, isolated_db)

    calls = store.list_retrieval_calls(run.id, db_path=isolated_db)
    evidence = store.list_evidence(run.id, db_path=isolated_db)
    by_title = {row["title"]: row for row in evidence}
    assert len(calls) == 1
    assert by_title["A researched paper"]["retrieval_call_id"] == _CALL.id
    assert by_title["Ordinary search paper"]["retrieval_call_id"] is None
    _, markdown = asyncio.run(_build_report(run, isolated_db))
    assert "## Data sources" in markdown
    assert _CALL.question in markdown


def test_what_was_seen_and_not_read_stays_on_record(
    isolated_db: str,
) -> None:
    """A coverage report cannot tell "unseen" from "seen and skipped"."""
    run = store.create_run("coverage goal", "extended", "engine", {})

    _persist_and_finalize(run, _final_state(researched=True), isolated_db)

    call = store.list_retrieval_calls(run.id, db_path=isolated_db)[0]
    assert [hit["locator"] for hit in call["hits"]] == ["12345678", "99999999"]
    assert call["admitted"] == ["12345678"]
    assert call["dropped"] == ["99999999"]
    assert call["depth"] == 1


def test_a_run_that_did_no_research_writes_no_searches(
    isolated_db: str,
) -> None:
    """Express and standard runs do not buy the phase, and that is fine."""
    run = store.create_run("shallow goal", "standard", "engine", {})

    _persist_and_finalize(run, _final_state(researched=False), isolated_db)

    assert store.list_retrieval_calls(run.id, db_path=isolated_db) == []
    evidence = store.list_evidence(run.id, db_path=isolated_db)
    assert evidence[0]["retrieval_call_id"] is None


def test_the_run_tier_reaches_the_engine_verbatim(isolated_db: str) -> None:
    """Which tiers research is the engine's list, and only its list.

    The app passes the tier rather than a yes/no, so the two sides cannot
    drift into disagreeing about which runs buy the phase. A legacy tier
    name is normalized on the way, since the engine matches on the
    current vocabulary.
    """
    from app.engine_adapter import build_engine_opts

    run = store.create_run("tier goal", "ultra", "engine", {})

    opts = build_engine_opts({"tier": "advanced"}, run.id, isolated_db)

    assert opts["research_tier"] == "ultra"


_REVIEW_CALL = SearchCall(
    question="Is the receptor expressed in humans?",
    query="TGF-beta receptor human expression",
    source="pubmed",
    status=CallStatus.OK,
    hits=(
        SourceHit(
            locator="55555555",
            title="Expression atlas",
            snippet="The receptor is expressed in human lung.",
            rank=0,
        ),
    ),
    admitted=("55555555",),
)


def _review_ledger() -> dict[str, Any]:
    """A second research request, from one hypothesis's own review."""
    ledger: dict[str, Any] = result_to_dict(
        ResearchResult(
            goal="reverse fibrosis",
            stances=(),
            threads=(
                ThreadRecord(
                    question=Question(
                        text=_REVIEW_CALL.question, stance="seed"
                    ),
                    depth=1,
                    status=ThreadStatus.OK,
                    call_ids=(_REVIEW_CALL.id,),
                ),
            ),
            calls=(_REVIEW_CALL,),
            findings=(),
            stop_reason=StopReason.NO_FOLLOW_UPS,
            levels_run=1,
        )
    )
    return ledger


def test_every_researcher_in_a_run_leaves_its_searches_on_record(
    isolated_db: str,
) -> None:
    """Research has two owners, and the state holds one ledger each.

    Under a single-ledger state the second writer replaced the first,
    so whichever researched last was the only one on record -- and the
    loss is invisible, because the surviving ledger looks complete.
    """
    run = store.create_run("two researchers", "ultra", "engine", {})
    state = _final_state(researched=True)
    state["research_ledgers"].append(_review_ledger())

    _persist_and_finalize(run, state, isolated_db)

    calls = store.list_retrieval_calls(run.id, db_path=isolated_db)
    assert {call["query"] for call in calls} == {
        "TGF-beta blockade human fibrosis",
        "TGF-beta receptor human expression",
    }


def test_the_same_search_from_two_researchers_is_one_row(
    isolated_db: str,
) -> None:
    """A call's id is its content, so the store deduplicates for free."""
    run = store.create_run("same search twice", "ultra", "engine", {})
    state = _final_state(researched=True)
    state["research_ledgers"].append(_ledger())

    _persist_and_finalize(run, state, isolated_db)

    assert len(store.list_retrieval_calls(run.id, db_path=isolated_db)) == 1


def test_a_reviews_own_paper_resolves_to_the_reviews_own_search(
    isolated_db: str,
) -> None:
    """The reflection half of the path, end to end.

    Its ledger arrives through a different route from the literature
    review's -- the item result, then the fan-out aggregate -- so the
    join it makes possible is worth pinning on its own rather than
    inferred from the review-less case.
    """
    run = store.create_run("review provenance", "ultra", "engine", {})
    state = _final_state(researched=True)
    state["research_ledgers"].append(_review_ledger())
    state["articles"].append(
        {
            "title": "Expression atlas",
            "source": "pubmed",
            "source_id": "55555555",
            "url": "https://pubmed.ncbi.nlm.nih.gov/55555555/",
            "abstract": "The receptor is expressed in human lung.",
            "retrieval_call_id": _REVIEW_CALL.id,
        }
    )

    _persist_and_finalize(run, state, isolated_db)

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    by_title = {row["title"]: row for row in evidence}
    calls = {
        call["id"]: call
        for call in store.list_retrieval_calls(run.id, db_path=isolated_db)
    }
    found_by = calls[by_title["Expression atlas"]["retrieval_call_id"]]
    assert found_by["question"] == "Is the receptor expressed in humans?"
    assert found_by["query"] == "TGF-beta receptor human expression"

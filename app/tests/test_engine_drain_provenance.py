from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import co_scientist.cache as cache_nodes
import pytest
from co_scientist import models as engine_models
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review.orchestration import (
    _CollectionResult,
    _ReviewSynthesis,
)
from co_scientist.agents.generation.literature_review.queries import (
    QueryPhaseResult,
)
from co_scientist.agents.generation.literature_review.research_phase import (
    ResearchOutcome,
)
from co_scientist.cache import NodeCache
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
from app.engine_tasks import inputs as engine_tasks_inputs
from app.report import gates as report_gates
from tests._drain_helpers import (
    _build_report,
    _engine_hypothesis,
    _final_state_with_features,
    _final_state_with_lineage,
    _persist,
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


def _provenance_final_state(*, researched: bool) -> dict[str, Any]:
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
    # Search ledger and evidence search link must persist together; either half
    # alone loses usable provenance.
    run = store.create_run("provenance goal", "extended", "engine", {})

    _persist_and_finalize(
        run, _provenance_final_state(researched=True), isolated_db
    )

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
    # Cache hits must preserve retrieval ledgers and article links without
    # making another search.
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
        **lr._literature_cache_params(state, lr.search_config_for(state)),
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
    run = store.create_run("coverage goal", "extended", "engine", {})

    _persist_and_finalize(
        run, _provenance_final_state(researched=True), isolated_db
    )

    call = store.list_retrieval_calls(run.id, db_path=isolated_db)[0]
    assert [hit["locator"] for hit in call["hits"]] == ["12345678", "99999999"]
    assert call["admitted"] == ["12345678"]
    assert call["dropped"] == ["99999999"]
    assert call["depth"] == 1


def test_a_run_that_did_no_research_writes_no_searches(
    isolated_db: str,
) -> None:
    run = store.create_run("shallow goal", "standard", "engine", {})

    _persist_and_finalize(
        run, _provenance_final_state(researched=False), isolated_db
    )

    assert store.list_retrieval_calls(run.id, db_path=isolated_db) == []
    evidence = store.list_evidence(run.id, db_path=isolated_db)
    assert evidence[0]["retrieval_call_id"] is None


def test_the_run_tier_reaches_the_engine_verbatim(isolated_db: str) -> None:
    # Pass normalized tiers rather than copied phase-enable decisions so app and
    # engine cannot drift.
    from app.engine_adapter.opts import build_engine_opts

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
    # Literature and reflection own separate ledgers; one shared writer silently
    # replaces earlier provenance.
    run = store.create_run("two researchers", "ultra", "engine", {})
    state = _provenance_final_state(researched=True)
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
    run = store.create_run("same search twice", "ultra", "engine", {})
    state = _provenance_final_state(researched=True)
    state["research_ledgers"].append(_ledger())

    _persist_and_finalize(run, state, isolated_db)

    assert len(store.list_retrieval_calls(run.id, db_path=isolated_db)) == 1


def test_a_reviews_own_paper_resolves_to_the_reviews_own_search(
    isolated_db: str,
) -> None:
    # Reflection provenance travels through item result and aggregate, unlike
    # literature-review ledger inputs.
    run = store.create_run("review provenance", "ultra", "engine", {})
    state = _provenance_final_state(researched=True)
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


# No-source degradation is invisible from otherwise complete ideas and
# tournaments; reports must disclose it.


def _degradation_final_state(
    degradation: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        **_final_state_with_features(),
        "retrieval_degradation": degradation,
    }


def test_the_report_carries_what_the_run_could_not_search(
    isolated_db: str,
) -> None:
    run = store.create_run("degraded goal", "extended", "engine", {})

    _persist_and_finalize(
        run,
        _degradation_final_state(
            {
                "reason": "mcp_unreachable",
                "lost": ["literature_review", "deep_research"],
                "floor": "none",
            }
        ),
        isolated_db,
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    degradation = report["payload"]["retrieval_degradation"]
    assert degradation["reason"] == "mcp_unreachable"
    assert degradation["floor"] == "none"
    assert "literature_review" in degradation["lost"]


def test_a_healthy_run_reports_no_degradation(isolated_db: str) -> None:
    run = store.create_run("healthy goal", "extended", "engine", {})

    _persist_and_finalize(run, _degradation_final_state(None), isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["retrieval_degradation"] is None


def _seed_gate_split(run: Any, db_path: str) -> tuple[str, str, str]:
    supported_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Supported",
            statement="Kinase X inhibition drives AML apoptosis.",
        ),
        db_path=db_path,
    )
    unsupported_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Unsupported",
            statement="A novel latent mechanism without any evidence yet.",
        ),
        db_path=db_path,
    )
    contradicted_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Contradicted",
            statement="Drug Y single-handedly cures the disease.",
        ),
        db_path=db_path,
    )
    _add_gate_split_edges(run, supported_id, contradicted_id, db_path)
    return supported_id, unsupported_id, contradicted_id


def _add_gate_split_edges(
    run: Any, supported_id: str, contradicted_id: str, db_path: str
) -> None:
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=supported_id,
            claim="Kinase X inhibition drives AML apoptosis.",
            label="supports",
            supporting=["A supporting source span."],
            contradicting=[],
            assessor="fixture",
        ),
        db_path=db_path,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=contradicted_id,
            claim="Drug Y single-handedly cures the disease.",
            label="contradicts",
            supporting=[],
            contradicting=["A source span refuting the claim."],
            assessor="fixture",
        ),
        db_path=db_path,
    )


def test_rank_and_publish_splits_contradicted_from_unverified(
    isolated_db: str,
) -> None:
    run = store.create_run("gate split", "standard", "engine", {})
    supported_id, unsupported_id, contradicted_id = _seed_gate_split(
        run, isolated_db
    )

    contradicted = report_gates.contradicted_hypothesis_ids(run.id, isolated_db)
    unverified = report_gates.unverified_hypothesis_ids(run.id, isolated_db)
    assert contradicted == {contradicted_id}
    assert unverified == {unsupported_id, contradicted_id}

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    kept_ids = {
        h["id"]
        for h in report_gates.exclude_unsafe_hypotheses(
            run.id, hyps, isolated_db
        )
    }
    assert kept_ids == {supported_id, unsupported_id}

    _assert_demo_run_badges_nothing(isolated_db)


def _assert_demo_run_badges_nothing(db_path: str) -> None:
    demo = store.create_run("demo", "standard", "mock", {})
    store.add_hypothesis(
        store.NewHypothesis(
            run_id=demo.id, title="Demo", statement="Demo idea."
        ),
        db_path=db_path,
    )
    assert report_gates.unverified_hypothesis_ids(demo.id, db_path) == set()


def test_partial_edge_clears_the_unverified_badge(isolated_db: str) -> None:
    # Partial support is relevant and consistent, so it clears the Unverified
    # badge.
    run = store.create_run("partial badge", "standard", "engine", {})
    partial_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Partially supported",
            statement="Kinase X modulation influences AML growth.",
        ),
        db_path=isolated_db,
    )
    insufficient_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Insufficient",
            statement="An entirely unevidenced conjecture.",
        ),
        db_path=isolated_db,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=partial_id,
            claim="Kinase X modulation influences AML growth.",
            label="partial",
            supporting=["A near-miss source span."],
            contradicting=[],
            assessor="fixture",
        ),
        db_path=isolated_db,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=insufficient_id,
            claim="An entirely unevidenced conjecture.",
            label="insufficient",
            supporting=[],
            contradicting=[],
            assessor="fixture",
        ),
        db_path=isolated_db,
    )

    unverified = report_gates.unverified_hypothesis_ids(run.id, isolated_db)
    assert unverified == {insufficient_id}


def test_gate_reports_exclusions_once_and_at_info(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    # Individual exclusions are expected narrative; warn when the gate leaves
    # nothing to synthesize.
    run = store.create_run("gate logging", "standard", "engine", {})
    _, _, contradicted_id = _seed_gate_split(run, isolated_db)
    hyps = store.list_hypotheses(run.id, db_path=isolated_db)

    with caplog.at_level(logging.INFO, logger="app.report.gates"):
        report_gates.exclude_unsafe_hypotheses(run.id, hyps, isolated_db)

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(contradicted_id in r.getMessage() for r in caplog.records)
    assert any(
        "excluded 1 of 3" in r.getMessage().lower() for r in caplog.records
    )


def test_gate_warns_when_it_excludes_everything(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    run = store.create_run("gate empty", "standard", "engine", {})
    store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Unsafe",
            statement="Weaponize the pathogen to enhance transmissibility.",
        ),
        db_path=isolated_db,
    )
    hyps = store.list_hypotheses(run.id, db_path=isolated_db)

    with caplog.at_level(logging.INFO, logger="app.report.gates"):
        kept = report_gates.exclude_unsafe_hypotheses(run.id, hyps, isolated_db)

    assert kept == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "no ideas" in message
    assert "safety review" in message
    assert "peer review" not in message


def test_gate_warning_names_review_rejection_not_safety(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Persisted review rejection skips safety screening; warning text must not
    # invent a safety cause.
    hyps = [
        {"id": "h1", "status": "rejected", "statement": "Idea one."},
        {"id": "h2", "status": "rejected", "statement": "Idea two."},
    ]

    with caplog.at_level(logging.INFO, logger="app.report.gates"):
        kept = report_gates.exclude_unsafe_hypotheses(
            "run-review-rejected", hyps, None, claim_edges=[]
        )

    assert kept == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "peer review" in message
    assert "safety review" not in message


def _drained_status(
    disposition: str | None, isolated_db: str, goal: str
) -> str:
    state = _final_state_with_lineage()
    state["hypotheses"][0]["review_disposition"] = disposition
    run = store.create_run(goal, "standard", "engine", {})
    _persist(run_id=run.id, final_state=state, db_path=isolated_db)
    by_id = {
        hypothesis["id"]: hypothesis
        for hypothesis in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    return str(by_id["parent-1"]["status"])


@pytest.mark.parametrize(
    "disposition", sorted(engine_models.BLOCKING_REVIEW_DISPOSITIONS)
)
def test_every_engine_blocking_disposition_drains_as_rejected(
    isolated_db: str, disposition: str
) -> None:
    assert _drained_status(disposition, isolated_db, f"{disposition} goal") == (
        "rejected"
    )


@pytest.mark.parametrize("disposition", [None, "needs_revision"])
def test_non_blocking_dispositions_still_publish(
    isolated_db: str, disposition: str | None
) -> None:
    assert (
        _drained_status(disposition, isolated_db, f"{disposition} goal")
        == "active"
    )


def test_a_new_engine_blocking_disposition_reaches_the_drain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # App publication must follow engine dispositions or report content
    # contradicts its own tournament tabs.
    monkeypatch.setattr(
        engine_models,
        "BLOCKING_REVIEW_DISPOSITIONS",
        engine_models.BLOCKING_REVIEW_DISPOSITIONS | {"superseded_by_evidence"},
    )
    status = _drained_status(
        "superseded_by_evidence", isolated_db, "drifted gate goal"
    )
    assert status == "rejected"


def test_offline_run_with_empty_leaderboard_is_blocked_like_a_real_run(
    isolated_db: str,
) -> None:
    # Offline scientific readiness is the same gate; only curated demos write
    # reports outside finalization.
    state = _final_state_with_lineage()
    for hypothesis in state["hypotheses"]:
        hypothesis["review_disposition"] = "unsafe"
    run = store.create_run(
        "offline empty leaderboard goal",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(llm_backend="offline", db_path=isolated_db),
    )

    _persist_and_finalize(run, state, isolated_db)

    settled = store.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == store.RunStatus.BLOCKED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is None
    assert settled.error is not None
    assert "peer review" in settled.error
    assert "safety review" not in settled.error
    assert "contradicted" not in settled.error


def _seed_scientist_hypothesis(run_id: str, db_path: str) -> str:
    return store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Scientist idea",
            statement="A scientist-proposed mechanism for kinase X.",
            created_by_agent="scientist_manual",
            author="dr-who",
        ),
        db_path=db_path,
    )


def _seed_scientist_review(
    run_id: str, hypothesis_id: str, db_path: str
) -> None:
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            reviewer_agent="scientist",
            summary="Scientist verdict: oppose (by dr-who)",
            critique="The proposed control cannot distinguish the mechanism.",
            author="dr-who",
            verdict="oppose",
        ),
        db_path=db_path,
    )


def _merged_final_state(run_id: str, db_path: str) -> dict[str, Any]:
    state: dict[str, Any] = {"hypotheses": []}
    engine_tasks_inputs._merge_scientist_inputs(state, run_id, db_path)
    return {
        "hypotheses": [h.to_dict() for h in state["hypotheses"]],
        "articles": [],
        "tournament_matchups": [],
        "proximity_graph": {},
        "meta_review": {},
        "research_overview": {},
    }


def _replay_finalize(
    run_id: str, final_state: dict[str, Any], db_path: str
) -> None:
    store.clear_publication_artifacts(run_id, db_path=db_path)
    _persist(run_id=run_id, final_state=final_state, db_path=db_path)


def test_drained_scientist_hypothesis_keeps_its_row(isolated_db: str) -> None:
    # Scientist rows survive publication resets; reconcile them instead of
    # inserting colliding copies.
    run = store.create_run("Scientist drain", "express", "engine", {})
    hypothesis_id = _seed_scientist_hypothesis(run.id, isolated_db)
    final_state = _merged_final_state(run.id, isolated_db)

    _replay_finalize(run.id, final_state, isolated_db)

    rows = store.list_hypotheses(run.id, isolated_db)
    assert [row["id"] for row in rows] == [hypothesis_id]
    assert rows[0]["author"] == "dr-who"
    assert rows[0]["created_by_agent"] == "scientist_manual"
    assert rows[0]["generation"] == 0
    assert rows[0]["parent_id"] is None
    assert rows[0]["safety_status"] is not None


def test_drained_scientist_hypothesis_keeps_tournament_counts(
    isolated_db: str,
) -> None:
    run = store.create_run("Scientist replay", "express", "engine", {})
    _seed_scientist_hypothesis(run.id, isolated_db)
    final_state = _merged_final_state(run.id, isolated_db)
    final_state["hypotheses"][0]["win_count"] = 3
    final_state["hypotheses"][0]["loss_count"] = 1

    _replay_finalize(run.id, final_state, isolated_db)
    _replay_finalize(run.id, final_state, isolated_db)

    rows = store.list_hypotheses(run.id, isolated_db)
    assert (rows[0]["win_count"], rows[0]["loss_count"]) == (3, 1)


def test_drained_scientist_review_keeps_author_and_verdict(
    isolated_db: str,
) -> None:
    run = store.create_run("Scientist review drain", "express", "engine", {})
    hypothesis_id = _seed_scientist_hypothesis(run.id, isolated_db)
    _seed_scientist_review(run.id, hypothesis_id, isolated_db)
    final_state = _merged_final_state(run.id, isolated_db)

    _replay_finalize(run.id, final_state, isolated_db)

    reviews = store.list_reviews(run.id, isolated_db)
    assert [row["reviewer_agent"] for row in reviews] == ["scientist"]
    assert reviews[0]["author"] == "dr-who"
    assert reviews[0]["verdict"] == "oppose"


def test_scientist_review_score_uses_the_engine_review_rubric(
    isolated_db: str,
) -> None:
    # Human verdicts share agent review scales; guessing off-scale scores
    # misleads tournament judges.
    from co_scientist.constants import NEEDS_REVISION_SCORE, NOT_VIABLE_SCORE

    run = store.create_run("Scientist rubric", "express", "engine", {})
    hypothesis_id = _seed_scientist_hypothesis(run.id, isolated_db)
    _seed_scientist_review(run.id, hypothesis_id, isolated_db)
    state: dict[str, Any] = {"hypotheses": []}

    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)

    review = state["hypotheses"][0].reviews[0]
    assert review.overall_score == NOT_VIABLE_SCORE
    assert review.overall_score <= NEEDS_REVISION_SCORE
    assert review.detailed_feedback["scientist_author"] == "dr-who"
    assert review.detailed_feedback["scientist_verdict"] == "oppose"

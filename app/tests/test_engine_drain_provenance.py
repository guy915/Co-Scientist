"""Tests for engine drain 3."""

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

# The drain closing the loop on retrieval provenance.
#
# The store has held a ``retrieval_calls`` table and a
# ``evidence.retrieval_call_id`` column since the schema change that made
# room for them, and until a run actually wrote both the column stayed
# NULL. These tests pin the end of that path: a run whose literature review
# went back for its open questions leaves searches on record, and every
# piece of evidence it found names the search that found it.
#
# The final states here are synthetic, in the shape the engine's literature
# review and its deep reviews produce -- a ``research_ledgers`` list, one
# entry per research request, and articles stamped with the call that
# surfaced them.


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


def _provenance_final_state(*, researched: bool) -> dict[str, Any]:
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
    """A coverage report cannot tell "unseen" from "seen and skipped"."""
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
    """Express and standard runs do not buy the phase, and that is fine."""
    run = store.create_run("shallow goal", "standard", "engine", {})

    _persist_and_finalize(
        run, _provenance_final_state(researched=False), isolated_db
    )

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
    """A call's id is its content, so the store deduplicates for free."""
    run = store.create_run("same search twice", "ultra", "engine", {})
    state = _provenance_final_state(researched=True)
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


# A run that reached no literature source says so in its report.
#
# The engine records the fact; these tests pin that it survives the drain
# and lands in the payload the workbench reads. It is the one degradation a
# reader cannot infer from the output: the run still publishes ideas,
# reviews and a tournament, and nothing in any of them reveals that none of
# it was checked against a paper.


def _degradation_final_state(
    degradation: dict[str, Any] | None,
) -> dict[str, Any]:
    """A drained run, with or without a retrieval outage behind it.

    An ordinary complete run otherwise: a degraded run publishes the same
    report a healthy one does, which is the whole problem.
    """
    return {
        **_final_state_with_features(),
        "retrieval_degradation": degradation,
    }


def test_the_report_carries_what_the_run_could_not_search(
    isolated_db: str,
) -> None:
    """Without this the run publishes as though it never needed sources."""
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
    """Absent rather than an empty shape, so the notice cannot misfire."""
    run = store.create_run("healthy goal", "extended", "engine", {})

    _persist_and_finalize(run, _degradation_final_state(None), isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["retrieval_degradation"] is None


# Engine-drain tests for rank-and-publish gating.
#
# Split out of ``test_engine_drain.py`` by concern. These cover the
# rank-and-publish split of contradicted versus merely unverified ideas and
# the persisted-status gate that decides which drained ideas the report may
# publish at all. The PARITY-cited synthesis-exclusion case stays in
# ``test_engine_drain.py``; the drain's per-hypothesis safety screen (writing
# ``safety_status`` and held-review audit rows before finalize) moved to
# ``test_engine_drain_hypothesis_screening.py`` when this file passed the
# module-size budget.


def _seed_gate_split(run: Any, db_path: str) -> tuple[str, str, str]:
    """Seed supported/unsupported/contradicted hypotheses for the gate split.

    The supported idea gets a ``supports`` edge and the contradicted one a
    ``contradicts`` edge; the unsupported idea deliberately gets no edge at all.
    """
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
    """Add a supports edge for the supported id, contradicts for the other."""
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
    """Contradicted ideas are withheld; unsupported ones publish unverified.

    Batch 9 rank-and-publish: ``exclude_unsafe_hypotheses`` drops a
    contradicted idea but keeps a merely-unsupported one, which
    ``unverified_hypothesis_ids`` flags for the "Unverified" badge. A run with
    no claim-evidence at all (mock demo runs) flags nothing.
    """
    run = store.create_run("gate split", "standard", "engine", {})
    supported_id, unsupported_id, contradicted_id = _seed_gate_split(
        run, isolated_db
    )

    contradicted = report_gates.contradicted_hypothesis_ids(run.id, isolated_db)
    unverified = report_gates.unverified_hypothesis_ids(run.id, isolated_db)
    assert contradicted == {contradicted_id}
    # Only the supported idea has a ``supports`` edge; the other two lack one.
    assert unverified == {unsupported_id, contradicted_id}

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    kept_ids = {
        h["id"]
        for h in report_gates.exclude_unsafe_hypotheses(
            run.id, hyps, isolated_db
        )
    }
    # Contradicted is withheld; supported and unsupported both publish.
    assert kept_ids == {supported_id, unsupported_id}

    _assert_demo_run_badges_nothing(isolated_db)


def _assert_demo_run_badges_nothing(db_path: str) -> None:
    """A run with no claim-evidence at all badges nothing (demo exemption)."""
    demo = store.create_run("demo", "standard", "mock", {})
    store.add_hypothesis(
        store.NewHypothesis(
            run_id=demo.id, title="Demo", statement="Demo idea."
        ),
        db_path=db_path,
    )
    assert report_gates.unverified_hypothesis_ids(demo.id, db_path) == set()


def test_partial_edge_clears_the_unverified_badge(isolated_db: str) -> None:
    """A hypothesis whose best evidence is PARTIAL is not badged unverified.

    A partial (near-miss) verdict means relevant, consistent evidence was
    found, so it clears the badge exactly as a ``supports`` edge does -- the
    fix for the flood of "Unverified" ideas whose claims only ever landed on
    ``insufficient``.
    """
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
    # The partial idea clears the badge; only the insufficient one is flagged.
    assert unverified == {insufficient_id}


def test_gate_reports_exclusions_once_and_at_info(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A withheld idea is news at info; the report losing every idea warns.

    Withholding a contradicted or unsafe idea is the gate doing its job, so
    it belongs in the run narrative rather than in the warnings band -- one
    warning per idea is a row per idea that needs no action. The case that
    does need one is the gate emptying the report.
    """
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
    """Nothing left to synthesize is the outcome worth a warning.

    This hypothesis has no persisted review disposition or safety_status
    (a legacy row), so it is excluded through the gate's own re-review
    fallback -- a genuine safety exclusion, and the warning must say so.
    """
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
    """A review-rejected pool warns about peer review, never safety.

    Unlike the legacy-fallback case above, a hypothesis already carrying a
    persisted ``status="rejected"`` (the engine's own blocking review
    disposition) is excluded on that status alone -- the gate never
    re-reviews it, and the warning must not imply it did.
    """
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
    """Drain a state whose parent carries ``disposition``; return its status."""
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
    """Persisted status tracks the engine's tournament gate, member for member.

    Parametrized over the engine's own set rather than a copy of it: what a
    run may publish and what a run may rank are one rule, and the app used
    to restate both the set and the predicate over it.
    """
    assert _drained_status(disposition, isolated_db, f"{disposition} goal") == (
        "rejected"
    )


@pytest.mark.parametrize("disposition", [None, "needs_revision"])
def test_non_blocking_dispositions_still_publish(
    isolated_db: str, disposition: str | None
) -> None:
    """A weak-but-not-fatal idea competes and publishes; the tournament rules.

    ``duplicate`` is deliberately absent from both this list and the engine's
    blocking set -- it has its own status and its own wording, covered by
    ``test_drain_preserves_proximity_pruned_parent_as_a_duplicate``.
    """
    assert (
        _drained_status(disposition, isolated_db, f"{disposition} goal")
        == "active"
    )


def test_a_new_engine_blocking_disposition_reaches_the_drain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disposition added to the engine must not stay publishable here.

    The drift the drain used to be exposed to, simulated: a disposition the
    engine starts blocking on makes an idea unrankable there, so the app
    must stop recording it ``active`` and publishing it -- the "report
    contradicts its own tabs" failure. The app no longer keeps its own copy
    of the set or of the predicate over it, so this arrives for free.
    """
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
    """The scientific-readiness gate applies to offline runs too.

    The offline LLM backend still drives the real graph end to end, so an
    empty leaderboard there means the same "nothing survived review" outcome
    as a real run's -- publishing anyway would understate the failure. Only
    the three curated default demos are exempt, and they bypass this gate
    entirely by writing their report row directly (see ``seed/__init__.py``); an
    ad-hoc offline run reaches the same ``finalize_report`` path a real run
    does.

    This is production run 44e848fb reproduced: no safety_status was ever
    set (safety screened 0 blocked) and no claim-evidence edges exist
    (grounding assessed nothing) -- every idea left the report solely
    because the initial review gate rejected it. The blocked reason must
    name that, not the safety review or a contradiction neither pipeline
    ever ran.
    """
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


# Scientist contributions surviving the engine final-state drain.
#
# A scientist-contributed hypothesis and review are persisted at POST time,
# merged into engine state at the next task boundary, and then drained back
# out with the rest of the final state. These tests pin what that round trip
# must preserve: the hypothesis's own row (id, author, provenance, lineage,
# safety state) rather than a colliding second insert, and the review's
# authorship and verdict rather than a generic re-attributed copy.


def _seed_scientist_hypothesis(run_id: str, db_path: str) -> str:
    """Persist a scientist-contributed hypothesis the way the endpoint does."""
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
    """Persist a scientist review the way the endpoint does."""
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
    """Merge the run's scientist input and shape it as a drained final state."""
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
    """Run the finalizer's publication reset and drain, as its task does."""
    store.clear_publication_artifacts(run_id, db_path=db_path)
    _persist(run_id=run_id, final_state=final_state, db_path=db_path)


def test_drained_scientist_hypothesis_keeps_its_row(isolated_db: str) -> None:
    """The scientist's own row is preserved, not re-inserted into a collision.

    The row survives the finalizer's publication reset by design, so the
    drain meets an id it already stored and must reconcile with it rather
    than insert a duplicate.
    """
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
    """Replaying the finalizer does not accumulate the row's win/loss counts."""
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
    """The review stays attributed to its author, not relabeled 'review'."""
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
    """A scientist verdict scores on the same 1-10 scale as agent reviews.

    The score is read from the persisted verdict, not guessed from words in
    the summary prose, and lands in the rubric band the verdict means -- the
    ranking prompt renders it beside agent scores, so an off-scale value
    (the old 20/60/90) misrepresents the idea to the judge.
    """
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

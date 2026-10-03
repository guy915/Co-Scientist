from __future__ import annotations

import json
import sqlite3
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.agents.ranking.ranking_debate import (
    _debate_provenance_fields,
    _DebateRun,
    _finalize_debate_response,
    _MatchupPrompt,
)
from co_scientist.llm import campaign_free_mode

import app.citations as citation_metadata
import app.citations as citation_resolver
from app import safety, store
from app.citations import (
    CitationMetadata,
    Resolvability,
    Resolver,
    offline_resolver,
)
from app.config import settings
from app.engine_adapter.drain import final_state as drain_final_state
from app.engine_adapter.drain.hypotheses import _authored_title
from app.engine_adapter.drain.matches import _persist_engine_matches
from app.execution_policy import scoped_execution_policy
from app.hypothesis import screen_hypotheses
from app.report import markdown as report_markdown
from tests._drain_helpers import (
    _engine_hypothesis,
    _final_state_with_features,
    _held_final_state,
    _persist,
    _persist_and_finalize,
)
from tests._process_mode_helpers import FakeProcessMode

from ._llm_fake_backend import install_completion_backend

_HELD_TEXT = (
    "Improving hospital triage protocols and resource allocation for "
    "mass casualty events such as natural disasters."
)


def _escalation_state(held_text: str = _HELD_TEXT) -> dict[str, Any]:
    return {
        "hypotheses": [
            _engine_hypothesis(
                "safe-1",
                "Inhibiting kinase X reduces AML growth via apoptosis.",
            ),
            _engine_hypothesis("held-1", held_text),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def _real_run(goal: str) -> store.RunRow:
    return store.create_run(goal, "standard", "engine", {})


def _fake_semantic_response(category: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=f'{{"category":"{category}","reason":"model"}}'
                )
            )
        ]
    )


def _stub_eligible(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online()


def _held_status(run_id: str, isolated_db: str) -> str:
    by_id = {
        h["id"]: h for h in store.list_hypotheses(run_id, db_path=isolated_db)
    }
    return str(by_id["held-1"]["safety_status"])


def test_drain_escalates_and_raises_a_held_verdict(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    async def block_completion(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("prohibited")

    _stub_eligible(monkeypatch, fake_process_mode)
    install_completion_backend(monkeypatch, block_completion)
    run = _real_run("drain escalation raise")

    _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )

    assert _held_status(run.id, isolated_db) == "prohibited"
    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    raised = [
        d
        for d in decisions
        if d["stage"] == "hypothesis" and "prohibited" in d["reason"]
    ]
    assert raised, "expected an audit row recording the escalation's raise"


def test_campaign_scope_reaches_held_hypothesis_executor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.hypothesis.safety as hypothesis_safety_resolve

    seen: list[bool] = []

    async def resolve(review: Any, *_args: Any, **_kwargs: Any) -> Any:
        seen.append(campaign_free_mode())
        return review

    monkeypatch.setattr(hypothesis_safety_resolve, "resolve_hold", resolve)
    run = _real_run("campaign executor propagation")

    with scoped_execution_policy("campaign"):
        _persist(
            run_id=run.id,
            final_state=_escalation_state(),
            db_path=isolated_db,
        )

    assert seen and all(seen)


def test_rescreen_does_not_downgrade_an_escalation_raised_block(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    # Re-screening unchanged text must not undo a stronger contextual verdict.

    async def block_completion(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("prohibited")

    _stub_eligible(monkeypatch, fake_process_mode)
    install_completion_backend(monkeypatch, block_completion)
    run = _real_run("drain escalation rescreen")

    _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )
    assert _held_status(run.id, isolated_db) == "prohibited"
    before = store.list_safety_decisions(run.id, db_path=isolated_db)

    second = screen_hypotheses(
        run.id,
        store.list_hypotheses(run.id, db_path=isolated_db),
        db_path=isolated_db,
    )

    assert _held_status(run.id, isolated_db) == "prohibited"
    assert "held-1" in second.blocked_ids
    assert second.escalatable == ()
    after = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert len(after) == len(before), "re-screen must not duplicate audit rows"


def test_drain_escalation_fails_closed_on_missing_credential(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online(credential=False)
    run = _real_run("drain escalation no credential")

    _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )

    assert _held_status(run.id, isolated_db) == "uncertain"


def test_drain_escalation_fails_closed_on_provider_error(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:

    async def raise_completion(**_: object) -> None:
        raise RuntimeError("provider unavailable")

    _stub_eligible(monkeypatch, fake_process_mode)
    install_completion_backend(monkeypatch, raise_completion)
    run = _real_run("drain escalation provider error")

    _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )

    assert _held_status(run.id, isolated_db) == "uncertain"


def test_drain_skips_escalation_cleanly_when_offline(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:

    async def fail_if_called(**_: object) -> None:
        raise AssertionError(
            "an offline-backed run must never call the provider"
        )

    install_completion_backend(monkeypatch, fail_if_called)
    run = store.create_run(
        "drain escalation offline",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(llm_backend="offline", db_path=isolated_db),
    )

    drained = _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )

    assert drained.safety_counts["screened"] == 2
    assert _held_status(run.id, isolated_db) == "uncertain"


def test_escalation_does_not_hold_the_write_lock(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    # Stall escalation to prove unrelated writes proceed; provider I/O must
    # never hold the SQLite writer.
    call_started = threading.Event()
    release_call = threading.Event()

    async def slow_completion(**_: object) -> SimpleNamespace:
        call_started.set()
        assert release_call.wait(timeout=5), "test did not release the call"
        return _fake_semantic_response("allowed")

    _stub_eligible(monkeypatch, fake_process_mode)
    install_completion_backend(monkeypatch, slow_completion)
    run = _real_run("drain escalation lock check")

    errors: list[BaseException] = []

    def _run_drain() -> None:
        try:
            _persist(
                run_id=run.id,
                final_state=_escalation_state(),
                db_path=isolated_db,
            )
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=_run_drain)
    worker.start()
    try:
        assert call_started.wait(timeout=5), "escalation call never started"
        start = time.monotonic()
        store.create_run(
            "concurrent write during escalation", "standard", "engine", {}
        )
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, (
            "a concurrent write blocked for "
            f"{elapsed:.2f}s -- the write lock is held across the call"
        )
    finally:
        release_call.set()
        worker.join(timeout=5)
    assert not errors, errors


async def test_a_cleared_hold_is_audited_as_an_allow_not_a_block(
    monkeypatch: pytest.MonkeyPatch,
    isolated_db: str,
    fake_process_mode: FakeProcessMode,
) -> None:
    # Audit decisions must reflect resolved outcomes, including allow, rather
    # than a historical hardcoded block.
    _stub_eligible(monkeypatch, fake_process_mode)

    async def _allow(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("allowed")

    install_completion_backend(monkeypatch, _allow)
    run = _real_run("cleared hold audit")

    await drain_final_state.persist_final_state(
        run_id=run.id,
        final_state=_escalation_state(),
        db_path=isolated_db,
    )

    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    held_rows = [
        row
        for row in decisions
        if row["stage"] == "hypothesis" and "uncertain" not in row["reason"]
    ]
    assert held_rows, "the resolution must leave an audit row"
    assert all(row["decision"] == "allow" for row in held_rows), (
        f"a cleared hold was audited as a block: {held_rows}"
    )


def _final_state_with_article(article: dict[str, Any]) -> dict[str, Any]:
    return {
        "hypotheses": [],
        "articles": [article],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def test_drain_persists_doi_pmid_passage_and_retrieval_timestamp(
    isolated_db: str,
) -> None:
    run = store.create_run("identity goal", "standard", "engine", {})
    article = {
        "title": "A PubMed paper",
        "source": "pubmed",
        "source_id": "12345678",
        "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "doi": "10.1000/xyz123",
        "abstract": "An abstract about kinase X.",
        "retrieved_at": 111.5,
    }
    _persist_and_finalize(run, _final_state_with_article(article), isolated_db)

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    assert len(evidence) == 1
    row = evidence[0]
    assert row["doi"] == "10.1000/xyz123"
    assert row["pmid"] == "12345678"
    assert row["passage_text"] == "A PubMed paper An abstract about kinase X."
    assert row["retrieved_at"] == 111.5
    assert row["created_at"] != row["retrieved_at"]


def test_drain_derives_pmid_from_pubmed_url_without_source_id(
    isolated_db: str,
) -> None:
    run = store.create_run("identity goal", "standard", "engine", {})
    article = {
        "title": "Untagged source article",
        "source": "web",
        "url": "https://pubmed.ncbi.nlm.nih.gov/98765432/",
        "abstract": "Some abstract text.",
    }
    _persist_and_finalize(run, _final_state_with_article(article), isolated_db)

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    assert evidence[0]["pmid"] == "98765432"
    assert evidence[0]["doi"] is None


def test_offline_resolver_available_matches_metadata_heuristic(
    isolated_db: str,
) -> None:
    run = store.create_run("identity goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [],
        "articles": [
            {
                "title": "Reachable-by-metadata paper",
                "source": "pubmed",
                "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
                "abstract": "x",
            },
            {
                "title": "Retracted paper",
                "source": "pubmed",
                "url": "https://pubmed.ncbi.nlm.nih.gov/2/",
                "abstract": "x",
                "is_retracted": True,
            },
            {
                "title": "No identifier at all",
                "source": "pubmed",
                "url": "",
                "abstract": "x",
            },
        ],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }
    _persist_and_finalize(run, final_state, isolated_db)

    evidence = {
        e["title"]: e for e in store.list_evidence(run.id, db_path=isolated_db)
    }
    assert evidence["Reachable-by-metadata paper"]["available"] is True
    assert evidence["Reachable-by-metadata paper"]["retracted"] is False
    assert evidence["Retracted paper"]["available"] is False
    assert evidence["Retracted paper"]["retracted"] is True
    assert evidence["No identifier at all"]["available"] is False
    assert evidence["No identifier at all"]["retracted"] is False


def test_live_resolver_dereferences_rather_than_inspecting_the_string(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "evidence_resolver", "live")

    def fake_resolve_many(
        metas: list[CitationMetadata], *, resolver: Resolver
    ) -> list[Resolvability]:
        return [
            Resolvability.RESOLVABLE,
            Resolvability.UNRESOLVABLE,
        ]

    monkeypatch.setattr(
        citation_resolver,
        "resolve_many",
        fake_resolve_many,
    )

    run = store.create_run("identity goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [],
        "articles": [
            {
                "title": "Actually reachable",
                "source": "pubmed",
                "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
                "abstract": "x",
            },
            {
                "title": "URL present but dead",
                "source": "pubmed",
                "url": "https://pubmed.ncbi.nlm.nih.gov/2/",
                "abstract": "x",
            },
        ],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }
    _persist_and_finalize(run, final_state, isolated_db)

    evidence = {
        e["title"]: e for e in store.list_evidence(run.id, db_path=isolated_db)
    }
    assert evidence["Actually reachable"]["available"] is True
    assert evidence["Actually reachable"]["retracted"] is False
    assert evidence["URL present but dead"]["available"] is False
    assert evidence["URL present but dead"]["retracted"] is False


def test_live_resolver_persists_retraction_from_either_source(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "evidence_resolver", "live")

    def fake_resolve_many(
        metas: list[CitationMetadata], *, resolver: Resolver
    ) -> list[Resolvability]:
        first_verdict = (
            Resolvability.RETRACTED
            if metas[0].retracted
            else Resolvability.RESOLVABLE
        )
        return [first_verdict, Resolvability.RETRACTED]

    monkeypatch.setattr(
        citation_resolver,
        "resolve_many",
        fake_resolve_many,
    )

    run = store.create_run("identity goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [],
        "articles": [
            {
                "title": "Flagged by metadata",
                "source": "pubmed",
                "url": "https://pubmed.ncbi.nlm.nih.gov/3/",
                "abstract": "x",
                "is_retracted": True,
            },
            {
                "title": "Caught by the live retraction set",
                "source": "pubmed",
                "url": "https://pubmed.ncbi.nlm.nih.gov/4/",
                "abstract": "x",
            },
        ],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }
    _persist_and_finalize(run, final_state, isolated_db)

    evidence = {
        e["title"]: e for e in store.list_evidence(run.id, db_path=isolated_db)
    }
    for title in ("Flagged by metadata", "Caught by the live retraction set"):
        assert evidence[title]["available"] is False
        assert evidence[title]["retracted"] is True


def test_old_evidence_row_with_no_retracted_column_renders_unretracted(
    isolated_db: str,
) -> None:
    # Added nullable retraction columns cannot establish facts about legacy
    # evidence.
    run = store.create_run("identity goal", "standard", "engine", {})
    article = {
        "title": "Pre-migration paper",
        "source": "pubmed",
        "url": "",
        "abstract": "x",
    }
    _persist_and_finalize(run, _final_state_with_article(article), isolated_db)

    with sqlite3.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE evidence SET retracted = NULL WHERE run_id = ?", (run.id,)
        )
        conn.commit()

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    assert len(evidence) == 1
    assert evidence[0]["available"] is False
    assert evidence[0]["retracted"] is False


def test_drain_persists_hybrid_retrieval_score_provenance(
    isolated_db: str,
) -> None:
    run = store.create_run("identity goal", "standard", "engine", {})
    article = {
        "title": "Scored paper",
        "source": "pubmed",
        "url": "https://pubmed.ncbi.nlm.nih.gov/3/",
        "abstract": "x",
        "retrieval_score": 0.87,
        "retrieval_rationale": "Directly addresses the goal.",
        "retriever_version": "hybrid-lexical-semantic/1",
    }
    _persist_and_finalize(run, _final_state_with_article(article), isolated_db)

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    row = evidence[0]
    assert row["retrieval_score"] == 0.87
    assert row["retrieval_rationale"] == "Directly addresses the goal."
    assert row["retriever_version"] == "hybrid-lexical-semantic/1"


def test_evidence_passages_uses_stored_passage_text(
    isolated_db: str,
) -> None:
    # Located offsets index the exact materialized passage, never a later
    # reconstruction.
    from app.claims.grounding import evidence_passages

    run = store.create_run("identity goal", "standard", "engine", {})
    article = {
        "title": "Passage paper",
        "source": "pubmed",
        "url": "https://pubmed.ncbi.nlm.nih.gov/4/",
        "abstract": "About kinase X inhibition.",
    }
    _persist_and_finalize(run, _final_state_with_article(article), isolated_db)

    passages = evidence_passages(run.id, db_path=isolated_db)
    assert len(passages) == 1
    assert passages[0].text == "Passage paper About kinase X inhibition."


def test_live_path_routes_every_verdict_through_the_resolvability_seam(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "evidence_resolver", "live")
    seen: list[tuple[CitationMetadata, Resolver]] = []

    def recording_assess(
        meta: CitationMetadata, *, resolver: Resolver = offline_resolver
    ) -> Resolvability:
        seen.append((meta, resolver))
        return Resolvability.RESOLVABLE

    monkeypatch.setattr(
        citation_metadata, "assess_resolvability", recording_assess
    )

    run = store.create_run("identity goal", "standard", "engine", {})
    article = {
        "title": "Seam paper",
        "source": "pubmed",
        "source_id": "42",
        "url": "https://pubmed.ncbi.nlm.nih.gov/42/",
        "doi": "10.1000/seam",
        "abstract": "x",
    }
    _persist_and_finalize(run, _final_state_with_article(article), isolated_db)

    assert len(seen) == 1
    meta, resolver = seen[0]
    assert isinstance(meta, CitationMetadata)
    assert (meta.doi, meta.pmid) == ("10.1000/seam", "42")
    assert resolver is citation_resolver.live_resolver


def test_offline_path_routes_through_the_same_seam(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Resolver] = []

    def recording_assess(
        meta: CitationMetadata, *, resolver: Resolver = offline_resolver
    ) -> Resolvability:
        seen.append(resolver)
        return resolver(meta)

    monkeypatch.setattr(
        citation_metadata, "assess_resolvability", recording_assess
    )

    run = store.create_run("identity goal", "standard", "engine", {})
    article = {
        "title": "Offline seam paper",
        "source": "pubmed",
        "url": "https://pubmed.ncbi.nlm.nih.gov/43/",
        "abstract": "x",
    }
    _persist_and_finalize(run, _final_state_with_article(article), isolated_db)

    assert seen == [offline_resolver]


def test_drain_persists_the_classified_source_type(
    isolated_db: str,
) -> None:
    # Publication type is lost after draining, so classify once while engine
    # metadata is available.
    run = store.create_run("identity goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [],
        "articles": [
            {
                "title": "Journal paper",
                "source": "pubmed",
                "url": "https://pubmed.ncbi.nlm.nih.gov/5/",
                "abstract": "x",
            },
            {
                "title": "Preprint indexed in pubmed",
                "source": "pubmed",
                "url": "https://pubmed.ncbi.nlm.nih.gov/6/",
                "abstract": "x",
                "publication_type": "Preprint",
            },
            {
                "title": "Preprint server paper",
                "source": "biorxiv",
                "url": "https://www.biorxiv.org/content/10.1101/7v1",
                "abstract": "x",
            },
        ],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }
    _persist_and_finalize(run, final_state, isolated_db)

    evidence = {
        e["title"]: e for e in store.list_evidence(run.id, db_path=isolated_db)
    }
    assert evidence["Journal paper"]["source_type"] == "peer_reviewed"
    assert evidence["Preprint indexed in pubmed"]["source_type"] == "preprint"
    assert evidence["Preprint server paper"]["source_type"] == "preprint"


def test_persist_writes_safety_and_toxicity_onto_the_hypothesis_row(
    isolated_db: str,
) -> None:
    # Proposer safety prose is not reviewer assessment and must never control
    # the safety gate.
    run = store.create_run("CSC goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-safety",
                "Blocking CXCR1 suppresses breast cancer stem cells.",
                safety_and_toxicity=(
                    "Limited human safety data exists for this class."
                ),
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }
    _persist(
        run_id=run.id,
        final_state=final_state,
        db_path=isolated_db,
    )

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    assert len(hyps) == 1
    assert hyps[0]["safety_and_toxicity"] == (
        "Limited human safety data exists for this class."
    )


_STATEMENT = "Blocking CXCR1 suppresses breast cancer stem cells. It works."


def test_authored_title_used_verbatim_when_present() -> None:
    title = _authored_title(
        {"title": "CXCR1 Blockade Against Breast Cancer Stem Cells"},
        _STATEMENT,
    )
    assert title == "CXCR1 Blockade Against Breast Cancer Stem Cells"


def test_authored_title_falls_back_when_field_absent() -> None:
    assert _authored_title({}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )


def test_authored_title_falls_back_when_field_is_malformed() -> None:
    assert _authored_title({"title": ["not", "a", "string"]}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )
    assert _authored_title({"title": 42}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )


def test_authored_title_falls_back_when_field_is_blank() -> None:
    assert _authored_title({"title": ""}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )
    assert _authored_title({"title": "   \n\t"}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )


def test_authored_title_is_clipped_past_the_display_cap() -> None:
    long_title = "A" * 150
    title = _authored_title({"title": long_title}, _STATEMENT)
    assert title == "A" * 120
    assert len(title) == 120


def test_persist_writes_the_authored_title_onto_the_hypothesis_row(
    isolated_db: str,
) -> None:
    run = store.create_run("CSC goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [
            _engine_hypothesis(
                "eng-hyp-title",
                _STATEMENT,
                title="CXCR1 Blockade Against Breast Cancer Stem Cells",
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }
    _persist(run_id=run.id, final_state=final_state, db_path=isolated_db)

    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    assert len(hyps) == 1
    assert hyps[0]["title"] == "CXCR1 Blockade Against Breast Cancer Stem Cells"


def test_persist_derives_the_title_for_an_evolved_child_without_one(
    isolated_db: str,
) -> None:
    # A child's mechanism can diverge; missing titles derive from its own text
    # rather than its parent.
    run = store.create_run("CSC goal", "standard", "engine", {})
    final_state = {
        "hypotheses": [
            _engine_hypothesis(
                "parent-1",
                "Parent hypothesis about kinase X. Details follow.",
                title="Kinase X Inhibition Strategy",
                parent_id=None,
                generation=0,
                origin="generation",
            ),
            _engine_hypothesis(
                "child-1",
                "Child hypothesis: kinase X plus cofactor W. More detail.",
                parent_id="parent-1",
                generation=1,
                origin="evolution",
            ),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }
    _persist(run_id=run.id, final_state=final_state, db_path=isolated_db)

    hyps = {
        h["id"]: h for h in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    assert hyps["parent-1"]["title"] == "Kinase X Inhibition Strategy"
    assert hyps["child-1"]["title"] == (
        "Child hypothesis: kinase X plus cofactor W"
    )


def _screening_hypothesis(hyp_id: str, text: str) -> dict[str, Any]:
    return {
        "id": hyp_id,
        "text": text,
        "parent_id": None,
        "generation": 0,
        "origin": "generation",
        "elo_rating": 1200,
        "win_count": 0,
        "loss_count": 0,
        "reviews": [],
        "citation_map": {},
        "evolution_history": [],
        "deep_verification_probes": [],
        "deep_verification_verdict": None,
    }


def _screening_state() -> dict[str, Any]:
    return {
        "hypotheses": [
            _screening_hypothesis(
                "safe-1",
                "Inhibiting kinase X reduces AML growth via apoptosis.",
            ),
            _screening_hypothesis(
                "unsafe-1",
                "Weaponize the pathogen to enhance transmissibility.",
            ),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def test_drain_screens_hypotheses_before_finalize(isolated_db: str) -> None:
    run = store.create_run("safety goal", "standard", "engine", {})
    state = _screening_state()

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    by_text = {h["statement"][:8]: h for h in store.list_hypotheses(run.id)}
    assert by_text["Inhibiti"]["safety_status"] == "allow"
    assert by_text["Weaponiz"]["safety_status"] == "prohibited"

    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert any(
        d["stage"] == "hypothesis" and d["decision"] == "block"
        for d in decisions
    )


def test_drain_persists_held_hypotheses_as_reviewable_decisions(
    isolated_db: str,
) -> None:
    # Held ideas leave the engine pool, so drain must preserve adjudicable
    # decisions before they disappear.
    run = store.create_run("held hypotheses goal", "standard", "engine", {})

    _persist(
        run_id=run.id,
        final_state=_held_final_state(),
        db_path=isolated_db,
    )

    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    holds = [d for d in decisions if d["decision"] == "hold"]
    assert len(holds) == 2
    for row in holds:
        assert row["stage"] == "hypothesis"
        assert row["requires_review"] is True
        assert row["resolution"] is None
        assert row["policy_version"] == "coscientist-safety-v5"
        assert row["matches"] == ["for research purposes only"]
        assert "uncertain" in row["reason"]
        assert "obfuscated intent" in row["reason"]
    reasons = " ".join(row["reason"] for row in holds)
    assert "held-1" in reasons and "held-2" in reasons
    assert "enhance pathogen transmissibility" in reasons
    assert "toxin production line" in reasons
    assert [h["id"] for h in store.list_hypotheses(run.id)] == ["safe-1"]


def test_drain_records_a_hold_without_an_engine_audit_entry(
    isolated_db: str,
) -> None:
    # Missing audit joins must not discard held hypotheses; retain a hold with
    # fallback rationale.
    run = store.create_run("orphan hold goal", "standard", "engine", {})
    state = _held_final_state()
    state["safety_decisions"] = []

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    holds = [
        d
        for d in store.list_safety_decisions(run.id, db_path=isolated_db)
        if d["decision"] == "hold"
    ]
    assert len(holds) == 2
    for row in holds:
        assert row["requires_review"] is True
        assert row["reason"]


def _multi_parent_state() -> dict[str, Any]:
    return {
        "hypotheses": [
            _engine_hypothesis(
                "parent-1",
                "Parent hypothesis about kinase X.",
                parent_id=None,
                generation=0,
                origin="generation",
            ),
            _engine_hypothesis(
                "parent-2",
                "Parent hypothesis about cofactor W.",
                parent_id=None,
                generation=0,
                origin="generation",
            ),
            _engine_hypothesis(
                "child-1",
                "Combined hypothesis: kinase X with cofactor W.",
                parent_id="parent-1",
                parent_ids=["parent-1", "parent-2"],
                generation=1,
                origin="evolution",
            ),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def test_drain_persists_multi_parent_lineage(isolated_db: str) -> None:
    run = store.create_run("combine goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state=_multi_parent_state(),
        db_path=isolated_db,
    )

    hyps = {
        h["id"]: h for h in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    child = hyps["child-1"]
    assert child["parent_id"] == "parent-1"
    assert child["parent_ids"] == ["parent-1", "parent-2"]
    assert hyps["parent-1"]["parent_ids"] is None
    assert hyps["parent-2"]["parent_ids"] is None


def test_drain_drops_pruned_co_parent_from_lineage(isolated_db: str) -> None:
    # Archived co-parents must not survive as dangling ids in persisted lineage.
    state = _multi_parent_state()
    state["hypotheses"] = [
        h for h in state["hypotheses"] if h["id"] != "parent-2"
    ]
    run = store.create_run("combine goal", "standard", "engine", {})
    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    hyps = {
        h["id"]: h for h in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    child = hyps["child-1"]
    assert child["parent_id"] == "parent-1"
    assert child["parent_ids"] is None


def test_drain_persists_creation_iteration(isolated_db: str) -> None:
    # Unknown creation cycles remain NULL so scaling falls back to generation
    # rather than inventing cycle zero.
    run = store.create_run("kinase goal", "standard", "engine", {})
    _persist(
        run_id=run.id,
        final_state={
            "hypotheses": [
                _engine_hypothesis("seed", "Seed idea.", creation_iteration=0),
                _engine_hypothesis(
                    "reborn", "Re-generated later.", creation_iteration=2
                ),
                _engine_hypothesis("legacy", "No cycle stamped."),
            ],
            "articles": [],
            "tournament_matchups": [],
            "meta_review": {},
            "evolution_details": [],
            "research_overview": {},
        },
        db_path=isolated_db,
    )

    by_id = {
        h["id"]: h for h in store.list_hypotheses(run.id, db_path=isolated_db)
    }
    assert by_id["seed"]["creation_iteration"] == 0
    assert by_id["reborn"]["creation_iteration"] == 2
    assert by_id["legacy"]["creation_iteration"] is None


def test_persist_match_records_the_iteration_it_was_judged_in(
    isolated_db: str,
) -> None:
    state = _final_state_with_features()
    state["tournament_matchups"][0]["iteration"] = 2
    run = store.create_run("CSC goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    matches = store.list_matches(run.id, db_path=isolated_db)
    assert [match["iteration"] for match in matches] == [2]


def test_persist_match_without_an_iteration_falls_back_to_zero(
    isolated_db: str,
) -> None:
    state = _final_state_with_features()
    state["tournament_matchups"][0].pop("iteration", None)
    run = store.create_run("CSC goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    matches = store.list_matches(run.id, db_path=isolated_db)
    assert [match["iteration"] for match in matches] == [0]


def _judged_matchup() -> dict[str, Any]:
    transcript = [
        {
            "turn": 1,
            "winner": "b",
            "winner_id": "e-b",
            "reasoning": ("Idea 2 names a measurable target. better idea: 2"),
            "presentation_order": "ab",
            "valid_output": True,
        },
        {
            "turn": 2,
            "winner": "b",
            "winner_id": "e-b",
            "reasoning": (
                "Presented the other way round it still holds. Better idea: 1"
            ),
            "presentation_order": "ba",
            "valid_output": True,
        },
    ]
    response: dict[str, Any] = {"decision_summary": "Idea 2 wins."}
    run = _DebateRun(
        base=_MatchupPrompt("", None, None, None),
        transcript=transcript,
        fallback="a",
        start_parity=0,
    )
    winner = _finalize_debate_response(response, ["b", "b"], run, "model")
    return {
        "hypothesis_a_id": "e-a",
        "hypothesis_b_id": "e-b",
        "winner_id": "e-b",
        "reasoning": "Idea 2 wins.",
        **_debate_provenance_fields(response, winner),
    }


def test_a_judged_debate_reaches_the_report(isolated_db: str) -> None:
    # Each debate turn may swap presentation numbers; persist one canonical
    # match verdict.
    run = store.create_run("cardiac fibrosis goal", "express", "engine", {})
    with store.transaction(isolated_db) as conn:
        _persist_engine_matches(
            run.id,
            [_judged_matchup()],
            {"e-a": "h1", "e-b": "h2"},
            conn,
        )

    [row] = store.list_matches(run.id, db_path=isolated_db)
    document = json.loads(row["debate_transcript"])
    assert document["verdict"] == "2"
    assert [turn["favored"] for turn in document["turns"]] == ["2", "2"]
    assert document["turns"][0]["text"] == "Idea 2 names a measurable target."
    assert document["turns"][1]["text"].endswith("it still holds.")

    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="cardiac fibrosis goal",
            provider="engine",
            top_hypotheses=[{"id": "h2", "title": "Empagliflozin"}],
            matches=store.list_matches(run.id, db_path=isolated_db),
            hypothesis_title_by_id={"h1": "NHE1 screen", "h2": "Empagliflozin"},
        )
    )

    assert "## Tournament debates" in markdown
    assert "### Debate 1: 1. NHE1 screen vs 2. Empagliflozin" in markdown
    assert (
        '**Turn 1 (favors idea 2; this turn\'s "Hypothesis 1" is idea 1):**'
        " Idea 2 names a measurable target." in markdown
    )
    # Swapped turn headers explain the numbering used by their own argument.
    assert (
        '**Turn 2 (favors idea 2; this turn\'s "Hypothesis 1" is idea 2):**'
        in markdown
    )
    assert markdown.rstrip().count("Better idea:") == 1
    assert "Better idea: 2" in markdown


def _review(novelty: float | None, overall: float) -> dict[str, Any]:
    scores: dict[str, Any] = {"scientific_soundness": 9}
    if novelty is not None:
        scores["novelty"] = novelty
    return {
        "scores": scores,
        "overall_score": overall,
        "review_summary": "s",
        "constructive_feedback": "c",
    }


def _state(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    # Overall score deliberately differs from novelty so incorrect column
    # mapping cannot pass by coincidence.
    return {
        "hypotheses": [
            _engine_hypothesis(
                "h-1", "A hypothesis.", score=9.0, reviews=reviews
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def _persisted_novelty(state: dict[str, Any], db_path: str) -> Any:
    run = store.create_run("novelty goal", "standard", "engine", {})
    _persist(run_id=run.id, final_state=state, db_path=db_path)
    rows = store.list_hypotheses(run.id, db_path=db_path)
    return rows[0]["novelty_score"]


def test_novelty_score_comes_from_the_reviewers_novelty_axis(
    isolated_db: str,
) -> None:
    novelty = _persisted_novelty(_state([_review(3.0, 9.0)]), isolated_db)
    assert novelty == 3.0


def test_novelty_score_averages_across_reviewers(isolated_db: str) -> None:
    state = _state([_review(2.0, 9.0), _review(4.0, 9.0)])
    assert _persisted_novelty(state, isolated_db) == 3.0


def test_novelty_score_is_unset_when_the_reviewer_omitted_it(
    isolated_db: str,
) -> None:
    state = _state([_review(None, 9.0)])
    assert _persisted_novelty(state, isolated_db) is None


def test_novelty_score_is_unset_when_nothing_reviewed_it(
    isolated_db: str,
) -> None:
    assert _persisted_novelty(_state([]), isolated_db) is None

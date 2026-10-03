"""Tests for engine drain 2."""

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

# Engine-drain tests for contextual safety-verdict escalation (J14).
#
# Covers the drain's wiring of ``hypothesis.safety.escalate_held_hypotheses``
# into ``engine_adapter.drain.persist_final_state``: a bulk engine-generated
# hypothesis the deterministic screen holds UNCERTAIN now gets the same
# contextual-escalation chance a scientist-authored hypothesis already had
# (``app.human_input``). These mirror the fail-closed cases already pinned in
# ``test_hypothesis_safety_escalation.py``, but exercised through the real
# drain -- persisted status, audit rows, and transaction boundaries included --
# rather than the escalation function in isolation.


# A control-arm hard-split item the deterministic layer holds as UNCERTAIN
# via the benign-context marker check ("triage"/"disaster"), carrying
# needs_context=True -- the only shape escalation acts on. Matches the
# fixture in test_hypothesis_safety_escalation.py.
_HELD_TEXT = (
    "Improving hospital triage protocols and resource allocation for "
    "mass casualty events such as natural disasters."
)


def _escalation_state(held_text: str = _HELD_TEXT) -> dict[str, Any]:
    """A final state with one benign hypothesis and one held UNCERTAIN one."""
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
    """A non-offline engine run: the default backend, eligible to escalate."""
    return store.create_run(goal, "standard", "engine", {})


def _fake_semantic_response(category: str) -> SimpleNamespace:
    """Build a minimal litellm response carrying one safety category."""
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
    """Make every hypothesis-stage escalation eligible to reach the model."""
    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online()


def _held_status(run_id: str, isolated_db: str) -> str:
    """Return the persisted safety_status of the run's held hypothesis."""
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
    """The real held-hypothesis escalation inherits campaign admission."""
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
    """A later whole-pool re-screen must not undo an escalation's raise.

    ``runs.contrib`` re-screens the whole pool whenever a scientist adds
    input. The deterministic layer alone would re-derive UNCERTAIN from
    ``held-1``'s unchanged text and, without ``_STICKY_STATUSES`` covering
    the escalation-raised outcome, silently clear the block back down.
    """

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

    # Simulate the scientist-input re-screen: same pool, re-screened.
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
    """A configured-but-unreachable model leaves the hold in place."""
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
    """A provider failure mid-call leaves the hold in place, not a block."""

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
    """An offline-backed run never reaches the model and still settles.

    No eligibility stubbing here: the run's own persisted ``llm_backend``
    is what ``_should_escalate_to_semantic`` reads, so this exercises the
    real offline gate, not a monkeypatched stand-in for it. The provider
    call is patched to raise if it is ever reached at all, since a real
    offline run must never attempt one.
    """

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

    # The drain settles cleanly -- the run is not left half-finalized.
    assert drained.safety_counts["screened"] == 2
    assert _held_status(run.id, isolated_db) == "uncertain"


def test_escalation_does_not_hold_the_write_lock(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    """A concurrent write succeeds while escalation is in flight.

    AGENTS.md: nothing may hold SQLite's write lock across network I/O.
    The model call is stalled deliberately; if the drain held the lock
    across it, the concurrent ``create_run`` below would block for the
    busy-timeout instead of returning immediately.
    """
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
        except BaseException as exc:  # surfaced via the assert below
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
    """The audit row must say what happened, not what usually happens.

    The audit recorder wrote a hardcoded ``decision="block"``, which was
    correct while resolution could only raise a verdict. Now that a Tier B
    hold can also be cleared, that hardcoded value would file a block row
    for a hypothesis the same pass published -- and the adjudication UI
    reads these rows, so it would show a reviewer a block that never
    happened.
    """
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
    """A PubMed article's canonical identity and passage are persisted.

    Neither ``doi``/``pmid`` nor ``passage_text``/``retrieved_at`` existed
    as evidence columns before G12: this pins that the drain now derives
    and stores all four rather than only title/abstract/url.
    """
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
    # created_at is the drain's own insert stamp; it must not collapse onto
    # the engine's earlier retrieval time.
    assert row["created_at"] != row["retrieved_at"]


def test_drain_derives_pmid_from_pubmed_url_without_source_id(
    isolated_db: str,
) -> None:
    """A PMID recoverable only from the URL is still persisted."""
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
    """Offline mode (the hermetic test default) never performs network I/O.

    A non-empty identifier/URL and no retraction flag reads ``available``;
    a retracted article, even with a URL, reads unavailable *and* carries
    its own ``retracted`` flag -- distinct from a plain "no identifier"
    article, which is unavailable but not retracted.
    """
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
    """Live mode's ``available`` reflects the resolver's verdict.

    A non-empty URL that the resolver reports unresolvable must persist
    as unavailable -- exactly the case the metadata-only heuristic could
    never represent, since ``bool(url)`` is true either way.
    """
    monkeypatch.setattr(settings, "evidence_resolver", "live")

    def fake_resolve_many(
        metas: list[CitationMetadata], *, resolver: Resolver
    ) -> list[Resolvability]:
        # Every request "has" a non-empty url/doi/pmid by construction, so a
        # metadata-only heuristic would call all of them available; the
        # live resolver instead reports the second as unresolvable.
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
    """Live mode persists ``retracted`` from both retraction sources.

    Neither reaches the resolver's verdict the same way: the drain's own
    metadata flag (``article["is_retracted"]``) is thread through the
    request tuple's fourth element into ``resolve_one``, which checks it
    before ever dereferencing anything; the live resolver's own
    ``retraction_set`` lookup finds the second article independently, with
    no metadata flag at all. Both must land as ``retracted=True`` *and*
    ``available=False`` -- the gate's decision is unchanged either way,
    only the extra fact is new.
    """
    monkeypatch.setattr(settings, "evidence_resolver", "live")

    def fake_resolve_many(
        metas: list[CitationMetadata], *, resolver: Resolver
    ) -> list[Resolvability]:
        # Echo the first request's own metadata flag (proves the drain's
        # own retraction flag actually reaches the resolver, rather than
        # being read off the article and discarded); force RETRACTED for the
        # second
        # regardless of its (False) metadata flag, standing in for the live
        # resolver's independent retraction_set match.
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
    """A row persisted before this column existed degrades safely.

    ``ALTER TABLE ... ADD COLUMN`` leaves every pre-existing row NULL; a
    run drained before this wave shipped has no way to know whether its
    unavailable evidence was retracted, so it must render exactly as it
    did before -- ``retracted=False``, ``available`` untouched.
    """
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
    """The hybrid retrieval score, rationale, and version land on the row."""
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
    """``evidence_passages`` reads the materialized column.

    Not a live reconstruction, so a span's offsets always index the
    exact stored text.
    """
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
    """Production computes availability through ``assess_resolvability``.

    The seam and its ``Resolver`` protocol used to exist beside the live
    path rather than underneath it: the drain called a differently-shaped
    resolver directly, and ``assess_resolvability`` was reachable only
    from its own unit test. A parity row citing a seam nothing production
    reaches reads as built when it is not, so this pins the wiring itself
    -- the seam is called once per article, with the protocol's own
    ``CitationMetadata`` (not a positional tuple), carrying the live
    resolver.
    """
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
    """The hermetic default differs only in which ``Resolver`` it passes."""
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
    """Source type is classified once, at the only point it is knowable.

    ``publication_type`` is an engine ``Article`` field the evidence table
    does not store, so a later reader cannot re-derive the distinction
    between a preprint indexed in PubMed and a peer-reviewed article from
    the same source. The drain therefore resolves it and persists the
    verdict alongside availability and retraction.
    """
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


# Drain persistence of the proposer's own safety assessment (MO-10).
#
# Split out of ``test_engine_drain.py`` to keep that module within the size
# cap once this test was added alongside the module's existing MO-6
# (scene-setting) test. Safety and toxicity is distinct from a reviewer's
# safety_ethical_concerns and never consulted by the safety gate.


def test_persist_writes_safety_and_toxicity_onto_the_hypothesis_row(
    isolated_db: str,
) -> None:
    """The proposer's own safety assessment (MO-10) reaches the row.

    Distinct from a reviewer's safety_ethical_concerns: this is the
    proposal's own field, and must never be consulted by the safety gate.
    """
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
    """An LLM-authored title is preferred over the derived one."""
    title = _authored_title(
        {"title": "CXCR1 Blockade Against Breast Cancer Stem Cells"},
        _STATEMENT,
    )
    assert title == "CXCR1 Blockade Against Breast Cancer Stem Cells"


def test_authored_title_falls_back_when_field_absent() -> None:
    """A payload with no title key falls back exactly as it did before."""
    assert _authored_title({}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )


def test_authored_title_falls_back_when_field_is_malformed() -> None:
    """A non-string title (a json_object-downgrade artifact) degrades safely."""
    assert _authored_title({"title": ["not", "a", "string"]}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )
    assert _authored_title({"title": 42}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )


def test_authored_title_falls_back_when_field_is_blank() -> None:
    """An empty or whitespace-only title falls back rather than persisting."""
    assert _authored_title({"title": ""}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )
    assert _authored_title({"title": "   \n\t"}, _STATEMENT) == (
        "Blocking CXCR1 suppresses breast cancer stem cells"
    )


def test_authored_title_is_clipped_past_the_display_cap() -> None:
    """A title over the cap is clipped, not discarded back to the fallback."""
    long_title = "A" * 150
    title = _authored_title({"title": long_title}, _STATEMENT)
    assert title == "A" * 120
    assert len(title) == 120


def test_persist_writes_the_authored_title_onto_the_hypothesis_row(
    isolated_db: str,
) -> None:
    """The authored title (not first_sentence) reaches the store row."""
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
    """An evolved child with no authored title falls back to its own text.

    Not the parent's title: the child's mechanism may have diverged, so
    first_sentence(child.text) is the right fallback, never the parent's
    (possibly stale) title.
    """
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
                # No authored title on this response -- json_object
                # downgrade, or the evolution LLM simply omitted it.
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


# Drain tests for the pre-tournament per-hypothesis safety screen.
#
# Split out of ``test_engine_drain_safety.py`` when that file passed the
# module-size budget. This module covers the screen that runs inside the
# drain itself -- persisting each hypothesis's ``safety_status`` and, for a
# held UNCERTAIN idea, a reviewable ``hold`` decision -- before the report is
# ever built. The rank-and-publish split and the persisted-status gate that
# decide what a *drained* idea may publish stay in
# ``test_engine_drain_safety.py``.


def _screening_hypothesis(hyp_id: str, text: str) -> dict[str, Any]:
    """A minimal engine hypothesis carrying every field the drain reads."""
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
    """A final state with one safe and one unsafe hypothesis to screen."""
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
    """The drain persists each hypothesis's safety_status and blocks unsafe.

    Milestone 6/M9: the per-hypothesis safety screen runs inside the drain
    (before the report is built), so an unsafe hypothesis is marked and audited
    at persistence time -- not only filtered out later at report synthesis.
    """
    run = store.create_run("safety goal", "standard", "engine", {})
    state = _screening_state()

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    # safety_status is persisted for every hypothesis by the drain itself.
    by_text = {h["statement"][:8]: h for h in store.list_hypotheses(run.id)}
    assert by_text["Inhibiti"]["safety_status"] == "allow"
    assert by_text["Weaponiz"]["safety_status"] == "prohibited"

    # A blocking audit row was recorded during the drain (pre-finalize).
    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert any(
        d["stage"] == "hypothesis" and d["decision"] == "block"
        for d in decisions
    )


def test_drain_persists_held_hypotheses_as_reviewable_decisions(
    isolated_db: str,
) -> None:
    """Held UNCERTAIN hypotheses survive the drain as adjudicable decisions.

    The engine's safety screen holds UNCERTAIN hypotheses out of the pool in
    ``held_for_review``; the drain must persist each one as a ``hold``
    decision at the hypothesis stage, carrying the screen's rationale and
    enough of the idea to display -- otherwise the hold vanishes at the app
    boundary and no person can ever inspect or adjudicate it.
    """
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
        # The shape the adjudication path requires: a reviewable decision
        # that no resolution has touched yet.
        assert row["stage"] == "hypothesis"
        assert row["requires_review"] is True
        assert row["resolution"] is None
        assert row["policy_version"] == "coscientist-safety-v5"
        assert row["matches"] == ["for research purposes only"]
        # Identity + rationale: the engine's reason and the held idea's text.
        assert "uncertain" in row["reason"]
        assert "obfuscated intent" in row["reason"]
    reasons = " ".join(row["reason"] for row in holds)
    assert "held-1" in reasons and "held-2" in reasons
    assert "enhance pathogen transmissibility" in reasons
    assert "toxin production line" in reasons
    # The held ideas never got hypothesis rows -- the engine kept them out
    # of the pool -- so the decision row is the only record of them.
    assert [h["id"] for h in store.list_hypotheses(run.id)] == ["safe-1"]


def test_drain_records_a_hold_without_an_engine_audit_entry(
    isolated_db: str,
) -> None:
    """A held entry whose audit entry is missing still gets a hold row.

    The engine writes ``held_for_review`` and ``safety_decisions`` in the
    same node, but the drain must not depend on the join succeeding: a held
    hypothesis with no matching audit entry records a hold with a fallback
    rationale rather than being dropped.
    """
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


# Drain persistence of multi-parent (combination) lineage.
#
# Split out of ``test_engine_drain.py`` to keep that module within the size
# cap. Covers the ``parent_ids`` JSON column: a combination child stores
# every parent with the primary leading, and a pruned co-parent degrades
# the stored lineage to the surviving primary parent.


def _multi_parent_state() -> dict[str, Any]:
    """A final state with a two-parent combination child."""
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
    """A combination child stores every parent, primary leading."""
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
    # Single-parent rows carry no multi-parent list.
    assert hyps["parent-1"]["parent_ids"] is None
    assert hyps["parent-2"]["parent_ids"] is None


def test_drain_drops_pruned_co_parent_from_lineage(isolated_db: str) -> None:
    """A co-parent pruned before the drain leaves a single-parent child.

    The primary parent survives but the combination partner was archived, so
    the stored lineage degrades to the one remaining parent (parent_id alone)
    rather than persisting a dangling id in the JSON list.
    """
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
    """The drain carries each hypothesis's authoring cycle to the store.

    ``creation_iteration`` is the engine's authoring-cycle ordinal (0 for the
    initial generation, N for a later research-expansion/evolution cycle); the
    temporal-scaling eval reads it as the run's timeline axis
    (``EVAL-SCALING-001``). A hypothesis whose engine payload omits it (a
    legacy row) persists as NULL rather than 0, so the eval falls back to
    ``generation`` rather than treating it as the initial cycle.
    """
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


# Tournament-match persistence in the final-state drain.
#
# Covers ``engine_adapter.drain.matches``: the columns a judged matchup
# carries into its ``matches`` row. Id resolution and the unresolved-side
# skip live in ``test_engine_drain.py``; this module holds the cycle the
# match was judged in, which the drain used to discard.


def test_persist_match_records_the_iteration_it_was_judged_in(
    isolated_db: str,
) -> None:
    """The matchup's own iteration reaches the row, not a hardcoded zero.

    The drain wrote ``iteration=0`` for every match on every run. Production
    extended run bc77950f judged its 23 matches across three iterations and
    stored all of them as iteration 0, so the persisted Elo history could
    not be read back by cycle.
    """
    state = _final_state_with_features()
    state["tournament_matchups"][0]["iteration"] = 2
    run = store.create_run("CSC goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    matches = store.list_matches(run.id, db_path=isolated_db)
    assert [match["iteration"] for match in matches] == [2]


def test_persist_match_without_an_iteration_falls_back_to_zero(
    isolated_db: str,
) -> None:
    """A matchup judged before the field existed still persists.

    Checkpoints written by an earlier build carry no ``iteration`` on their
    matchups, and a resumed run drains them alongside newly judged ones.
    """
    state = _final_state_with_features()
    state["tournament_matchups"][0].pop("iteration", None)
    run = store.create_run("CSC goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    matches = store.list_matches(run.id, db_path=isolated_db)
    assert [match["iteration"] for match in matches] == [0]


def _judged_matchup() -> dict[str, Any]:
    """A matchup detail as the ranking node emits it after a real debate."""
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
    """The turns survive persistence and render in the published shape.

    Turn 2 was judged with the ideas presented in reverse, so its own
    trailing "Better idea: 1" names the same idea turn 1 called 2. The
    stored document keeps one verdict for the match and neither turn's
    contradictory line.
    """
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
    # Turn 2 was judged the other way round: its own text calls idea 2
    # "Hypothesis 1", and the header says so rather than leaving the
    # reader to read two turns as contradicting each other.
    assert (
        '**Turn 2 (favors idea 2; this turn\'s "Hypothesis 1" is idea 2):**'
        in markdown
    )
    # Published artifact (Figure A.17, paper line 1122) prints it capitalized.
    assert markdown.rstrip().count("Better idea:") == 1
    assert "Better idea: 2" in markdown


# Drain persistence of ``hypothesis_state.novelty_score`` (finding K10).
#
# The column used to be filled from the engine's *overall* score, so it
# held a different quantity than its name promised. It now carries the
# reviewers' own novelty axis.


def _review(novelty: float | None, overall: float) -> dict[str, Any]:
    """One engine review scoring novelty apart from its overall score."""
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
    """A final state whose single hypothesis carries ``reviews``.

    ``score`` is deliberately far from every novelty score so a test
    asserting the persisted value cannot pass on the old behavior by
    coincidence.
    """
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
    """Drain ``state`` and return the stored novelty score."""
    run = store.create_run("novelty goal", "standard", "engine", {})
    _persist(run_id=run.id, final_state=state, db_path=db_path)
    rows = store.list_hypotheses(run.id, db_path=db_path)
    return rows[0]["novelty_score"]


def test_novelty_score_comes_from_the_reviewers_novelty_axis(
    isolated_db: str,
) -> None:
    """The stored value is the review novelty, not the overall score."""
    novelty = _persisted_novelty(_state([_review(3.0, 9.0)]), isolated_db)
    assert novelty == 3.0


def test_novelty_score_averages_across_reviewers(isolated_db: str) -> None:
    """Several reviewers average, so one outlier cannot define the value."""
    state = _state([_review(2.0, 9.0), _review(4.0, 9.0)])
    assert _persisted_novelty(state, isolated_db) == 3.0


def test_novelty_score_is_unset_when_the_reviewer_omitted_it(
    isolated_db: str,
) -> None:
    """A review without a novelty axis stores nothing.

    The old behavior wrote the overall score here, which is exactly the
    case where a reader would most wrongly trust the column name.
    """
    state = _state([_review(None, 9.0)])
    assert _persisted_novelty(state, isolated_db) is None


def test_novelty_score_is_unset_when_nothing_reviewed_it(
    isolated_db: str,
) -> None:
    """An unreviewed hypothesis stores nothing rather than its score."""
    assert _persisted_novelty(_state([]), isolated_db) is None

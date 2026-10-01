"""Tests for evidence identity/availability persistence (fidelity-audit G12).

Covers what the drain now writes onto each evidence row beyond title/
abstract: canonical DOI/PMID identity, the exact stored passage a claim
span indexes, a retrieval timestamp distinct from the insert stamp, and an
``available`` flag derived from a real (if offline-stubbed) resolution
rather than a bare "is the URL string non-empty" check.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from app import citation_metadata, citation_resolver, store
from app.citation_metadata import (
    CitationMetadata,
    Resolvability,
    Resolver,
    offline_resolver,
)
from app.config import settings
from app.engine_adapter.drain import (
    evidence_resolution as drain_evidence_resolution,
)
from tests._drain_helpers import _persist_and_finalize


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
        drain_evidence_resolution.citation_resolver,
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
        drain_evidence_resolution.citation_resolver,
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
    from app.claim_grounding import evidence_passages

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

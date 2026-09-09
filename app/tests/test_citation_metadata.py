"""Citation metadata and resolvability, judged apart from claim support.

Covers the four facts the metadata check owns -- retraction, availability,
source type, and publication date -- and the property that makes it a
*separate* check: a source's resolvability verdict never consults whether
the source supports the claim citing it.
"""

from __future__ import annotations

import pytest

from app.citation_metadata import (
    CitationMetadata,
    DateState,
    Resolvability,
    SourceType,
    assess_resolvability,
    classify_date,
    classify_source_type,
    offline_resolver,
)
from app.citations import CitationRecord, CitationState, classify_citation

# --- Resolvability: retraction and availability ------------------------------


def test_retraction_dominates_a_reachable_source() -> None:
    """A retracted source is unusable even though it still resolves."""
    meta = CitationMetadata(url="https://x/1", doi="10.1/a", retracted=True)
    assert assess_resolvability(meta) is Resolvability.RETRACTED


def test_offline_resolver_accepts_a_bare_identifier_without_a_url() -> None:
    """A DOI or PMID is an identifier; it resolves without a URL string.

    The pre-convergence ``offline_resolver`` required a non-empty
    ``meta.url``, while the drain's own metadata heuristic accepted a bare
    DOI or PMID. Converging on the stricter of the two would have
    reclassified every doi/pmid-only citation from available to
    unresolvable -- a gate-decision change -- so the seam takes the
    heuristic's rule.
    """
    assert (
        offline_resolver(CitationMetadata(doi="10.1/a"))
        is Resolvability.RESOLVABLE
    )
    assert (
        offline_resolver(CitationMetadata(pmid="12345678"))
        is Resolvability.RESOLVABLE
    )
    assert offline_resolver(CitationMetadata()) is Resolvability.UNRESOLVABLE


def test_resolvability_uses_the_swappable_resolver() -> None:
    """The injected resolver decides, not the supplied metadata."""

    def _live_resolver(meta: CitationMetadata) -> Resolvability:
        assert meta.doi == "10.1/abc"
        return Resolvability.RETRACTED

    verdict = assess_resolvability(
        CitationMetadata(url="https://x/1", doi="10.1/abc"),
        resolver=_live_resolver,
    )
    assert verdict is Resolvability.RETRACTED


def test_resolvability_is_independent_of_claim_support() -> None:
    """A verbatim-supported claim citing a retracted source is still flagged.

    The abstract literally contains the claim, so every support signal is
    at its maximum -- and the metadata verdict is unmoved, because it never
    reads the claim at all. The citation label the reader sees follows the
    metadata verdict, not the support.
    """
    claim = "Kinase X phosphorylates substrate Y in cardiac tissue."
    meta = CitationMetadata(url="https://x/1", doi="10.1/a", retracted=True)
    assert assess_resolvability(meta) is Resolvability.RETRACTED

    record = CitationRecord(
        url=meta.url,
        abstract=claim,
        claim=claim,
        available=assess_resolvability(meta) is Resolvability.RESOLVABLE,
    )
    assert classify_citation(record) is CitationState.UNAVAILABLE


# --- Source type -------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("pubmed", SourceType.PEER_REVIEWED),
        ("europepmc", SourceType.PEER_REVIEWED),
        ("openalex", SourceType.PEER_REVIEWED),
        ("arxiv", SourceType.PREPRINT),
        ("biorxiv", SourceType.PREPRINT),
        ("preprints", SourceType.PREPRINT),
        ("scientific_database", SourceType.DATABASE),
        ("web", SourceType.WEB),
        ("attachment", SourceType.DOCUMENT),
        ("engine", SourceType.UNKNOWN),
        ("", SourceType.UNKNOWN),
    ],
)
def test_source_type_from_the_retrieval_source_name(
    source: str, expected: SourceType
) -> None:
    """Every source name a run can actually persist classifies."""
    assert classify_source_type(CitationMetadata(source=source)) is expected


def test_publisher_declared_type_outranks_the_retrieval_source() -> None:
    """A preprint indexed in PubMed is a preprint, not a journal article.

    The retrieval source says ``pubmed``, which alone would read as peer
    reviewed; PubMed's own declared publication type says otherwise and
    must win, or the strongest available signal is the one discarded.
    """
    meta = CitationMetadata(source="pubmed", publication_type="Preprint")
    assert classify_source_type(meta) is SourceType.PREPRINT

    journal = CitationMetadata(source="", publication_type="Journal Article")
    assert classify_source_type(journal) is SourceType.PEER_REVIEWED


def test_preprint_host_classifies_an_otherwise_unknown_source() -> None:
    """A preprint URL is recognized when neither other signal is present."""
    meta = CitationMetadata(
        source="unknown", url="https://www.biorxiv.org/content/10.1101/1v1"
    )
    assert classify_source_type(meta) is SourceType.PREPRINT


# --- Publication date --------------------------------------------------------


def test_date_states_cover_missing_present_and_implausible() -> None:
    """A date is present, absent, or outside the range a paper can hold."""
    assert (
        classify_date(CitationMetadata(year=2024), today_year=2026)
        is DateState.PRESENT
    )
    assert (
        classify_date(CitationMetadata(year=None), today_year=2026)
        is DateState.MISSING
    )
    assert (
        classify_date(CitationMetadata(year=3025), today_year=2026)
        is DateState.IMPLAUSIBLE
    )
    assert (
        classify_date(CitationMetadata(year=1500), today_year=2026)
        is DateState.IMPLAUSIBLE
    )


def test_next_year_is_plausible_for_an_in_press_paper() -> None:
    """An accepted paper carries its forthcoming issue's year, not today's."""
    assert (
        classify_date(CitationMetadata(year=2027), today_year=2026)
        is DateState.PRESENT
    )

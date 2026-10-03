from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import app.citations as citation_resolver
from app import retraction_set
from app.citations import (
    ALL_STATES,
    CitationMetadata,
    CitationRecord,
    CitationState,
    DateState,
    Resolvability,
    SourceType,
    _token_overlap,
    assess_resolvability,
    classify_citation,
    classify_date,
    classify_source_type,
    offline_resolver,
)

# Metadata resolvability and claim support are independent judgments.


def test_retraction_dominates_a_reachable_source() -> None:
    meta = CitationMetadata(url="https://x/1", doi="10.1/a", retracted=True)
    assert assess_resolvability(meta) is Resolvability.RETRACTED


def test_offline_resolver_accepts_a_bare_identifier_without_a_url() -> None:
    # DOI and PMID resolve as identifiers without a URL; requiring URLs would
    # change availability gates.
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

    def _live_resolver(meta: CitationMetadata) -> Resolvability:
        assert meta.doi == "10.1/abc"
        return Resolvability.RETRACTED

    verdict = assess_resolvability(
        CitationMetadata(url="https://x/1", doi="10.1/abc"),
        resolver=_live_resolver,
    )
    assert verdict is Resolvability.RETRACTED


def test_resolvability_is_independent_of_claim_support() -> None:
    # Retraction metadata dominates even verbatim claim support; resolvability
    # never consults entailment.
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
    assert classify_source_type(CitationMetadata(source=source)) is expected


def test_publisher_declared_type_outranks_the_retrieval_source() -> None:
    # PubMed indexes preprints too; declared publication type must outrank
    # retrieval-source assumptions.
    meta = CitationMetadata(source="pubmed", publication_type="Preprint")
    assert classify_source_type(meta) is SourceType.PREPRINT

    journal = CitationMetadata(source="", publication_type="Journal Article")
    assert classify_source_type(journal) is SourceType.PEER_REVIEWED


def test_preprint_host_classifies_an_otherwise_unknown_source() -> None:
    meta = CitationMetadata(
        source="unknown", url="https://www.biorxiv.org/content/10.1101/1v1"
    )
    assert classify_source_type(meta) is SourceType.PREPRINT


def test_date_states_cover_missing_present_and_implausible() -> None:
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
    assert (
        classify_date(CitationMetadata(year=2027), today_year=2026)
        is DateState.PRESENT
    )


def _recording_reachable(calls: list[str], *, result: bool = True) -> object:

    def _stub(client: httpx.Client, url: str) -> bool:
        calls.append(url)
        return result

    return _stub


def _recording_pmid_found(calls: list[str], *, result: bool = True) -> object:

    def _stub(client: httpx.Client, pmid: str) -> bool:
        calls.append(pmid)
        return result

    return _stub


def test_retracted_short_circuits_without_a_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(calls)
    )
    monkeypatch.setattr(
        citation_resolver, "_pmid_found", _recording_pmid_found(calls)
    )

    verdict = citation_resolver.resolve_one(
        doi="10.1000/dead",
        pmid="999",
        url="https://example.org/dead",
        retracted=True,
    )

    assert verdict is Resolvability.RETRACTED
    assert calls == []


def test_no_identifier_is_unresolvable_without_a_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(calls)
    )

    verdict = citation_resolver.resolve_one(
        doi="", pmid="", url="", retracted=False
    )

    assert verdict is Resolvability.UNRESOLVABLE
    assert calls == []


def test_doi_is_preferred_over_pmid_and_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(seen)
    )
    monkeypatch.setattr(
        citation_resolver, "_pmid_found", _recording_pmid_found(seen)
    )

    citation_resolver.resolve_one(
        doi="10.1000/xyz",
        pmid="12345",
        url="https://example.org/other",
        retracted=False,
    )

    assert seen == ["https://doi.org/10.1000/xyz"]


def test_pmid_is_preferred_over_a_bare_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pmid_calls: list[str] = []
    url_calls: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_pmid_found", _recording_pmid_found(pmid_calls)
    )
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(url_calls)
    )

    verdict = citation_resolver.resolve_one(
        doi="", pmid="12345", url="https://example.org/other", retracted=False
    )

    assert verdict is Resolvability.RESOLVABLE
    assert pmid_calls == ["12345"]
    assert url_calls == []


def test_bare_url_is_checked_when_no_identifier_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(seen)
    )

    citation_resolver.resolve_one(
        doi="", pmid="", url="https://example.org/paper", retracted=False
    )

    assert seen == ["https://example.org/paper"]


def test_reachable_and_unreachable_land_differently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        citation_resolver, "_reachable", lambda client, url: True
    )
    assert (
        citation_resolver.resolve_one(
            doi="10.1000/live", pmid="", url="", retracted=False
        )
        is Resolvability.RESOLVABLE
    )

    monkeypatch.setattr(
        citation_resolver, "_reachable", lambda client, url: False
    )
    assert (
        citation_resolver.resolve_one(
            doi="10.1000/dead-but-well-formed", pmid="", url="", retracted=False
        )
        is Resolvability.UNRESOLVABLE
    )


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeEsummaryClient:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self._status_code = status_code
        self._payload = payload
        self.requested_params: dict[str, Any] | None = None

    def get(self, url: str, params: dict[str, Any]) -> _FakeResponse:
        self.requested_params = params
        return _FakeResponse(self._status_code, self._payload)


def test_pmid_found_true_for_a_record_without_an_error_field() -> None:
    client = _FakeEsummaryClient(
        200,
        {"result": {"uids": ["23851394"], "23851394": {"uid": "23851394"}}},
    )

    assert citation_resolver._pmid_found(client, "23851394") is True  # type: ignore[arg-type]
    assert client.requested_params == {
        "db": "pubmed",
        "id": "23851394",
        "retmode": "json",
    }


def test_pmid_found_false_for_an_error_record() -> None:
    client = _FakeEsummaryClient(
        200,
        {
            "result": {
                "uids": ["999999999999"],
                "999999999999": {
                    "uid": "999999999999",
                    "error": "cannot get document summary",
                },
            }
        },
    )

    assert citation_resolver._pmid_found(client, "999999999999") is False  # type: ignore[arg-type]


def test_pmid_found_false_on_http_error() -> None:
    class _RaisingClient:
        def get(self, url: str, params: dict[str, Any]) -> _FakeResponse:
            raise httpx.ConnectError("no route")

    assert citation_resolver._pmid_found(_RaisingClient(), "1") is False  # type: ignore[arg-type]


def test_pmid_found_false_on_malformed_json() -> None:
    class _BadJsonResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            raise json.JSONDecodeError("bad", "doc", 0)

    class _BadJsonClient:
        def get(self, url: str, params: dict[str, Any]) -> _BadJsonResponse:
            return _BadJsonResponse()

    assert citation_resolver._pmid_found(_BadJsonClient(), "1") is False  # type: ignore[arg-type]


def test_resolve_many_preserves_input_order() -> None:
    results = citation_resolver.resolve_many(
        [
            CitationMetadata(url="https://a"),
            CitationMetadata(url="https://b", retracted=True),
            CitationMetadata(url="https://c"),
        ],
        resolver=offline_resolver,
    )

    assert results == [
        Resolvability.RESOLVABLE,
        Resolvability.RETRACTED,
        Resolvability.RESOLVABLE,
    ]


def test_resolve_many_routes_every_verdict_through_the_seam() -> None:
    seen: list[CitationMetadata] = []

    def recording_resolver(meta: CitationMetadata) -> Resolvability:
        seen.append(meta)
        return Resolvability.UNRESOLVABLE

    metas = [CitationMetadata(doi="10.1/a"), CitationMetadata(pmid="7")]
    results = citation_resolver.resolve_many(metas, resolver=recording_resolver)

    assert results == [Resolvability.UNRESOLVABLE] * 2
    assert sorted(m.doi + m.pmid for m in seen) == ["10.1/a", "7"]


def test_live_resolver_is_the_production_resolver_implementation() -> None:
    meta = CitationMetadata(url="https://x", doi="", pmid="", retracted=True)
    assert citation_resolver.live_resolver(meta) is Resolvability.RETRACTED


def test_resolve_many_empty_input_makes_no_calls() -> None:
    assert citation_resolver.resolve_many([], resolver=offline_resolver) == []


def test_offline_retracted_doi_short_circuits_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        retraction_set,
        "is_known_retracted",
        lambda doi: doi == "10.1000/offline-flagged",
    )
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(calls)
    )

    verdict = citation_resolver.resolve_one(
        doi="10.1000/offline-flagged", pmid="", url="", retracted=False
    )

    assert verdict is Resolvability.RETRACTED
    assert calls == []


def test_doi_absent_from_offline_set_still_resolves_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retraction_set,
        "is_known_retracted",
        lambda doi: False,
    )
    monkeypatch.setattr(
        citation_resolver, "_reachable", lambda client, url: True
    )

    verdict = citation_resolver.resolve_one(
        doi="10.1000/clean", pmid="", url="", retracted=False
    )

    assert verdict is Resolvability.RESOLVABLE


def test_source_flagged_retraction_never_consults_the_offline_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    def _fail_if_called(doi: str) -> bool:
        raise AssertionError("offline retraction set consulted needlessly")

    monkeypatch.setattr(retraction_set, "is_known_retracted", _fail_if_called)

    verdict = citation_resolver.resolve_one(
        doi="10.1000/already-flagged", pmid="", url="", retracted=True
    )

    assert verdict is Resolvability.RETRACTED


def test_states_are_exactly_four() -> None:
    assert set(ALL_STATES) == {
        "verified",
        "partial",
        "unsupported",
        "unavailable",
    }


@pytest.mark.parametrize(
    ("url", "abstract", "claim", "available", "expected"),
    [
        ("", "anything", "anything", True, "unavailable"),
        ("https://example.org", "anything", "anything", False, "unavailable"),
        (
            "https://example.org/1",
            "mitochondrial biogenesis brown adipose thermogenesis "
            "cold response",
            "mitochondrial biogenesis brown adipose thermogenesis "
            "cold response",
            True,
            "verified",
        ),
        (
            "https://example.org/1",
            "this paper studies algebraic topology and category theory",
            "protein folding kinetics in chaperonin complexes",
            True,
            "unsupported",
        ),
    ],
    ids=[
        "unavailable_when_no_url",
        "unavailable_when_flag_false",
        "verified_when_strong_overlap",
        "unsupported_when_no_overlap",
    ],
)
def test_classify_citation(
    url: str, abstract: str, claim: str, available: bool, expected: str
) -> None:
    r = CitationRecord(
        url=url, abstract=abstract, claim=claim, available=available
    )
    assert classify_citation(r) == expected


def test_partial_when_source_states_some_of_the_claim() -> None:
    r = CitationRecord(
        url="https://example.org/1",
        abstract="mitochondrial biogenesis rises during brown adipose "
        "thermogenesis in a poorly understood pathway",
        claim="mitochondrial biogenesis drives thermogenesis through "
        "uncoupling protein induction",
    )
    assert classify_citation(r) == "partial"


# Union overlap penalizes unrelated abstract length; claim coverage preserves
# literal support on long sources.
_ABSTRACT_BODY = (
    "Background: glioblastoma remains the most aggressive primary brain "
    "tumour, with median survival under fifteen months despite maximal "
    "resection, radiotherapy and temozolomide. Methods: three "
    "patient-derived stem cell lines were treated across a concentration "
    "range and assayed for viability and colony formation. Results: "
    "viability fell dose-dependently while normal astrocytes were spared. "
    "Conclusions: further preclinical evaluation is warranted."
)

_CLAIM = (
    "empagliflozin suppresses proliferation of patient-derived "
    "glioblastoma stem cells by elevating beta-hydroxybutyrate"
)


@pytest.mark.parametrize(
    "abstract",
    [
        f"{_CLAIM}. {_ABSTRACT_BODY}",
        "empagliflozin suppresses proliferation of glioblastoma stem "
        f"cells as beta-hydroxybutyrate rises. {_ABSTRACT_BODY}",
    ],
    ids=["verbatim_claim", "paraphrased_claim"],
)
def test_abstract_length_does_not_suppress_support(abstract: str) -> None:
    r = CitationRecord(
        url="https://example.org/1", abstract=abstract, claim=_CLAIM
    )
    assert classify_citation(r) == "verified"


def test_stating_the_claim_outscores_sharing_its_subject() -> None:
    # Lexical overlap cannot distinguish subject from assertion; actual support
    # must outrank mere topical similarity.
    subject_only = _token_overlap(_CLAIM, _ABSTRACT_BODY)
    stated = _token_overlap(_CLAIM, f"{_CLAIM}. {_ABSTRACT_BODY}")
    assert stated > subject_only
    assert subject_only < 0.60


def _write_gz(tmp_path: Path, dois: list[str]) -> Path:
    path = tmp_path / "retractions.txt.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(dois) + "\n")
    return path


def test_doi_in_the_set_is_known_retracted(tmp_path: Path) -> None:
    path = _write_gz(tmp_path, ["10.1000/known-bad"])

    assert retraction_set.is_known_retracted("10.1000/known-bad", path=path)


def test_doi_not_in_the_set_is_not_retracted(tmp_path: Path) -> None:
    path = _write_gz(tmp_path, ["10.1000/known-bad"])

    assert not retraction_set.is_known_retracted(
        "10.1000/perfectly-fine", path=path
    )


def test_missing_data_file_degrades_to_empty_set(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "does-not-exist.txt.gz"

    with caplog.at_level("WARNING"):
        result = retraction_set.is_known_retracted("10.1000/x", path=path)

    assert result is False
    assert "retraction" in caplog.text.lower()


def test_doi_url_prefix_matches_a_bare_entry(tmp_path: Path) -> None:
    path = _write_gz(tmp_path, ["10.1000/known-bad"])

    assert retraction_set.is_known_retracted(
        "https://doi.org/10.1000/KNOWN-BAD", path=path
    )


def test_the_shipped_data_file_loads_and_is_non_empty() -> None:
    doi_set = retraction_set._load_doi_set(
        retraction_set.DEFAULT_RETRACTIONS_PATH
    )

    assert len(doi_set) > 0

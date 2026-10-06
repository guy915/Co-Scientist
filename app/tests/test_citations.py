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
    CitationMetadata,
    CitationRecord,
    CitationState,
    DateState,
    Resolvability,
    SourceType,
    assess_resolvability,
    classify_citation,
    classify_date,
    classify_source_type,
    offline_resolver,
)

# Metadata resolvability and claim support are independent judgments.


def test_retraction_dominates_a_reachable_source_and_claim_support() -> None:
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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("pubmed", SourceType.PEER_REVIEWED),
        ("europepmc", SourceType.PEER_REVIEWED),
        ("arxiv", SourceType.PREPRINT),
        ("biorxiv", SourceType.PREPRINT),
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


def test_declared_type_and_preprint_host_outrank_the_retrieval_source() -> None:
    # PubMed indexes preprints too.
    declared = CitationMetadata(source="pubmed", publication_type="Preprint")
    journal = CitationMetadata(source="", publication_type="Journal Article")
    host = CitationMetadata(
        source="unknown", url="https://www.biorxiv.org/content/10.1101/1v1"
    )

    assert classify_source_type(declared) is SourceType.PREPRINT
    assert classify_source_type(journal) is SourceType.PEER_REVIEWED
    assert classify_source_type(host) is SourceType.PREPRINT


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2024, DateState.PRESENT),
        (2027, DateState.PRESENT),
        (None, DateState.MISSING),
        (3025, DateState.IMPLAUSIBLE),
        (1500, DateState.IMPLAUSIBLE),
    ],
)
def test_date_states_cover_missing_present_and_implausible(
    year: int | None, expected: DateState
) -> None:
    meta = CitationMetadata(year=year)

    assert classify_date(meta, today_year=2026) is expected


@pytest.mark.parametrize(
    ("kwargs", "expected", "calls"),
    [
        (
            {
                "doi": "10.1/x",
                "pmid": "9",
                "url": "https://x",
                "retracted": True,
            },
            Resolvability.RETRACTED,
            [],
        ),
        ({}, Resolvability.UNRESOLVABLE, []),
        (
            {"doi": "10.1000/xyz", "pmid": "12345", "url": "https://other"},
            Resolvability.RESOLVABLE,
            ["https://doi.org/10.1000/xyz"],
        ),
        (
            {"pmid": "12345", "url": "https://other"},
            Resolvability.RESOLVABLE,
            ["pmid:12345"],
        ),
        (
            {"url": "https://example.org/paper"},
            Resolvability.RESOLVABLE,
            ["https://example.org/paper"],
        ),
    ],
    ids=["retracted", "no-identifier", "doi-first", "pmid-before-url", "url"],
)
def test_resolution_prefers_doi_then_pmid_then_url_without_needless_calls(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    expected: Resolvability,
    calls: list[str],
) -> None:
    seen: list[str] = []

    def reachable(client: httpx.Client, url: str) -> bool:
        seen.append(url)
        return True

    def pmid_found(client: httpx.Client, pmid: str) -> bool:
        seen.append(f"pmid:{pmid}")
        return True

    monkeypatch.setattr(citation_resolver, "_reachable", reachable)
    monkeypatch.setattr(citation_resolver, "_pmid_found", pmid_found)
    args = {"doi": "", "pmid": "", "url": "", "retracted": False} | kwargs

    assert citation_resolver.resolve_one(**args) is expected
    assert seen == calls


def test_an_unreachable_well_formed_doi_is_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        citation_resolver, "_reachable", lambda client, url: False
    )

    verdict = citation_resolver.resolve_one(
        doi="10.1000/dead", pmid="", url="", retracted=False
    )

    assert verdict is Resolvability.UNRESOLVABLE


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _RaisingClient:
    def get(self, url: str, params: dict[str, Any]) -> _FakeResponse:
        raise httpx.ConnectError("no route")


class _BadJsonResponse:
    status_code = 200

    def json(self) -> dict[str, Any]:
        raise json.JSONDecodeError("bad", "doc", 0)


class _BadJsonClient:
    def get(self, url: str, params: dict[str, Any]) -> _BadJsonResponse:
        return _BadJsonResponse()


class _FakeEsummaryClient:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self._status_code = status_code
        self._payload = payload
        self.requested_params: dict[str, Any] | None = None

    def get(self, url: str, params: dict[str, Any]) -> _FakeResponse:
        self.requested_params = params
        return _FakeResponse(self._status_code, self._payload)


@pytest.mark.parametrize(
    ("client", "expected"),
    [
        (
            _FakeEsummaryClient(
                200, {"result": {"uids": ["1"], "1": {"uid": "1"}}}
            ),
            True,
        ),
        (
            _FakeEsummaryClient(
                200,
                {"result": {"uids": ["1"], "1": {"error": "cannot get doc"}}},
            ),
            False,
        ),
        (_RaisingClient(), False),
        (_BadJsonClient(), False),
    ],
    ids=["found", "error-record", "http-error", "malformed-json"],
)
def test_pmid_found_only_for_a_record_without_an_error(
    client: Any, expected: bool
) -> None:
    assert citation_resolver._pmid_found(client, "1") is expected


def test_resolve_many_preserves_input_order_and_uses_the_resolver_seam() -> (
    None
):
    metas = [
        CitationMetadata(url="https://a"),
        CitationMetadata(url="https://b", retracted=True),
        CitationMetadata(url="https://c"),
    ]

    assert citation_resolver.resolve_many(metas, resolver=offline_resolver) == [
        Resolvability.RESOLVABLE,
        Resolvability.RETRACTED,
        Resolvability.RESOLVABLE,
    ]
    assert (
        citation_resolver.resolve_many(
            metas, resolver=lambda meta: Resolvability.UNRESOLVABLE
        )
        == [Resolvability.UNRESOLVABLE] * 3
    )


def test_a_doi_in_the_offline_retraction_set_short_circuits_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def reachable(client: httpx.Client, url: str) -> bool:
        calls.append(url)
        return True

    monkeypatch.setattr(
        retraction_set,
        "is_known_retracted",
        lambda doi: doi == "10.1000/offline-flagged",
    )
    monkeypatch.setattr(citation_resolver, "_reachable", reachable)

    verdict = citation_resolver.resolve_one(
        doi="10.1000/offline-flagged", pmid="", url="", retracted=False
    )

    assert verdict is Resolvability.RETRACTED
    assert calls == []


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
        (
            "https://example.org/1",
            "mitochondrial biogenesis rises during brown adipose "
            "thermogenesis in a poorly understood pathway",
            "mitochondrial biogenesis drives thermogenesis through "
            "uncoupling protein induction",
            True,
            "partial",
        ),
    ],
    ids=[
        "unavailable_when_no_url",
        "unavailable_when_flag_false",
        "verified_when_strong_overlap",
        "unsupported_when_no_overlap",
        "partial_when_source_states_some_of_the_claim",
    ],
)
def test_classify_citation(
    url: str, abstract: str, claim: str, available: bool, expected: str
) -> None:
    r = CitationRecord(
        url=url, abstract=abstract, claim=claim, available=available
    )
    assert classify_citation(r) == expected


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


def _write_gz(tmp_path: Path, dois: list[str]) -> Path:
    path = tmp_path / "retractions.txt.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(dois) + "\n")
    return path


def test_only_dois_in_the_set_are_known_retracted(tmp_path: Path) -> None:
    path = _write_gz(tmp_path, ["10.1000/known-bad"])

    assert retraction_set.is_known_retracted("10.1000/known-bad", path=path)
    assert retraction_set.is_known_retracted(
        "https://doi.org/10.1000/KNOWN-BAD", path=path
    )
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


def test_the_shipped_data_file_loads_and_is_non_empty() -> None:
    doi_set = retraction_set._load_doi_set(
        retraction_set.DEFAULT_RETRACTIONS_PATH
    )

    assert len(doi_set) > 0

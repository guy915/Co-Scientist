"""Offline contracts for pubmed."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest
from Bio import Entrez
from mcp_server.entrez import read_entrez
from mcp_server.literature_review import PubmedSource
from mcp_server.pubmed_client import (
    MIN_RESULTS_BEFORE_RELAX,
    _EntrezClient,
    _extract_abstract,
    _extract_publication_types,
    anchored_relaxed_query,
    field_tag_terms,
    or_relaxed_query,
    relaxation_ladder,
    search_with_relaxation,
)
from mcp_server.pubmed_storage import (
    has_proven_metadata_no_link,
    link_metadata_to_run,
    write_metadata_cache_file,
)
from mcp_server.text_extraction import clean_markup, extract_text_from_pmc_html
from mcp_server.tools.lit_review import search_pubmed as pubmed_parsing
from mcp_server.tools.lit_review import search_pubmed as tool
from mcp_server.tools.lit_review.search_pubmed import check_pubmed_available


class _CannedEntrezHandle:
    """Minimal response handle for the offline public-tool test."""

    def __init__(self, response: Any) -> None:
        self.response = response

    def close(self) -> None:
        pass


def test_extract_publication_types_reads_the_list() -> None:
    """Every entry in an article's PublicationTypeList is returned as-is."""
    article = {
        "PublicationTypeList": ["Journal Article", "Retracted Publication"]
    }
    assert _extract_publication_types(article) == [
        "Journal Article",
        "Retracted Publication",
    ]


def test_extract_publication_types_defaults_to_empty() -> None:
    """An article with no PublicationTypeList yields an empty list."""
    assert _extract_publication_types({}) == []


def test_fetch_paper_details_surfaces_publication_types(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A retracted article's publication type reaches the metadata dict."""
    canned = {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": "A retracted paper",
                        "Journal": {"Title": "Nature"},
                        "PublicationTypeList": [
                            "Journal Article",
                            "Retracted Publication",
                        ],
                        "AuthorList": [],
                    },
                    "DateRevised": {
                        "Year": "2020",
                        "Month": "1",
                        "Day": "1",
                    },
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }

    client = _EntrezClient(tmp_path)
    monkeypatch.setattr(
        "mcp_server.pubmed_client.entrez_call", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        _EntrezClient, "entrez_read", lambda self, handle: canned
    )
    monkeypatch.setattr(
        _EntrezClient, "_fetch_pmc_fulltext_id", lambda self, *_a: None
    )

    metadata = client._fetch_paper_details("123")

    assert metadata["publication_types"] == [
        "Journal Article",
        "Retracted Publication",
    ]


def test_fetch_paper_details_reads_as_plain_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PubMed italicizes species and gene names inside its metadata.

    A live query returns them on roughly half of all records, and the tag
    travels straight into whatever an agent quotes.
    """
    canned = {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": (
                            "Repurposing loratadine in "
                            "<i>Klebsiella pneumoniae</i>"
                        ),
                        "Abstract": {
                            "AbstractText": [
                                "<b>Background:</b>",
                                "bla<sub>NDM-1</sub> is widespread.",
                            ]
                        },
                        "Journal": {"Title": "Nature"},
                        "AuthorList": [],
                    },
                    "DateRevised": {"Year": "2020", "Month": "1", "Day": "1"},
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }

    client = _EntrezClient(tmp_path)
    monkeypatch.setattr(
        "mcp_server.pubmed_client.entrez_call", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        _EntrezClient, "entrez_read", lambda self, handle: canned
    )
    monkeypatch.setattr(
        _EntrezClient, "_fetch_pmc_fulltext_id", lambda self, *_a: None
    )

    metadata = client._fetch_paper_details("123")

    assert metadata["title"] == (
        "Repurposing loratadine in Klebsiella pneumoniae"
    )
    assert metadata["abstract"] == "Background: blaNDM-1 is widespread."


def test_fetch_paper_details_keeps_article_without_author_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An optional AuthorList does not discard otherwise valid metadata."""
    canned = {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": "A paper without an author list",
                        "Abstract": {"AbstractText": ["Useful abstract."]},
                        "Journal": {"Title": "Nature"},
                    },
                    "DateRevised": {"Year": "2020", "Month": "1", "Day": "1"},
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }

    client = _EntrezClient(tmp_path)
    monkeypatch.setattr(
        "mcp_server.pubmed_client.entrez_call", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        _EntrezClient, "entrez_read", lambda self, handle: canned
    )
    monkeypatch.setattr(
        _EntrezClient, "_fetch_pmc_fulltext_id", lambda self, *_a: None
    )

    metadata = client._fetch_paper_details("123")

    assert metadata["title"] == "A paper without an author list"
    assert metadata["abstract"] == "Useful abstract."
    assert metadata["publication"] == "Nature"
    assert metadata["authors"] == []


def test_pubmed_tool_returns_article_without_author_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The maintained tool keeps valid results when Entrez omits authors."""
    paper = {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": "A paper without an author list",
                        "Abstract": {"AbstractText": ["Useful abstract."]},
                        "Journal": {"Title": "Nature"},
                    },
                    "DateRevised": {"Year": "2020", "Month": "1", "Day": "1"},
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }

    monkeypatch.delenv("COSCIENTIST_PUBMED_PILOT_TRACE", raising=False)
    monkeypatch.setattr(tool, "_pubmed_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "mcp_server.pubmed_client.entrez_call",
        lambda request, **kwargs: request(**kwargs),
    )
    monkeypatch.setattr(
        Entrez,
        "esearch",
        lambda **_kwargs: _CannedEntrezHandle({"IdList": ["123"]}),
    )
    monkeypatch.setattr(
        Entrez, "efetch", lambda **_kwargs: _CannedEntrezHandle(paper)
    )
    monkeypatch.setattr(
        Entrez,
        "elink",
        lambda **_kwargs: _CannedEntrezHandle([{"LinkSetDb": []}]),
    )
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.response)

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="authorless",
            slug="authorless",
            max_papers=1,
            run_id="offline-test",
        )
    )

    assert results.keys() == {"123"}
    assert results["123"]["title"] == "A paper without an author list"
    assert results["123"]["abstract"] == "Useful abstract."
    assert results["123"]["authors"] == []
    metadata_path = (
        tmp_path
        / "pubmed"
        / "authorless"
        / "runs"
        / "offline-test"
        / "123.metadata.json"
    )
    assert metadata_path.is_symlink()
    assert (
        json.loads(metadata_path.read_text(encoding="utf-8")) == results["123"]
    )


def test_extract_abstract_keeps_the_missing_sentinel() -> None:
    """An article with no abstract still reports "<not found>".

    The sentinel is angle-bracketed but is not markup, which is why only
    real formatting tags are stripped.
    """
    assert _extract_abstract({}) == "<not found>"


def _canned(article: dict[str, Any]) -> dict[str, Any]:
    """Wraps one Article mapping in the efetch response shape."""
    return {
        "PubmedArticle": [
            {
                "MedlineCitation": {"Article": article},
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }


@pytest.fixture
def entrez(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stubs the Entrez round-trip with whatever the test hands back."""

    def _install(article: dict[str, Any]) -> None:
        monkeypatch.setattr(
            "mcp_server.tools.lit_review.search_pubmed.entrez_call",
            lambda *_a, **_k: None,
        )
        monkeypatch.setattr(
            "mcp_server.tools.lit_review.search_pubmed.read_entrez",
            lambda _handle: _canned(article),
        )

    return _install


def test_an_article_reads_as_plain_text(entrez: Any) -> None:
    """PubMed italicizes species names and subscripts gene symbols."""
    entrez(
        {
            "ArticleTitle": "Emergence of <i>mcr-1.1</i> in bla<sub>NDM</sub>",
            "Abstract": {
                "AbstractText": [
                    "<b>Background:</b>",
                    "Colistin is a last resort.",
                ]
            },
            "Journal": {"Title": "Nature", "JournalIssue": {}},
            "AuthorList": [],
        }
    )

    article = pubmed_parsing._fetch_pubmed_article("123")

    assert article.title == "Emergence of mcr-1.1 in blaNDM"
    assert article.abstract == "Background: Colistin is a last resort."


def test_an_article_without_an_abstract_reports_none(entrez: Any) -> None:
    """Absent stays absent: cleaning must not turn None into "".

    Downstream ranking treats an empty abstract as evidence it can read
    and a missing one as a paper to fetch, so the two are not the same.
    """
    entrez(
        {
            "ArticleTitle": "A paper with no abstract",
            "Journal": {"Title": "Nature", "JournalIssue": {}},
            "AuthorList": [],
        }
    )

    assert pubmed_parsing._fetch_pubmed_article("123").abstract is None


@pytest.mark.parametrize("reachable", [True, False])
def test_anonymous_pubmed_availability_queries_service(
    monkeypatch: pytest.MonkeyPatch, reachable: bool
) -> None:
    monkeypatch.delenv("ENTREZ_EMAIL", raising=False)
    monkeypatch.delenv("ENTREZ_API_KEY", raising=False)
    monkeypatch.setattr(Entrez, "email", None)
    monkeypatch.setattr(Entrez, "api_key", None)
    called: list[dict[str, object]] = []

    def esearch(**kwargs: object) -> BytesIO:
        called.append(kwargs)
        if not reachable:
            raise URLError("test service unavailable")
        return BytesIO(
            b'<?xml version="1.0" encoding="UTF-8" ?>'
            b"<!DOCTYPE eSearchResult PUBLIC "
            b'"-//NLM//DTD esearch 20060628//EN" '
            b'"https://eutils.ncbi.nlm.nih.gov/eutils/dtd/20060628/esearch.dtd">'
            b"<eSearchResult><IdList><Id>22745249</Id></IdList></eSearchResult>"
        )

    monkeypatch.setattr(Entrez, "esearch", esearch)
    assert check_pubmed_available() == ("true" if reachable else "false")
    assert len(called) == 1


@pytest.mark.parametrize("result", [{"IdList": ["123"]}, [{"LinkSetDb": []}]])
def test_entrez_reader_closes_the_response(
    monkeypatch: pytest.MonkeyPatch, result: object
) -> None:
    handle = BytesIO()
    monkeypatch.setattr(Entrez, "read", lambda _handle: result)
    assert read_entrez(handle) is result
    assert handle.closed


def test_entrez_reader_closes_a_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = BytesIO()

    def malformed(_handle: object) -> None:
        raise ValueError("malformed XML")

    monkeypatch.setattr(Entrez, "read", malformed)
    with pytest.raises(ValueError, match="malformed XML"):
        read_entrez(handle)
    assert handle.closed


# =============================================================================
# field_tag_terms
# =============================================================================


def test_field_tag_terms_wraps_each_term_in_mesh_and_tiab() -> None:
    """Every term is OR'd against its own MeSH heading and text-word match.

    This is what keeps an over-specific multi-term query from collapsing to
    zero hits under PubMed's automatic term mapping: tagging bypasses the
    ATM fallback that silently ANDs every bare word once a phrase fails to
    match a controlled-vocabulary heading.
    """
    assert field_tag_terms("kinase tumor", " AND ") == (
        "(kinase[tiab] OR kinase[mesh]) AND (tumor[tiab] OR tumor[mesh])"
    )


def test_field_tag_terms_honors_the_given_joiner() -> None:
    """The same tagging is reusable for an OR-joined broadened rung."""
    assert field_tag_terms("kinase tumor growth", " OR ") == (
        "(kinase[tiab] OR kinase[mesh]) OR (tumor[tiab] OR tumor[mesh])"
        " OR (growth[tiab] OR growth[mesh])"
    )


def test_field_tag_terms_tags_a_single_term() -> None:
    """A single term still gains the MeSH/text-word OR, just with no join."""
    assert field_tag_terms("kinase", " AND ") == (
        "(kinase[tiab] OR kinase[mesh])"
    )


def test_field_tag_terms_leaves_explicit_boolean_queries_untouched() -> None:
    """A query the caller already wrote as boolean is not re-tokenized.

    Re-tagging term-by-term would fight the caller's own AND/OR/NOT
    structure rather than extend it.
    """
    assert field_tag_terms("kinase AND tumor", " AND ") == "kinase AND tumor"
    assert field_tag_terms("kinase OR tumor", " OR ") == "kinase OR tumor"
    assert field_tag_terms("kinase NOT tumor", " AND ") == "kinase NOT tumor"


# =============================================================================
# or_relaxed_query
# =============================================================================


def test_or_relaxes_a_multi_term_query_with_field_tags() -> None:
    """A space-separated (implicitly ANDed) query becomes a tagged OR."""
    assert or_relaxed_query("kinase inhibition tumor growth") == (
        "(kinase[tiab] OR kinase[mesh])"
        " OR (inhibition[tiab] OR inhibition[mesh])"
        " OR (tumor[tiab] OR tumor[mesh])"
        " OR (growth[tiab] OR growth[mesh])"
    )


def test_single_term_and_boolean_queries_are_not_relaxed() -> None:
    """Nothing to broaden: one term, or an already-boolean query."""
    assert or_relaxed_query("kinase") is None
    assert or_relaxed_query("kinase OR tumor") is None
    assert or_relaxed_query("kinase AND tumor") is None
    assert or_relaxed_query("kinase NOT tumor") is None


# =============================================================================
# relaxation_ladder
# =============================================================================


def test_ladder_broadens_recency_then_anchored_then_terms() -> None:
    """Recency, then all-but-the-subject, then every term, in that order.

    Only the two broadened rungs carry field tags. The exact and
    recency-dropped rungs are left exactly as PubMed's own automatic term
    mapping receives them -- see the module docstring for the live
    measurement showing a naive per-word tag on those rungs regresses
    queries ATM already handles well.
    """
    ladder = relaxation_ladder("kinase inhibition tumor", recency_years=7)
    anchored = (
        "(kinase[tiab] OR kinase[mesh])"
        " AND (inhibition[tiab] OR inhibition[mesh])"
        " AND ((tumor[tiab] OR tumor[mesh]))"
    )
    tagged_or = (
        "(kinase[tiab] OR kinase[mesh])"
        " OR (inhibition[tiab] OR inhibition[mesh])"
        " OR (tumor[tiab] OR tumor[mesh])"
    )
    assert ladder == [
        ("kinase inhibition tumor", 7),
        ("kinase inhibition tumor", 0),
        (anchored, 0),
        (tagged_or, 0),
    ]


def test_the_anchored_rung_keeps_the_leading_terms_required() -> None:
    """Broadening must answer the question it was given.

    ORing every term is a different question, not a wider one: measured
    live, "PHGDH knockdown osimertinib resistance EGFR adenocarcinoma"
    ANDs to 0 hits and ORs to 1,966,502, and the three documents a caller
    then read were a gastric cancer case report, a leiomyosarcoma series
    and a paper on antimicrobial resistance.
    """
    anchored = anchored_relaxed_query("PHGDH knockdown osimertinib resistance")

    assert anchored is not None
    # The leading pair stays ANDed; only the tail relaxes.
    assert anchored.startswith(
        "(PHGDH[tiab] OR PHGDH[mesh])"
        " AND (knockdown[tiab] OR knockdown[mesh]) AND ("
    )
    assert " AND (osimertinib" not in anchored
    assert "osimertinib[tiab] OR osimertinib[mesh]" in anchored
    assert "resistance[tiab] OR resistance[mesh]" in anchored


def test_a_query_with_nothing_past_its_anchors_is_not_anchored() -> None:
    """Anchoring every term would just restate the exact rung."""
    assert anchored_relaxed_query("kinase") is None
    assert anchored_relaxed_query("kinase tumor") is None
    assert anchored_relaxed_query("kinase AND tumor") is None


def test_ladder_omits_redundant_rungs() -> None:
    """With no recency window and one term, only the exact query remains."""
    assert relaxation_ladder("kinase", recency_years=0) == [("kinase", 0)]
    # No recency to drop; the OR rung still differs, so it is included.
    assert relaxation_ladder("kinase tumor", recency_years=0) == [
        ("kinase tumor", 0),
        (
            "(kinase[tiab] OR kinase[mesh]) OR (tumor[tiab] OR tumor[mesh])",
            0,
        ),
    ]


def test_ladder_leaves_an_explicit_boolean_query_untagged() -> None:
    """A caller-supplied boolean query passes through every rung as-is."""
    for operator in ("AND", "OR", "NOT"):
        query = f"kinase {operator} tumor"
        assert relaxation_ladder(query, recency_years=0) == [(query, 0)]


# =============================================================================
# search_with_relaxation
# =============================================================================


def test_lowercase_prose_operators_do_not_suppress_relaxation() -> None:
    """Only PubMed's uppercase Boolean operators signal query structure."""
    calls: list[str] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append(term)
        return []

    query = "kinase and tumor or growth not drug"
    ids = search_with_relaxation(query, 10, 0, _esearch)

    assert ids == []
    assert calls[0] == query
    assert len(calls) == 3
    assert " AND (" in calls[1]
    assert calls[2].startswith("(kinase[tiab] OR kinase[mesh]) OR")


def test_runner_returns_first_rung_when_it_has_enough() -> None:
    """A first rung that meets the threshold costs exactly one search."""
    calls: list[tuple[str, int, int]] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append((term, retmax, recency))
        return [str(i) for i in range(MIN_RESULTS_BEFORE_RELAX)]

    ids = search_with_relaxation("kinase tumor", 10, 7, _esearch)
    assert len(ids) == MIN_RESULTS_BEFORE_RELAX
    assert len(calls) == 1  # no relaxation issued
    assert calls[0][1:] == (10, 7)


def test_runner_relaxes_until_a_rung_returns_enough() -> None:
    """A starved query falls through every rung to the broadest one."""
    calls: list[tuple[str, int, int]] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append((term, retmax, recency))
        # Only the fully-ORed rung returns results.
        if term.startswith("(kinase[tiab] OR kinase[mesh]) OR"):
            return ["1", "2", "3", "4"]
        return []

    ids = search_with_relaxation("kinase inhibition tumor", 10, 7, _esearch)
    assert ids == ["1", "2", "3", "4"]
    assert [c[1:] for c in calls] == [(10, 7), (10, 0), (10, 0), (10, 0)]
    assert calls[0][0] == "kinase inhibition tumor"
    assert " AND (" in calls[2][0]  # the anchored rung was tried first


def test_the_anchored_rung_is_taken_before_the_fully_ored_one() -> None:
    """The point of the middle rung: it stops the descent short.

    Reaching the OR rung is what returned three off-topic documents on a
    real run, so a rung that keeps the subject and clears the bar has to
    end the descent rather than merely precede it.
    """
    calls: list[str] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append(term)
        return ["1", "2", "3"] if " AND (" in term else []

    ids = search_with_relaxation("kinase inhibition tumor", 10, 0, _esearch)

    assert ids == ["1", "2", "3"]
    assert len(calls) == 2
    assert not calls[-1].startswith("(kinase[tiab] OR kinase[mesh]) OR")


def test_first_rung_target_survives_when_anchored_rung_fills_buffer() -> None:
    """A later qualifying rung must not discard an exact-rung PMID.

    The inputs and IDs reproduce the retained B. fragilis diagnostic, not a
    holdout for the frozen scientific comparison. The stub keeps this test
    offline while preserving the actual observed rung boundary.
    """
    query = (
        "Symbiotic Bacteroides fragilis polysaccharide A signals through TLR2 "
        "on Foxp3+ regulatory T cells to promote mucosal tolerance and "
        "colonization."
    )
    precise_ids = ["21512004"]
    anchored_ids = [
        "42415234",
        "42679821",
        "42400638",
        "42346964",
        "42115921",
        "40233891",
        "40764272",
        "41196415",
        "41195911",
    ]
    calls: list[str] = []
    trace: dict[str, Any] = {"sort": "pub_date"}

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        assert retmax == 9
        assert recency == 0
        calls.append(term)
        if term == query:
            return precise_ids
        if " AND (" in term:
            return anchored_ids
        pytest.fail("The qualifying anchored rung should stop the ladder")

    ids = search_with_relaxation(query, 9, 0, _esearch, trace)

    assert ids == [*precise_ids, *anchored_ids[:8]]
    assert calls == [query, anchored_relaxed_query(query)]
    assert trace["selected"]["rung_index"] == 2
    assert trace["selected"]["rung_type"] == "anchored"
    assert trace["selected"]["ids"] == ids


def test_merged_rung_ids_keep_first_occurrence_order_and_retmax_cap() -> None:
    query = "kinase inhibition tumor growth"
    anchored_ids = ["shared", "anchored"]
    broad_ids = ["anchored", "broad-1", "broad-2"]

    def _esearch(term: str, _retmax: int, _recency: int) -> list[str]:
        if term == query:
            return ["exact", "shared"]
        if " AND (" in term:
            return anchored_ids
        return broad_ids

    ids = search_with_relaxation(query, 4, 0, _esearch)

    assert ids == ["exact", "shared", "anchored", "broad-1"]


def test_runner_keeps_a_thin_result_when_no_rung_clears_the_bar() -> None:
    """Some evidence beats none: the first non-empty rung is returned."""

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        return ["only-one"] if recency > 0 else []

    ids = search_with_relaxation("kinase inhibition tumor", 10, 7, _esearch)
    assert ids == ["only-one"]


def test_runner_returns_empty_when_nothing_matches_at_any_breadth() -> None:
    """A query matching nothing even when broadened yields an empty list."""
    ids = search_with_relaxation(
        "kinase inhibition tumor", 10, 7, lambda *_: []
    )
    assert ids == []


def test_threshold_is_clamped_to_retmax() -> None:
    """A retmax below the minimum never forces relaxation it cannot satisfy."""
    calls: list[str] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append(term)
        return ["1"]  # one result, and retmax is 1

    ids = search_with_relaxation("kinase tumor", 1, 0, _esearch)
    assert ids == ["1"]
    assert len(calls) == 1  # one hit satisfies retmax=1, no relax


def test_storage_import_does_not_initialize_entrez() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.modules["Bio"] = None
import mcp_server.pubmed_storage
assert "mcp_server.entrez" not in sys.modules
assert "mcp_server.pubmed_client" not in sys.modules
assert "mcp_server.literature_review" not in sys.modules
""",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_metadata_and_empty_link_proof_survive_cache_relocation(
    tmp_path: Path,
) -> None:
    tree = tmp_path / "original"
    shared_dir = tree / "slug" / "shared"
    shared_dir.mkdir(parents=True)
    run_dir = tree / "slug" / "runs" / "run-id"
    run_dir.mkdir(parents=True)
    metadata_file = shared_dir / "101.metadata.json"
    metadata = {"title": "Paper \u03b2", "pmc_full_text_id": None}

    write_metadata_cache_file(metadata_file, metadata, successful_no_link=True)
    link_metadata_to_run(run_dir, "101")
    link_metadata_to_run(run_dir, "101")
    link_metadata_to_run(None, "101")
    assert metadata_file.read_text() == (
        '{"title": "Paper \\u03b2", "pmc_full_text_id": null}'
    )
    assert (run_dir / metadata_file.name).readlink() == Path(
        "../../shared/101.metadata.json"
    )

    relocated = tmp_path / "relocated"
    tree.rename(relocated)
    relocated_metadata = relocated / "slug" / "shared" / metadata_file.name
    run_link = relocated / "slug" / "runs" / "run-id" / metadata_file.name
    assert run_link.read_bytes() == relocated_metadata.read_bytes()
    assert has_proven_metadata_no_link(relocated_metadata)
    relocated_metadata.write_text('{"title": "changed"}')
    assert not has_proven_metadata_no_link(relocated_metadata)


def test_final_results_fill_fulltext_shortfall_with_abstracts(
    tmp_path: Path,
) -> None:
    """PMC papers lead, while abstract-only records fill the corpus target."""
    source = PubmedSource(tmp_path)
    metadata = {
        "abstract-1": {"title": "Recent abstract", "abstract": "A1"},
        "fulltext-1": {
            "title": "Open paper",
            "abstract": "A2",
            "fulltext": "Complete article",
        },
        "abstract-2": {"title": "Older abstract", "abstract": "A3"},
    }

    result = source._assemble_final_results(
        ["fulltext-1"], metadata, max_papers=3
    )

    assert list(result) == ["fulltext-1", "abstract-1", "abstract-2"]
    assert len(result) == 3


def test_final_results_respect_total_corpus_limit(tmp_path: Path) -> None:
    """The abstract fallback never expands beyond the requested paper count."""
    source = PubmedSource(tmp_path)
    metadata = {
        "fulltext-1": {"fulltext": "One"},
        "fulltext-2": {"fulltext": "Two"},
        "abstract-1": {"abstract": "Three"},
    }

    result = source._assemble_final_results(
        ["fulltext-1", "fulltext-2"], metadata, max_papers=2
    )

    assert list(result) == ["fulltext-1", "fulltext-2"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Both encodings of the same real Europe PMC title.
        (
            "Colistin resistance in <i>Klebsiella pneumoniae</i>",
            "Colistin resistance in Klebsiella pneumoniae",
        ),
        (
            "Sphingosine against &lt;i&gt;Pseudomonas aeruginosa&lt;/i&gt;",
            "Sphingosine against Pseudomonas aeruginosa",
        ),
        # A structured abstract's section headers are block-level: dropping
        # them without a space would run "Aims" into the sentence after it.
        ("<h4>Aims</h4>The convergence of", "Aims The convergence of"),
        # An inline tag closes up: bla<sub>NDM</sub> is one gene name.
        ("bla<sub>NDM-1</sub> carriage", "blaNDM-1 carriage"),
        ("Trials &amp; results", "Trials & results"),
        # Europe PMC pads abbreviated species names with zero-width spaces.
        ("(<i>K. pneumoniae</i>\u200b\u200b)", "(K. pneumoniae)"),
        ("line one\n\n  line two", "line one line two"),
        # Entities that are not markup decode to the character they name.
        ("growth at p &lt; 0.05 in group A", "growth at p < 0.05 in group A"),
        (None, ""),
        ("", ""),
        (123, ""),
    ],
)
def test_clean_markup(raw: Any, expected: str) -> None:
    assert clean_markup(raw) == expected


def test_clean_markup_leaves_a_comparison_shaped_like_a_tag_intact() -> None:
    """A decoded comparison whose operands spell a tag name is still text.

    "p &lt;b and q&gt; r" decodes to "p <b and q> r", which reads as an
    opening tag with attributes to anything matching loosely. Deleting it
    would take the clause with it, so only bare tags are stripped.
    """
    raw = "holds for p &lt;b and q&gt; r"

    assert clean_markup(raw) == "holds for p <b and q> r"


def test_clean_markup_leaves_comparisons_intact() -> None:
    """A decoded "<" is text, not a tag, so a comparison survives.

    Stripping anything between angle brackets would eat the span between a
    "less than" and the next ">" -- in an abstract that silently deletes a
    clause. Only the formatting tags publishers actually send are removed.
    """
    raw = "significant at p&lt;0.05 while A&gt;B held"

    assert clean_markup(raw) == "significant at p<0.05 while A>B held"


def test_pmc_rendering_keeps_abstract_and_section_paragraphs() -> None:
    xml = """<article>
      <abstract><p>First <i>abstract</i>.</p><p>Second.</p></abstract>
      <body>
        <sec><title>Methods</title>
          <boxed-text><p>Boxed.</p></boxed-text><p>Direct.</p>
          <fig><p>Figure caption.</p></fig>
          <sec><title>Subsection</title><p>Nested.</p></sec>
        </sec>
        <sec><p>Unlabelled.</p></sec>
        <sec><title>Empty</title><sec><p>Nested only.</p></sec></sec>
      </body>
      <back><ref-list><p>References.</p></ref-list></back>
    </article>"""
    assert extract_text_from_pmc_html(xml) == (
        "# abstract\n\nFirstabstract.\n\nSecond.\n\n"
        "## Methods\n\nDirect.\n\nBoxed.\n\n## section\n\nUnlabelled."
    )


@pytest.mark.parametrize(
    "xml,expected",
    [
        ("<article/>", ""),
        (
            "<abstract>Plain abstract.</abstract>",
            "# abstract\n\nPlain abstract.",
        ),
        ("<abstract><p/></abstract>", ""),
    ],
)
def test_pmc_rendering_handles_sparse_articles(xml: str, expected: str) -> None:
    assert extract_text_from_pmc_html(xml) == expected


@pytest.mark.parametrize("max_chars", [0, 25, 200_000])
def test_pmc_sections_preserve_the_corpus_format(max_chars: int) -> None:
    """PMC keeps abstracts, sections, and boxed paragraphs without clutter."""
    article = """<article>
        <abstract><p>Abstract one.</p><p>Abstract two.</p></abstract>
        <body><sec><title>Methods</title>
            <p>First.</p><boxed-text><p>Boxed.</p></boxed-text><p>Second.</p>
            <sec><title>Nested</title><p>Subsection.</p></sec>
            <fig><p>Figure caption.</p></fig>
            <table-wrap><p>Table caption.</p></table-wrap>
        </sec><sec><label>Conclusion</label><p>Done.</p></sec></body>
        <back><p>References.</p></back>
    </article>"""
    expected = (
        "# abstract\n\nAbstract one.\n\nAbstract two.\n\n"
        "## Methods\n\nFirst.\n\nSecond.\n\nBoxed.\n\n"
        "## Conclusion\n\nDone."
    )
    if len(expected) > max_chars:
        expected = expected[:max_chars] + "\n\n[... truncated for length ...]"
    assert extract_text_from_pmc_html(article, max_chars) == expected

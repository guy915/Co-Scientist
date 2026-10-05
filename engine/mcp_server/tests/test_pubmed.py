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
    anchored_relaxed_query,
    relaxation_ladder,
    search_with_relaxation,
)
from mcp_server.pubmed_storage import (
    has_proven_metadata_no_link,
    link_metadata_to_run,
    write_metadata_cache_file,
)
from mcp_server.tests._entrez import CannedEntrezHandle, install_entrez
from mcp_server.text_extraction import clean_markup, extract_text_from_pmc_html
from mcp_server.tools.lit_review import search_pubmed as tool

_JOURNAL = {"Title": "Nature", "JournalIssue": {}}


def _canned(article: dict[str, Any]) -> dict[str, Any]:
    return {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {"Journal": _JOURNAL, **article},
                    "DateRevised": {"Year": "2020", "Month": "1", "Day": "1"},
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }


def _install_article(
    monkeypatch: pytest.MonkeyPatch, article: dict[str, Any]
) -> None:
    install_entrez(
        monkeypatch,
        esearch=lambda **_kwargs: CannedEntrezHandle({"IdList": ["123"]}),
        efetch=lambda **_kwargs: CannedEntrezHandle(_canned(article)),
        elink=lambda **_kwargs: CannedEntrezHandle([{"LinkSetDb": []}]),
    )


_MARKUP = {
    "ArticleTitle": "Repurposing loratadine in <i>Klebsiella pneumoniae</i>",
    "Abstract": {
        "AbstractText": ["<b>Background:</b>", "bla<sub>NDM-1</sub> is common."]
    },
    "AuthorList": [],
}
_MARKUP_TEXT = (
    "Repurposing loratadine in Klebsiella pneumoniae",
    "Background: blaNDM-1 is common.",
)


@pytest.mark.parametrize(
    ("article", "expected"),
    [
        pytest.param(
            {
                "ArticleTitle": "A paper without an author list",
                "Abstract": {"AbstractText": ["Useful abstract."]},
            },
            {
                "title": "A paper without an author list",
                "abstract": "Useful abstract.",
                "authors": [],
                "publication": "Nature",
            },
            id="no author list",
        ),
        pytest.param(
            _MARKUP,
            dict(zip(("title", "abstract"), _MARKUP_TEXT, strict=True)),
            id="publisher markup reads as plain text",
        ),
        pytest.param(
            {
                "ArticleTitle": "A retracted paper",
                "PublicationTypeList": ["Journal Article", "Retraction"],
            },
            {
                "abstract": "<not found>",
                "publication_types": ["Journal Article", "Retraction"],
            },
            id="publication types and a missing abstract",
        ),
    ],
)
def test_the_fulltext_tool_returns_article_metadata_and_links_it_to_the_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    article: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    monkeypatch.delenv("COSCIENTIST_PUBMED_PILOT_TRACE", raising=False)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(tmp_path))
    _install_article(monkeypatch, article)

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="single", slug="slug", max_papers=1, run_id="run"
        )
    )

    assert results.keys() == {"123"}
    assert {key: results["123"][key] for key in expected} == expected
    metadata_path = tmp_path / "pubmed/slug/runs/run/123.metadata.json"
    assert metadata_path.is_symlink()
    assert (
        json.loads(metadata_path.read_text(encoding="utf-8")) == results["123"]
    )


@pytest.mark.parametrize(
    ("article", "title", "abstract"),
    [
        pytest.param(_MARKUP, *_MARKUP_TEXT, id="markup reads as plain text"),
        pytest.param(
            {"ArticleTitle": "No abstract"},
            "No abstract",
            None,
            id="no abstract",
        ),
    ],
)
def test_search_pubmed_returns_plain_text_articles(
    monkeypatch: pytest.MonkeyPatch,
    article: dict[str, Any],
    title: str,
    abstract: str | None,
) -> None:
    _install_article(monkeypatch, article)

    payload = json.loads(tool.search_pubmed("kinase", 1))

    (found,) = payload["results"]
    assert (found["title"], found["abstract"]) == (title, abstract)


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
    assert tool.check_pubmed_available() == ("true" if reachable else "false")
    assert len(called) == 1


@pytest.mark.parametrize("malformed", [False, True])
def test_the_entrez_reader_closes_the_response(
    monkeypatch: pytest.MonkeyPatch, malformed: bool
) -> None:
    handle = BytesIO()

    def read(_handle: object) -> object:
        if malformed:
            raise ValueError("malformed XML")
        return {"IdList": ["123"]}

    monkeypatch.setattr(Entrez, "read", read)
    if malformed:
        with pytest.raises(ValueError, match="malformed XML"):
            read_entrez(handle)
    else:
        assert read_entrez(handle) == {"IdList": ["123"]}
    assert handle.closed


def _tagged(*terms: str, joiner: str = " OR ") -> str:
    return joiner.join(f"({term}[tiab] OR {term}[mesh])" for term in terms)


_ANCHORED = (
    f"{_tagged('PHGDH', 'knockdown', joiner=' AND ')} AND "
    f"({_tagged('osimertinib', 'resistance')})"
)


@pytest.mark.parametrize(
    ("query", "recency", "ladder"),
    [
        ("kinase", 0, [("kinase", 0)]),
        (
            "kinase tumor",
            0,
            [("kinase tumor", 0), (_tagged("kinase", "tumor"), 0)],
        ),
        (
            "kinase inhibition tumor",
            7,
            [
                ("kinase inhibition tumor", 7),
                ("kinase inhibition tumor", 0),
                (
                    f"{_tagged('kinase', 'inhibition', joiner=' AND ')}"
                    f" AND ({_tagged('tumor')})",
                    0,
                ),
                (_tagged("kinase", "inhibition", "tumor"), 0),
            ],
        ),
        (
            "PHGDH knockdown osimertinib resistance",
            0,
            [
                ("PHGDH knockdown osimertinib resistance", 0),
                (_ANCHORED, 0),
                (_tagged("PHGDH", "knockdown", "osimertinib", "resistance"), 0),
            ],
        ),
        # Explicit Boolean structure would fight retokenizing.
        *(
            (f"kinase {op} tumor", 0, [(f"kinase {op} tumor", 0)])
            for op in ("AND", "OR", "NOT")
        ),
    ],
)
def test_the_relaxation_ladder_broadens_recency_then_anchored_then_terms(
    query: str, recency: int, ladder: list[tuple[str, int]]
) -> None:
    assert relaxation_ladder(query, recency_years=recency) == ladder


def _by_rung(**ids_by_rung: list[str]) -> Any:
    calls: list[tuple[str, int, int]] = []

    def esearch(term: str, retmax: int, recency: int) -> list[str]:
        if " AND (" in term:
            rung = "anchored"
        elif term.startswith("("):
            rung = "tagged_or"
        else:
            rung = "recent" if recency else "exact"
        calls.append((term, retmax, recency))
        return ids_by_rung.get(rung, [])

    esearch.calls = calls  # type: ignore[attr-defined]
    return esearch


@pytest.mark.parametrize(
    ("query", "retmax", "recency", "ids_by_rung", "expected", "rungs"),
    [
        (
            "kinase tumor",
            10,
            7,
            {"recent": [str(i) for i in range(MIN_RESULTS_BEFORE_RELAX)]},
            ["0", "1", "2"],
            1,
        ),
        (
            "kinase inhibition tumor",
            10,
            7,
            {"tagged_or": ["1", "2", "3", "4"]},
            ["1", "2", "3", "4"],
            4,
        ),
        (
            "kinase inhibition tumor",
            10,
            0,
            {"anchored": ["1", "2", "3"], "tagged_or": ["9"]},
            ["1", "2", "3"],
            2,
        ),
        (
            "kinase inhibition tumor",
            10,
            7,
            {"recent": ["only-one"]},
            ["only-one"],
            4,
        ),
        ("kinase inhibition tumor", 10, 7, {}, [], 4),
        # The threshold is clamped to retmax.
        ("kinase tumor", 1, 0, {"exact": ["1"]}, ["1"], 1),
        # Lowercase prose operators do not suppress relaxation.
        ("kinase and tumor or growth not drug", 10, 0, {}, [], 3),
    ],
)
def test_relaxation_stops_at_the_first_rung_with_enough_results(
    query: str,
    retmax: int,
    recency: int,
    ids_by_rung: dict[str, list[str]],
    expected: list[str],
    rungs: int,
) -> None:
    esearch = _by_rung(**ids_by_rung)

    ids = search_with_relaxation(query, retmax, recency, esearch)

    assert ids == expected
    assert len(esearch.calls) == rungs
    assert esearch.calls[0][0] == query


def test_first_rung_target_survives_when_anchored_rung_fills_buffer() -> None:
    query = (
        "Symbiotic Bacteroides fragilis polysaccharide A signals through TLR2 "
        "on Foxp3+ regulatory T cells to promote mucosal tolerance and "
        "colonization."
    )
    precise_ids = ["21512004"]
    anchored_ids = [str(42415234 + n) for n in range(9)]
    calls: list[str] = []
    trace: dict[str, Any] = {"sort": "pub_date"}

    def esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append(term)
        if term == query:
            return precise_ids
        assert " AND (" in term, "The anchored rung should stop the ladder"
        return anchored_ids

    ids = search_with_relaxation(query, 9, 0, esearch, trace)

    assert ids == [*precise_ids, *anchored_ids[:8]]
    assert calls == [query, anchored_relaxed_query(query)]
    assert trace["selected"]["rung_index"] == 2
    assert trace["selected"]["rung_type"] == "anchored"
    assert trace["selected"]["ids"] == ids


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
    metadata = {"title": "Paper β", "pmc_full_text_id": None}

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


@pytest.mark.parametrize(
    ("fulltext_ids", "max_papers", "expected"),
    [
        (["fulltext-1"], 3, ["fulltext-1", "abstract-1", "abstract-2"]),
        (["fulltext-1", "fulltext-2"], 2, ["fulltext-1", "fulltext-2"]),
    ],
)
def test_final_results_fill_fulltext_shortfall_within_the_corpus_limit(
    tmp_path: Path,
    fulltext_ids: list[str],
    max_papers: int,
    expected: list[str],
) -> None:
    metadata = {
        "abstract-1": {"title": "Recent abstract", "abstract": "A1"},
        "abstract-2": {"title": "Older abstract", "abstract": "A3"},
        **{paper_id: {"fulltext": "Complete"} for paper_id in fulltext_ids},
    }

    result = PubmedSource(tmp_path)._assemble_final_results(
        fulltext_ids, metadata, max_papers=max_papers
    )

    assert list(result) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Colistin resistance in <i>Klebsiella pneumoniae</i>",
            "Colistin resistance in Klebsiella pneumoniae",
        ),
        (
            "Sphingosine against &lt;i&gt;Pseudomonas aeruginosa&lt;/i&gt;",
            "Sphingosine against Pseudomonas aeruginosa",
        ),
        # Dropping block headers without a space joins them to the following
        # sentence.
        ("<h4>Aims</h4>The convergence of", "Aims The convergence of"),
        # Inline tags must close up so a split gene name remains one symbol.
        ("bla<sub>NDM-1</sub> carriage", "blaNDM-1 carriage"),
        ("Trials &amp; results", "Trials & results"),
        # Europe PMC species abbreviations can include zero-width spaces.
        ("(<i>K. pneumoniae</i>​​)", "(K. pneumoniae)"),
        ("line one\n\n  line two", "line one line two"),
        # Loose angle-bracket stripping can delete a comparison clause.
        ("holds for p &lt;b and q&gt; r", "holds for p <b and q> r"),
        ("at p&lt;0.05 while A&gt;B held", "at p<0.05 while A>B held"),
        (None, ""),
        ("", ""),
        (123, ""),
    ],
)
def test_clean_markup(raw: Any, expected: str) -> None:
    assert clean_markup(raw) == expected


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
    rendered = "# abstract\n\nFirstabstract.\n\nSecond.\n\n"
    rendered += "## Methods\n\nDirect.\n\nBoxed.\n\n## section\n\nUnlabelled."

    assert extract_text_from_pmc_html(xml) == rendered
    assert extract_text_from_pmc_html(xml, 25) == (
        rendered[:25] + "\n\n[... truncated for length ...]"
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

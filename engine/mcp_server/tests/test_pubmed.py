from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez
from mcp_server.entrez import read_entrez
from mcp_server.pubmed_client import (
    MIN_RESULTS_BEFORE_RELAX,
    anchored_relaxed_query,
    search_with_relaxation,
)
from mcp_server.pubmed_storage import (
    has_proven_metadata_no_link,
    link_metadata_to_run,
    write_metadata_cache_file,
)
from mcp_server.tests._entrez import (
    CannedEntrezHandle,
    configure_trace,
    install_entrez,
    pubmed_article,
    read_trace,
)
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
    ("raw", "expected"),
    [
        (
            "Sphingosine against &lt;i&gt;Pseudomonas aeruginosa&lt;/i&gt;",
            "Sphingosine against Pseudomonas aeruginosa",
        ),
        # Dropping block headers without a space joins them to the following
        # sentence.
        ("<h4>Aims</h4>The convergence of", "Aims The convergence of"),
        # Loose angle-bracket stripping can delete a comparison clause.
        ("at p&lt;0.05 while A&gt;B held", "at p<0.05 while A>B held"),
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


class _Handle(CannedEntrezHandle):
    def __init__(self, payload: Any = None, body: bytes = b"") -> None:
        super().__init__(payload)
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __contains__(self, value: str) -> bool:
        return value.encode() in self.body


def _article(paper_id: str) -> dict[str, Any]:
    article = pubmed_article(paper_id)["PubmedArticle"][0]
    article["MedlineCitation"]["PMID"] = paper_id
    return cast(dict[str, Any], article)


def _efetch_reversed(**kwargs: Any) -> _Handle:
    records = [_article(paper_id) for paper_id in kwargs["id"]]
    return _Handle({"PubmedArticle": list(reversed(records))})


def _elink_groups(links: dict[str, str]) -> Any:
    def elink(**kwargs: Any) -> _Handle:
        groups = [
            {
                "IdList": [paper_id],
                "LinkSetDb": (
                    [
                        {
                            "LinkName": "pubmed_pmc",
                            "Link": [{"Id": links[paper_id]}],
                        }
                    ]
                    if paper_id in links
                    else []
                ),
            }
            for paper_id in kwargs["id"]
        ]
        return _Handle(list(reversed(groups)))

    return elink


def _install_batch_entrez(
    monkeypatch: pytest.MonkeyPatch,
    efetch: Any,
    elink: Any,
) -> None:
    install_entrez(monkeypatch, efetch=efetch, elink=elink)
    monkeypatch.setattr(Entrez, "max_tries", 1)
    monkeypatch.setattr(Entrez, "sleep_between_tries", 0)


@pytest.fixture
def _restore_entrez_retry_policy() -> Any:
    max_tries = Entrez.max_tries
    sleep_between_tries = Entrez.sleep_between_tries
    yield
    Entrez.max_tries = max_tries
    Entrez.sleep_between_tries = sleep_between_tries


@pytest.mark.usefixtures("_restore_entrez_retry_policy")
def test_batched_search_keeps_metadata_on_elink_error_and_recovers_next_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = tmp_path / "cache"
    configure_trace(
        monkeypatch, cache_root, "batch-offline-build", free_models=True
    )
    monkeypatch.setenv("COSCIENTIST_PUBMED_METADATA_BATCH", "1")
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

    paper_ids = ["701", "702", "703"]
    pubmed_requests: list[list[str]] = []
    elink_requests: list[dict[str, Any]] = []
    fulltext_requests: list[str] = []
    fail_elink = True
    link = _elink_groups({"701": "1701"})

    def efetch(**kwargs: Any) -> _Handle:
        if kwargs["db"] == "pubmed":
            pubmed_requests.append(kwargs["id"])
            return _efetch_reversed(**kwargs)
        fulltext_requests.append(kwargs["id"])
        return _Handle(
            body=(
                b"<article><body><sec><title>Introduction</title>"
                b"<p>Recovered PMC full text.</p></sec></body></article>"
            )
        )

    def elink(**kwargs: Any) -> _Handle:
        elink_requests.append(kwargs.copy())
        if fail_elink:
            raise RuntimeError("offline")
        return cast(_Handle, link(**kwargs))

    monkeypatch.setattr(
        Entrez, "esearch", lambda **_kwargs: _Handle({"IdList": paper_ids})
    )
    _install_batch_entrez(monkeypatch, efetch, elink)

    def search(run_id: str) -> dict[str, Any]:
        return asyncio.run(
            tool.pubmed_search_with_fulltext(
                query="batch ELink recovery",
                slug="batch-elink-recovery",
                max_papers=1,
                run_id=run_id,
            )
        )

    first_results = search("elink-failure-run")
    shared_dir = cache_root / "pubmed" / "batch-elink-recovery" / "shared"
    first_trace = read_trace(
        cache_root, "batch-elink-recovery", "elink-failure-run"
    )

    assert list(first_results) == ["701"]
    assert first_results["701"]["pmc_full_text_id"] is None
    assert not any(shared_dir.glob("*.metadata.json"))
    assert first_trace["metadata_origins"] == dict.fromkeys(
        paper_ids, "entrez_fetch"
    )
    assert [
        (error["pmid"], error["stage"]) for error in first_trace["fetch_errors"]
    ] == [(paper_id, "elink") for paper_id in paper_ids]

    fail_elink = False
    second_results = search("elink-recovered-run")

    assert pubmed_requests == [paper_ids, paper_ids]
    assert [request["id"] for request in elink_requests] == [paper_ids] * 2
    assert list(second_results) == ["701"]
    assert "Recovered PMC full text." in second_results["701"]["fulltext"]
    assert fulltext_requests == ["1701"]
    assert all(
        (shared_dir / f"{paper_id}.metadata.json").exists()
        for paper_id in paper_ids
    )

import asyncio
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from Bio import Entrez

from mcp_server.entrez import entrez_call, initialize_entrez, read_entrez
from mcp_server.literature_review import PubmedSource
from mcp_server.pubmed_client import search_with_relaxation
from mcp_server.pubmed_records import parse_pubmed_record
from mcp_server.pubmed_storage import confined_path, validate_cache_identifier
from mcp_server.text_extraction import extract_text_from_pmc_html
from mcp_server.tools._results import failed, keyed_records, non_raising, ok

logger = logging.getLogger(__name__)


def check_pubmed_available() -> str:
    """Return 'true' when a cheap PubMed canary query returns a result."""
    initialize_entrez()
    try:
        results = read_entrez(entrez_call(Entrez.esearch, db="pubmed", term="cancer", retmax=1))
        return "true" if results.get("IdList") else "false"
    except Exception as exc:
        logger.warning("PubMed availability query failed: %s", exc)
        logger.debug("PubMed availability query failed", exc_info=True)
        return "false"


def _esearch_pubmed_ids(query: str, max_papers: int) -> list[str]:

    def search(term: str, retmax: int, _recency_years: int) -> list[str]:
        results = read_entrez(entrez_call(Entrez.esearch, db="pubmed", term=term, retmax=retmax))
        ids: list[str] = results.get("IdList", [])
        return ids

    return search_with_relaxation(query, max_papers, 0, search)


def search_pubmed(query: str, max_papers: int = 10) -> dict[str, Any]:
    """Search PubMed and return article metadata as a JSON result envelope.

    Args:
        query: Search query for PubMed.
        max_papers: Maximum number of papers to retrieve.
    """
    try:
        initialize_entrez()
        articles = []
        metadata_failed = False
        for paper_id in _esearch_pubmed_ids(query, max_papers):
            try:
                articles.append(_fetch_pubmed_article(paper_id).to_dict())
            except Exception as exc:
                # A malformed paper must not discard successful siblings.
                logger.warning("Failed to fetch metadata for paper %s: %s", paper_id, exc)
                metadata_failed = True
        return failed("PubMed metadata unavailable") if metadata_failed else ok(articles)
    except Exception as exc:
        logger.error("Error searching PubMed: %s", exc)
        return failed(exc)


@dataclass
class Article:
    title: str
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citations: int = 0
    abstract: str | None = None
    content: str | None = None
    source_id: str | None = None
    # The Article default is shared across sources; PubMed tools explicitly
    # stamp their own source.
    source: str = "google_scholar"
    pdf_links: list[str] = field(default_factory=list)
    # Being listed in results does not mean the agent consulted article content.
    used_in_analysis: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pubmed_article_url(doi: str | None, paper_id: str) -> str:
    # DOI resolves to the publisher's copy; PubMed is the fallback.
    return f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{paper_id}/"


def _fetch_pubmed_article(paper_id: str) -> Article:
    paper_results = read_entrez(entrez_call(Entrez.efetch, db="pubmed", id=paper_id))

    pubmed_article = paper_results["PubmedArticle"][0]
    record = parse_pubmed_record(pubmed_article)
    return Article(
        title=record.title,
        url=_pubmed_article_url(record.doi, paper_id),
        authors=record.authors,
        year=record.year,
        venue=record.publication,
        abstract=record.abstract,
        source_id=paper_id,
        source="pubmed",
    )


def _read_and_extract_fulltext(html_file: Path) -> str:
    return extract_text_from_pmc_html(html_file.read_text(encoding="utf-8"))


async def _extract_fulltext(
    pmc_id: str, metadata: dict[str, Any], run_dir: Path, cache_root: Path
) -> bool:
    try:
        validate_cache_identifier(pmc_id, label="PMC ID", numeric=True)
        relative_run_dir = run_dir.relative_to(cache_root)
        html_file = confined_path(cache_root, *relative_run_dir.parts, f"{pmc_id}.fulltext.html")
        if not html_file.exists():
            logger.warning("Fulltext file not found for %s at %s", pmc_id, html_file)
            return False
        # Full-article parsing is CPU-heavy; keep it off the event loop.
        metadata["fulltext"] = await asyncio.to_thread(_read_and_extract_fulltext, html_file)
        return True
    except Exception as exc:
        logger.error("Failed to extract text from %s: %s", pmc_id, exc)
        return False


def _pubmed_cache_dir() -> Path:
    cache_dir = Path(os.getenv("COSCIENTIST_LIT_REVIEW_DIR", "./cache/literature_review"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir.resolve()


@non_raising
async def pubmed_search_with_fulltext(
    query: str,
    slug: str,
    max_papers: int = 10,
    recency_years: int = 0,
    run_id: str | None = None,
    *,
    include_fulltext: bool = True,
) -> dict[str, Any]:
    """Search PubMed and attach readable text from cached PMC articles.

    Args:
        query: PubMed boolean query (AND/OR/NOT operators).
        slug: Identifier for organizing results (research goal hash).
        max_papers: Maximum papers to retrieve.
        recency_years: Filter to papers from last N years (0 = no filter).
        run_id: Unique run identifier for per-run tracking.
        include_fulltext: Skip downloads and extraction when false, retaining
            PMC-linked selection and metadata provenance.

    Returns:
        Metadata keyed by PubMed ID, with fulltext where available.
    """
    lit_review_dir = _pubmed_cache_dir()
    validate_cache_identifier(slug, label="slug")
    if run_id is not None:
        validate_cache_identifier(run_id, label="run ID")
    source = PubmedSource(lit_review_dir / "pubmed")
    results = await source.pubmed_search(
        query,
        slug,
        max_papers,
        recency_years,
        run_id,
        include_fulltext=include_fulltext,
    )
    if include_fulltext:
        base_dir = confined_path(lit_review_dir, "pubmed", slug)
        run_dir = confined_path(base_dir, "runs", run_id) if run_id else base_dir
        extracted = sum(
            await asyncio.gather(
                *(
                    _extract_fulltext(str(pmc_id), metadata, run_dir, lit_review_dir)
                    for metadata in results.values()
                    if (pmc_id := metadata.get("pmc_full_text_id"))
                )
            )
        )
        logger.info("Extracted fulltext for %s/%s papers", extracted, len(results))
    return keyed_records(results)

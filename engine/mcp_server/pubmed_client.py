"""Entrez-backed PubMed client: search and per-paper metadata fetching."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from Bio import Entrez

from mcp_server.entrez import initialize_entrez
from mcp_server.entrez_rate_limit import entrez_call, record_pilot_fetch_error
from mcp_server.pubmed_query import search_with_relaxation
from mcp_server.tools.text import clean_markup

logger = logging.getLogger(__name__)

# One source of truth for the sort sent to Entrez and recorded in pilot traces.
PUBMED_SEARCH_SORT = "pub_date"
PUBMED_METADATA_BATCH_ENV = "COSCIENTIST_PUBMED_METADATA_BATCH"
PUBMED_METADATA_BATCH_SIZE = 9


def _metadata_no_link_sidecar(metadata_file: Path) -> Path:
    return metadata_file.with_name(f".{metadata_file.stem}.no-link.sha256")


def _has_proven_metadata_no_link(metadata_file: Path) -> bool:
    try:
        expected = _metadata_no_link_sidecar(metadata_file).read_text(
            encoding="ascii"
        )
        actual = hashlib.sha256(metadata_file.read_bytes()).hexdigest()
    except (OSError, UnicodeError):
        return False
    return expected == actual


def _write_metadata_cache_file(
    metadata_file: Path,
    metadata: dict[str, Any],
    *,
    successful_no_link: bool = False,
) -> None:
    sidecar = _metadata_no_link_sidecar(metadata_file)
    # Failed legacy lookups can rewrite identical JSON. Expire the old proof.
    sidecar.unlink(missing_ok=True)
    with open(metadata_file, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream)
    if successful_no_link:
        digest = hashlib.sha256(metadata_file.read_bytes()).hexdigest()
        sidecar.write_text(digest, encoding="ascii")


# Configure Entrez credentials at import so the source is ready to query.
initialize_entrez()


def _parse_authors(article: dict[str, Any]) -> list[str]:
    """Builds "Forename Lastname" strings for each author on an article.

    Args:
        article: Entrez-parsed ``Article`` mapping (from a
            ``PubmedArticle["MedlineCitation"]["Article"]`` node).

    Returns:
        List of author display names, dropping any entry where either name
        part was missing rather than emitting a name with a literal
        "<invalid>" token in it.
    """
    names = []
    for author in article.get("AuthorList", []):
        name = (
            f"{author.get('ForeName', '<invalid>')} "
            f"{author.get('LastName', '<invalid>')}"
        )
        if "<invalid>" not in name:
            names.append(name)
    return names


def _extract_doi(pubmed_article: dict[str, Any]) -> str:
    """Extracts the DOI from a PubmedArticle's ArticleIdList.

    Args:
        pubmed_article: Entrez-parsed ``PubmedArticle`` element.

    Returns:
        The DOI string, or "<not found>" if no ArticleIdList entry is
        tagged with ``IdType="doi"``.
    """
    # ArticleIdList mixes several ID types (pubmed, doi, pmc, ...); filter
    # down to the one tagged IdType="doi". The "<not found>" default covers
    # the empty case where no DOI was assigned.
    return next(
        (
            str(element)
            for element in filter(
                lambda xml_string: (
                    xml_string.attributes.get("IdType", None) == "doi"
                ),
                pubmed_article["PubmedData"]["ArticleIdList"],
            )
        ),
        "<not found>",
    )


def _parse_date_revised(citation: dict[str, Any]) -> str:
    """Formats a citation's DateRevised as "YYYY/M/D".

    Args:
        citation: Entrez-parsed ``MedlineCitation`` mapping.

    Returns:
        The revision date joined as "YYYY/M/D" with no zero-padding, to
        match the split-and-index expression this field is consumed with
        elsewhere (e.g. field_mapping "date_revised|split:/|index:0|int" to
        pull out just the year).
    """
    # Entrez.read parses DateRevised into a dict-like with separate
    # Year/Month/Day string fields.
    date_revised_raw = citation["DateRevised"]
    return "{}/{}/{}".format(
        *[str(date_revised_raw[field]) for field in ["Year", "Month", "Day"]]
    )


def _extract_publication_types(article: dict[str, Any]) -> list[str]:
    """Extracts an article's PubMed publication types.

    Includes "Retracted Publication" for a retracted article -- the field
    the engine's shared multi-shape retraction detector
    (``article_support._metadata_is_retracted``) already checks, so
    surfacing it here is what lets ranking and evidence-budget selection
    recognize a retracted PubMed paper at all.

    Args:
        article: Entrez-parsed ``Article`` mapping.

    Returns:
        The publication type strings (e.g. "Journal Article", "Retracted
        Publication"), or an empty list if the article carries none.
    """
    return [str(item) for item in article.get("PublicationTypeList", [])]


def _extract_abstract(article: dict[str, Any]) -> str:
    """Extracts and joins an article's abstract text.

    Args:
        article: Entrez-parsed ``Article`` mapping.

    Returns:
        The abstract text with any labeled sections joined into one string,
        or "<not found>" when the article carries no abstract.
    """
    try:
        # Some articles split the abstract into multiple labeled sections
        # (Background, Methods, ...); join them into one string. Articles
        # with no abstract omit the key entirely.
        return " ".join(article["Abstract"]["AbstractText"])
    except KeyError:
        return "<not found>"


def _parse_pubmed_article(
    pubmed_article: dict[str, Any],
    pmc_full_text_id: str | None,
    doi: str | None = None,
) -> dict[str, Any]:
    """Parses one PubMed record using the maintained metadata fields."""
    citation = pubmed_article["MedlineCitation"]
    article = citation["Article"]
    resolved_doi = doi if doi is not None else _extract_doi(pubmed_article)
    return {
        "date_revised": _parse_date_revised(citation),
        "title": clean_markup(article["ArticleTitle"]),
        "abstract": clean_markup(_extract_abstract(article)),
        "doi": resolved_doi,
        "authors": _parse_authors(article),
        "publication": article["Journal"]["Title"],
        "pmc_full_text_id": pmc_full_text_id,
        "publication_types": _extract_publication_types(article),
    }


def _apply_recency_filter(
    search_params: dict[str, Any], recency_years: int
) -> None:
    """Adds a publication-date window to PubMed search params in place.

    Args:
        search_params: esearch parameter dict to mutate.
        recency_years: Number of years back from the current year to keep;
            values of 0 or less leave the params unchanged.
    """
    if recency_years <= 0:
        return
    # Imported locally since it is only needed for this branch.
    from datetime import datetime

    current_year = datetime.now().year
    min_year = current_year - recency_years
    search_params["mindate"] = f"{min_year}/01/01"
    search_params["maxdate"] = f"{current_year}/12/31"
    search_params["datetype"] = "pdat"  # filter by publication date
    logger.debug(
        "applying recency filter: %s-%s (last %s years)",
        min_year,
        current_year,
        recency_years,
    )


class _EntrezClient:
    """PubMed source base: Entrez search and per-paper metadata primitives."""

    def __init__(self, qualified_path: Path):
        """Initializes the PubMed source.

        Args:
            qualified_path: Directory where this source stores papers (the
                ``pubmed`` subdirectory of the literature-review root).
        """
        self.qualified_path = qualified_path

    def entrez_read(self, handle: Any) -> Any:
        """Reads an open Entrez handle.

        Entrez.read parses XML into either a dict-like or list-like structure
        depending on the query, so the return type is intentionally opaque.

        Rate limiting does not belong here: by the time a handle exists its
        request has already been sent, so the delay this used to sleep paced
        nothing. Requests are paced before they go out, in
        :func:`mcp_server.entrez_rate_limit.entrez_call`.

        Args:
            handle: Open Entrez response handle.

        Returns:
            Parsed result from Entrez.read() (dict-like or list-like).
        """
        results = Entrez.read(handle)
        handle.close()
        return results

    def _fetch_pmc_fulltext_id(self, paper_id: str, doi: str) -> str | None:
        """Looks up the PMC fulltext ID linked to a PubMed article.

        Args:
            paper_id: PubMed article ID.
            doi: DOI of the article, used only for the debug log line when no
                PMC link is found.

        Returns:
            The linked PMC ID, or None if no fulltext link exists.
        """
        try:
            # elink cross-references PubMed IDs to PMC IDs; a paper only has
            # a usable PMC fulltext if this link exists. A request failure
            # still means fulltext is unavailable for retrieval, but pilot
            # traces must distinguish it from a successful no-link response.
            related = self.entrez_read(
                entrez_call(
                    Entrez.elink, dbfrom="pubmed", db="pmc", id=paper_id
                )
            )
        except Exception as exc:
            record_pilot_fetch_error("elink", exc)
            logger.debug("%s -- fulltext not available in pmc", doi)
            return None
        try:
            link_sets = related[0]["LinkSetDb"]
            if not link_sets or not link_sets[0].get("Link"):
                return None
            return str(link_sets[0]["Link"][0]["Id"])
        except (IndexError, KeyError, TypeError) as exc:
            record_pilot_fetch_error("elink_parse", exc)
            logger.debug("%s -- fulltext not available in pmc", doi)
            return None

    def _fetch_paper_details(self, paper_id: str) -> dict[str, Any]:
        """Fetches and parses one paper's metadata from Entrez (blocking).

        Performs the blocking efetch/elink network calls and XML parsing for a
        single paper. Intended to be dispatched via asyncio.to_thread so
        callers can fetch many papers concurrently without blocking the event
        loop.

        Args:
            paper_id: PubMed article ID.

        Returns:
            Metadata dict for the paper (title, abstract, authors, doi, etc.).
        """
        # efetch returns a PubmedArticleSet; a single-id request still comes
        # back as a one-element list, hence the [0] below.
        results = self.entrez_read(
            entrez_call(Entrez.efetch, db="pubmed", id=paper_id)
        )
        pubmed_article = results["PubmedArticle"][0]
        doi = _extract_doi(pubmed_article)
        pmc_id = self._fetch_pmc_fulltext_id(paper_id, doi)
        return _parse_pubmed_article(pubmed_article, pmc_id, doi)

    def _esearch_ids(
        self, query: str, retmax: int, recency_years: int
    ) -> list[str]:
        """Runs one esearch attempt and returns its ids (empty if none)."""
        search_params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "sort": PUBMED_SEARCH_SORT,
        }
        _apply_recency_filter(search_params, recency_years)
        logger.debug("searching pubmed with sort=%s", PUBMED_SEARCH_SORT)
        results = self.entrez_read(entrez_call(Entrez.esearch, **search_params))
        # esearch's IdList is empty (not absent) when nothing matches, so the
        # truthiness check also covers that case, not just a missing key.
        if id_list := results.get("IdList", None):
            return [str(paper_id) for paper_id in id_list]
        return []

    def pubmed_search_ids(
        self,
        query: str,
        retmax: int = 10,
        recency_years: int = 0,
        trace: dict[str, Any] | None = None,
    ) -> list[str]:
        """Searches PubMed and returns matching paper IDs.

        PubMed ANDs every untagged term, so a distilled multi-term query
        collapses toward zero hits; the search is issued down a relaxation
        ladder (drop the recency window, then OR the terms) so a starved query
        still returns candidates to ground against rather than an empty pool.

        Args:
            query: PubMed boolean query.
            retmax: Maximum results to return.
            recency_years: Filter to papers from last N years (0 = no filter).
            trace: Optional bounded pilot-trace dictionary.

        Returns:
            List of PubMed IDs sorted by publication date (most recent first).
        """
        ids = search_with_relaxation(
            query, retmax, recency_years, self._esearch_ids, trace
        )
        if not ids:
            logger.warning("No results found for query: %s", query)
        return ids

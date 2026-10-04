from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from Bio import Entrez

from mcp_server.entrez import (
    entrez_call,
    initialize_entrez,
    read_entrez,
    record_pilot_fetch_error,
)
from mcp_server.text_extraction import clean_markup

logger = logging.getLogger(__name__)

_MAX_TRACE_IDS = 9

# Clamp the sufficiency threshold to retmax so tiny requests cannot force
# impossible relaxation.
MIN_RESULTS_BEFORE_RELAX = 3

_BOOLEAN_OPERATORS = frozenset({"AND", "OR", "NOT"})

EsearchFn = Callable[[str, int, int], list[str]]


def _has_boolean_structure(query: str) -> bool:
    """PubMed reserves uppercase AND/OR/NOT; lowercase forms are ordinary
    search terms (NCBI PubMed Help).
    """
    return any(token in _BOOLEAN_OPERATORS for token in query.split())


def _field_tagged_term(term: str) -> str:
    """Field tags bypass automatic term mapping, which silently splits
    unmatched phrases into ANDed words.
    """
    return f"({term}[tiab] OR {term}[mesh])"


def field_tag_terms(query: str, joiner: str) -> str:
    """Retagging explicit Boolean structure would override the caller's query
    intent.
    """
    if _has_boolean_structure(query):
        return query
    terms = query.split()
    if not terms:
        return query
    return joiner.join(_field_tagged_term(term) for term in terms)


# Two leading terms anchor the topic; one is broad, while three can reproduce
# zero-hit conjunctions.
_ANCHOR_TERMS = 2


def anchored_relaxed_query(query: str) -> str | None:
    """Leading terms carry the subject; relaxing them would answer a
    different question.
    """
    if _has_boolean_structure(query):
        return None
    tokens = query.split()
    if len(tokens) <= _ANCHOR_TERMS:
        return None
    anchors = " AND ".join(
        _field_tagged_term(term) for term in tokens[:_ANCHOR_TERMS]
    )
    loosened = " OR ".join(
        _field_tagged_term(term) for term in tokens[_ANCHOR_TERMS:]
    )
    return f"{anchors} AND ({loosened})"


def or_relaxed_query(query: str) -> str | None:
    if _has_boolean_structure(query):
        return None
    tokens = query.split()
    if len(tokens) < 2:
        return None
    return field_tag_terms(query, " OR ")


def relaxation_ladder(
    query: str, recency_years: int = 0
) -> list[tuple[str, int]]:
    """Keep the recency-only rung untagged; anchor the subject before
    broadening every term.
    """
    ladder: list[tuple[str, int]] = [(query, recency_years)]
    if recency_years > 0:
        ladder.append((query, 0))
    for rung in (anchored_relaxed_query(query), or_relaxed_query(query)):
        if rung is not None and rung not in {term for term, _ in ladder}:
            ladder.append((rung, 0))
    return ladder


def _relaxation_rung_type(
    rung_index: int, query: str, term: str, recency_years: int
) -> str:
    if rung_index == 1:
        return "exact"
    if term == query and recency_years == 0:
        return "recency_dropped"
    return "anchored" if " AND (" in term else "or"


def _record_attempt(
    trace: dict[str, Any] | None, attempt: dict[str, Any] | None
) -> None:
    """Application ESearch rungs exclude hidden Biopython transport retries."""
    if trace is not None and attempt is not None:
        trace.setdefault("attempts", []).append(attempt)


def _new_attempt(
    trace: dict[str, Any] | None,
    rung_index: int,
    rung_type: str,
    recency_years: int,
    retmax: int,
) -> dict[str, Any]:
    return {
        "rung_index": rung_index,
        "rung_type": rung_type,
        "operation": "esearch",
        "recency_years": recency_years,
        "retmax": retmax,
        "sort": trace["sort"] if trace is not None else None,
    }


def _record_failed_attempt(
    trace: dict[str, Any] | None,
    attempt: dict[str, Any],
    exc: Exception,
) -> None:
    attempt.update(
        {"count": 0, "first_ids": [], "error_type": type(exc).__name__}
    )
    _record_attempt(trace, attempt)
    if trace is None:
        return
    trace["selected"] = None
    trace["threshold_met"] = False
    trace["error"] = {"stage": "esearch", "type": type(exc).__name__}


def _record_selected_rung(
    trace: dict[str, Any] | None,
    selected: tuple[int, str, str, list[str]] | None,
    threshold_met: bool,
) -> None:
    if trace is None:
        return
    trace["selected"] = (
        {
            "rung_index": selected[0],
            "rung_type": selected[1],
            "count": len(selected[3]),
            "ids": selected[3][:_MAX_TRACE_IDS],
            "sort": trace["sort"],
        }
        if selected
        else None
    )
    trace["threshold_met"] = threshold_met


def search_with_relaxation(
    query: str,
    retmax: int,
    recency_years: int,
    esearch: EsearchFn,
    trace: dict[str, Any] | None = None,
) -> list[str]:
    """Keep precise-rung hits when broader searches supply enough results;
    some evidence beats none.
    """
    threshold = min(MIN_RESULTS_BEFORE_RELAX, retmax)
    merged: list[str] = []
    fallback: tuple[int, str, str] | None = None
    for rung_index, (term, recency) in enumerate(
        relaxation_ladder(query, recency_years), start=1
    ):
        rung_type = _relaxation_rung_type(rung_index, query, term, recency)
        attempt = _new_attempt(trace, rung_index, rung_type, recency, retmax)
        try:
            ids = esearch(term, retmax, recency)
        except Exception as exc:
            _record_failed_attempt(trace, attempt, exc)
            raise
        attempt.update({"count": len(ids), "first_ids": ids[:_MAX_TRACE_IDS]})
        _record_attempt(trace, attempt)
        merged.extend(i for i in dict.fromkeys(ids) if i not in merged)
        del merged[retmax:]
        if len(ids) >= threshold:
            _record_selected_rung(
                trace,
                (rung_index, rung_type, term, merged),
                threshold_met=True,
            )
            return merged
        if ids and fallback is None:
            fallback = (rung_index, rung_type, term)
    _record_selected_rung(
        trace, (*fallback, merged) if fallback else None, threshold_met=False
    )
    return merged


# One source of truth for the sort sent to Entrez and recorded in pilot traces.
PUBMED_SEARCH_SORT = "pub_date"
PUBMED_METADATA_BATCH_ENV = "COSCIENTIST_PUBMED_METADATA_BATCH"
PUBMED_METADATA_BATCH_SIZE = 9


initialize_entrez()


def _parse_authors(article: dict[str, Any]) -> list[str]:
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
    # ArticleIdList mixes namespaces; select only the DOI type.
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
    """Keep the date shape used by split/index field mappings."""
    date_revised_raw = citation["DateRevised"]
    return "{}/{}/{}".format(
        *[str(date_revised_raw[field]) for field in ["Year", "Month", "Day"]]
    )


def _extract_publication_types(article: dict[str, Any]) -> list[str]:
    """Publication types expose retractions to the engine's evidence/ranking
    detector.
    """
    return [str(item) for item in article.get("PublicationTypeList", [])]


def _extract_abstract(article: dict[str, Any]) -> str:
    try:
        # Some abstracts have multiple labeled sections; absent abstracts omit
        # the key.
        return " ".join(article["Abstract"]["AbstractText"])
    except KeyError:
        return "<not found>"


def _parse_pubmed_article(
    pubmed_article: dict[str, Any],
    pmc_full_text_id: str | None,
    doi: str | None = None,
) -> dict[str, Any]:
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
    if recency_years <= 0:
        return
    from datetime import datetime

    current_year = datetime.now().year
    min_year = current_year - recency_years
    search_params["mindate"] = f"{min_year}/01/01"
    search_params["maxdate"] = f"{current_year}/12/31"
    search_params["datetype"] = "pdat"
    logger.debug(
        "applying recency filter: %s-%s (last %s years)",
        min_year,
        current_year,
        recency_years,
    )


class _EntrezClient:
    def __init__(self, qualified_path: Path):
        self.qualified_path = qualified_path

    def entrez_read(self, handle: Any) -> Any:
        return read_entrez(handle)

    def _fetch_pmc_fulltext_id(self, paper_id: str, doi: str) -> str | None:
        try:
            # Failed PMC lookup and successful no-link are equally unreadable
            # but distinct provenance.
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
        """Blocking Entrez requests and XML parsing must run off the event
        loop.
        """
        # Even single-ID efetch returns a PubmedArticleSet list.
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
        search_params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "sort": PUBMED_SEARCH_SORT,
        }
        _apply_recency_filter(search_params, recency_years)
        logger.debug("searching pubmed with sort=%s", PUBMED_SEARCH_SORT)
        results = self.entrez_read(entrez_call(Entrez.esearch, **search_params))
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
        ids = search_with_relaxation(
            query, retmax, recency_years, self._esearch_ids, trace
        )
        if not ids:
            logger.warning("No results found for query: %s", query)
        return ids

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from Bio import Entrez

from mcp_server.entrez import entrez_call, initialize_entrez, read_entrez
from mcp_server.pubmed_records import parse_pubmed_record

logger = logging.getLogger(__name__)

# Clamp the sufficiency threshold to retmax so tiny requests cannot force
# impossible relaxation.
MIN_RESULTS_BEFORE_RELAX = 3

# PubMed reserves uppercase AND/OR/NOT; lowercase forms are ordinary search terms
# (NCBI PubMed Help).
_BOOLEAN_OPERATORS = frozenset({"AND", "OR", "NOT"})

EsearchFn = Callable[[str, int, int], list[str]]


def _field_tagged_term(term: str) -> str:
    """Field tags bypass automatic term mapping, which silently splits
    unmatched phrases into ANDed words.
    """
    return f"({term}[tiab] OR {term}[mesh])"


# Two leading terms anchor the topic; one is broad, while three can reproduce
# zero-hit conjunctions.
_ANCHOR_TERMS = 2


def anchored_relaxed_query(query: str) -> str | None:
    """Leading terms carry the subject; relaxing them would answer a
    different question.
    """
    tokens = query.split()
    if any(token in _BOOLEAN_OPERATORS for token in tokens):
        return None
    if len(tokens) <= _ANCHOR_TERMS:
        return None
    anchors = " AND ".join(_field_tagged_term(term) for term in tokens[:_ANCHOR_TERMS])
    loosened = " OR ".join(_field_tagged_term(term) for term in tokens[_ANCHOR_TERMS:])
    return f"{anchors} AND ({loosened})"


def or_relaxed_query(query: str) -> str | None:
    tokens = query.split()
    if any(token in _BOOLEAN_OPERATORS for token in tokens):
        return None
    if len(tokens) < 2:
        return None
    return " OR ".join(_field_tagged_term(term) for term in tokens)


def relaxation_ladder(query: str, recency_years: int = 0) -> list[tuple[str, int]]:
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


def search_with_relaxation(
    query: str,
    retmax: int,
    recency_years: int,
    esearch: EsearchFn,
) -> list[str]:
    """Keep precise-rung hits when broader searches supply enough results;
    some evidence beats none.
    """
    threshold = min(MIN_RESULTS_BEFORE_RELAX, retmax)
    merged: list[str] = []
    for term, recency in relaxation_ladder(query, recency_years):
        ids = esearch(term, retmax, recency)
        merged.extend(i for i in dict.fromkeys(ids) if i not in merged)
        del merged[retmax:]
        if len(ids) >= threshold:
            return merged
    return merged


PUBMED_SEARCH_SORT = "pub_date"


initialize_entrez()


def _apply_recency_filter(search_params: dict[str, Any], recency_years: int) -> None:
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

    def _fetch_pmc_fulltext_id(self, paper_id: str, doi: str | None) -> str | None:
        try:
            # Failed PMC lookup and successful no-link are equally unreadable
            # but distinct provenance.
            related = self.entrez_read(
                entrez_call(Entrez.elink, dbfrom="pubmed", db="pmc", id=paper_id)
            )
        except Exception:
            logger.debug("fulltext not available in pmc")
            return None
        try:
            link_sets = related[0]["LinkSetDb"]
            if not link_sets or not link_sets[0].get("Link"):
                return None
            return str(link_sets[0]["Link"][0]["Id"])
        except (IndexError, KeyError, TypeError):
            logger.debug("fulltext not available in pmc")
            return None

    def _fetch_paper_details(self, paper_id: str) -> dict[str, Any] | None:
        """Blocking Entrez requests and XML parsing must run off the event
        loop.
        """
        # Even single-ID efetch returns a PubmedArticleSet list.
        results = self.entrez_read(entrez_call(Entrez.efetch, db="pubmed", id=paper_id))
        pubmed_articles = results.get("PubmedArticle") or []
        if not pubmed_articles:
            # Book records (StatPearls, GeneReviews) carry no journal metadata.
            return None
        pubmed_article = pubmed_articles[0]
        record = parse_pubmed_record(pubmed_article)
        pmc_id = self._fetch_pmc_fulltext_id(paper_id, record.doi)
        return record.fulltext_metadata(pmc_id)

    def _esearch_ids(self, query: str, retmax: int, recency_years: int) -> list[str]:
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
    ) -> list[str]:
        ids = search_with_relaxation(query, retmax, recency_years, self._esearch_ids)
        if not ids:
            logger.warning("PubMed search returned no results")
        return ids

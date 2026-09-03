"""Europe PMC search, including the preprint servers.

Europe PMC indexes PubMed's corpus plus preprints from bioRxiv, medRxiv
and others, which is why preprint search runs through here rather than
against biorxiv.org's own API: that API lists papers by posting date and
cannot be queried by subject at all, so it can answer "what appeared on
Tuesday" but never "what is known about WEE1".

Two tools rather than one because they answer different questions. The
general search wants the best evidence regardless of venue; the preprint
search deliberately restricts to what has *not* been peer reviewed,
which is where the last eighteen months of a fast-moving field lives and
where a novelty claim is most often wrong.
"""

import logging
from typing import Any

import httpx

from mcp_server.tools.text import clean_markup

logger = logging.getLogger(__name__)

_EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# Europe PMC's source code for preprint servers (bioRxiv, medRxiv, and
# the other servers it indexes).
_PREPRINT_FILTER = "SRC:PPR"

# Restricts the preprint filter above to bioRxiv specifically, for the
# composer's separate bioRxiv connector (distinct from the "every server
# Europe PMC indexes" preprint_search below). Verified live: the same
# query with an unknown PUBLISHER value returns zero hits, so this is a
# real filter Europe PMC applies, not an ignored, unrecognized field.
_BIORXIV_FILTER = 'PUBLISHER:"bioRxiv"'


def _empty_result(source: str, query: str) -> dict[str, Any]:
    """Builds the envelope a search returns when it cannot answer."""
    return {"source": source, "query": query, "records": []}


def _record(result: dict[str, Any]) -> dict[str, Any]:
    """Normalizes one Europe PMC result into a flat paper record."""
    doi = result.get("doi")
    pmid = result.get("pmid")
    # Europe PMC's own source/id pair, which every record carries -- a DOI
    # does not survive plenty of preprints. The engine re-keys a
    # list-shaped response by this field, and without it two queries'
    # results collide on list position and overwrite each other.
    record_id = f"{result.get('source', 'MED')}/{result.get('id')}"
    return {
        "source_id": record_id,
        # Europe PMC italicizes species and gene names, and sends that
        # markup escaped on some records and raw on others.
        "title": clean_markup(result.get("title")),
        "abstract": clean_markup(result.get("abstractText")),
        "year": result.get("pubYear"),
        "journal": (result.get("journalInfo") or {})
        .get("journal", {})
        .get("title")
        or result.get("bookOrReportDetails", {}).get("publisher"),
        "authors": result.get("authorString"),
        "doi": doi,
        "pmid": pmid,
        # Whether this is peer reviewed is a fact about the evidence, not
        # a detail of the record: a preprint supporting a claim is a
        # weaker citation and the model has to be able to say so.
        "is_preprint": result.get("source") == "PPR",
        "cited_by_count": result.get("citedByCount"),
        "url": (
            f"https://doi.org/{doi}"
            if doi
            else f"https://europepmc.org/article/{record_id}"
        ),
    }


async def _search(
    query: str, max_results: int, source_label: str, echo: str | None = None
) -> dict[str, Any]:
    """Runs one Europe PMC query and normalizes its results.

    Args:
        query: The query as Europe PMC receives it, filters included.
        max_results: Maximum records to return, capped at 25.
        source_label: The provenance stamp the envelope carries.
        echo: What the envelope reports as the query, when that differs
            from what was sent. The preprint search appends a source
            filter the caller never wrote, and echoing it back would put
            Europe PMC's own syntax in front of a model that then has to
            guess whether the filter was part of its question.

    Returns:
        The normalized envelope, empty-records on any failure.
    """
    limit = max(1, min(max_results, 25))
    asked = echo if echo is not None else query
    params: dict[str, str | int] = {
        "query": query,
        "format": "json",
        "pageSize": limit,
        "resultType": "core",
        # Most cited first would bury anything recent, and recency is the
        # reason to consult a preprint server at all; Europe PMC's own
        # relevance ranking is the compromise both tools want.
        "sort": "",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(_EUROPEPMC_URL, params=params)
            response.raise_for_status()
        results = (
            (response.json().get("resultList") or {}).get("result") or []
        )[:limit]
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Europe PMC search failed for %r: %s", query, exc)
        return _empty_result(source_label, asked)
    return {
        "source": source_label,
        "query": asked,
        "records": [_record(result) for result in results],
    }


async def search_europepmc(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search Europe PMC's full corpus of papers and preprints.

    Args:
        query: Free-text or Europe PMC query syntax.
        max_results: Maximum records to return, capped at 25.

    Returns:
        Source-stamped paper records, each flagged as preprint or not, or
        an empty-records envelope.
    """
    return await _search(query, max_results, "Europe PMC")


async def search_preprints(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search bioRxiv, medRxiv and other preprint servers.

    Args:
        query: Free-text or Europe PMC query syntax.
        max_results: Maximum records to return, capped at 25.

    Returns:
        Source-stamped preprint records, or an empty-records envelope.
    """
    return await _search(
        f"({query}) AND {_PREPRINT_FILTER}",
        max_results,
        "Preprints",
        echo=query,
    )


async def search_biorxiv(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search bioRxiv specifically, not the broader preprint set above.

    bioRxiv's own REST API lists papers by posting date and cannot be
    queried by subject at all (see the module docstring), so a genuine
    bioRxiv subject search has to run through Europe PMC too, restricted
    to this one publisher rather than every preprint server it indexes.

    Args:
        query: Free-text or Europe PMC query syntax.
        max_results: Maximum records to return, capped at 25.

    Returns:
        Source-stamped bioRxiv records, or an empty-records envelope.
    """
    return await _search(
        f"({query}) AND {_PREPRINT_FILTER} AND {_BIORXIV_FILTER}",
        max_results,
        "bioRxiv",
        echo=query,
    )

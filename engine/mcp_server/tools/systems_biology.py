"""Network, pathway and target-association lookups for systems biology.

Three sources that answer a question the literature cannot: what a
protein actually interacts with, which pathways it sits in, and what a
target is already associated with. They are entity-keyed rather than
free-text, which is why they are wired as context-enrichment and
reflection tools rather than as literature search sources.

Every call degrades to an empty-records envelope rather than raising, on
the same reasoning as ``biomedical_databases``: one unreachable source
must not fail the step that consults several.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_STRING_URL = "https://string-db.org/api/json/interaction_partners"
_REACTOME_SEARCH = "https://reactome.org/ContentService/search/query"
_REACTOME_PATHWAYS = "https://reactome.org/ContentService/data/pathways/low"
_OPENTARGETS_URL = "https://api.platform.opentargets.org/api/v4/graphql"

# Human. Every consumer of these tools is a human-biology run, and the
# APIs require a taxon rather than defaulting to one.
_HUMAN_TAXON = 9606


def _empty_result(source: str, query: str) -> dict[str, Any]:
    """Builds the envelope a lookup returns when it cannot answer."""
    return {"source": source, "query": query, "records": []}


def _capped(max_results: int) -> int:
    """Clamps a caller's result count to the range these APIs are polite at."""
    return max(1, min(max_results, 25))


async def search_string_interactions(
    query: str, max_results: int = 10
) -> dict[str, Any]:
    """Return the proteins a gene or protein is linked to.

    Args:
        query: A gene or protein symbol, e.g. "WEE1" or "SLC9A1".
        max_results: Maximum partners to return, capped at 25.

    Returns:
        Source-stamped interaction partners with STRING's combined score
        and its evidence channels, or an empty-records envelope.
    """
    limit = _capped(max_results)
    params: dict[str, str | int] = {
        "identifiers": query,
        "species": _HUMAN_TAXON,
        "limit": limit,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(_STRING_URL, params=params)
            response.raise_for_status()
        partners = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("STRING lookup failed for %r: %s", query, exc)
        return _empty_result("STRING", query)
    records = [
        {
            "partner": partner.get("preferredName_B"),
            "combined_score": partner.get("score"),
            # STRING's channels, kept separate because they mean different
            # things: a pair supported only by text mining is a weaker
            # claim than one with experimental support, and a single
            # combined score hides which it is.
            "experimental_score": partner.get("escore"),
            "database_score": partner.get("dscore"),
            "coexpression_score": partner.get("ascore"),
            "textmining_score": partner.get("tscore"),
            "url": f"https://string-db.org/network/{partner.get('stringId_B')}",
        }
        for partner in partners[:limit]
        if isinstance(partner, dict)
    ]
    return {"source": "STRING", "query": query, "records": records}


async def _reactome_entity(client: httpx.AsyncClient, query: str) -> str | None:
    """Resolves a gene or protein symbol to a Reactome entity id."""
    response = await client.get(
        _REACTOME_SEARCH,
        params={
            "query": query,
            "species": "Homo sapiens",
            "cluster": "true",
        },
    )
    response.raise_for_status()
    groups = response.json().get("results") or []
    entries = [
        entry
        for group in groups
        for entry in (group.get("entries") or [])
        if entry.get("exactType") == "ReferenceGeneProduct"
    ]
    return str(entries[0]["stId"]) if entries else None


async def search_reactome_pathways(
    query: str, max_results: int = 10
) -> dict[str, Any]:
    """Return the curated pathways a gene or protein participates in.

    Two calls rather than one: Reactome's free-text search returns the
    entity, and pathway membership is a separate lookup from it. Searching
    for the pathway name directly finds pathways *called* that, which is a
    different question from the one a mechanism needs answered.

    Args:
        query: A gene or protein symbol, e.g. "WEE1".
        max_results: Maximum pathways to return, capped at 25.

    Returns:
        Source-stamped pathway records, or an empty-records envelope.
    """
    limit = _capped(max_results)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            entity = await _reactome_entity(client, query)
            if entity is None:
                return _empty_result("Reactome", query)
            response = await client.get(
                f"{_REACTOME_PATHWAYS}/entity/{entity}/allForms",
                params={"species": str(_HUMAN_TAXON)},
            )
            response.raise_for_status()
        pathways = response.json()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Reactome lookup failed for %r: %s", query, exc)
        return _empty_result("Reactome", query)
    records = [
        {
            "pathway_id": pathway.get("stId"),
            "name": pathway.get("displayName"),
            "url": f"https://reactome.org/content/detail/{pathway.get('stId')}",
        }
        for pathway in pathways[:limit]
        if isinstance(pathway, dict)
    ]
    return {"source": "Reactome", "query": query, "records": records}


_OPENTARGETS_QUERY = """
query($q: String!, $n: Int!) {
  search(queryString: $q, entityNames: ["target"], page: {index: 0, size: 1}) {
    hits {
      id
      object {
        ... on Target {
          approvedSymbol
          approvedName
          associatedDiseases(page: {index: 0, size: $n}) {
            rows { score disease { id name } }
          }
          tractability { label modality value }
        }
      }
    }
  }
}
"""


def _tractable_modalities(tractability: list[dict[str, Any]]) -> list[str]:
    """Names the tractability buckets a target actually satisfies.

    Open Targets returns every bucket with a true/false flag; the false
    ones are the overwhelming majority and say nothing, so only the
    satisfied ones are carried to the model.
    """
    return [
        f"{entry.get('modality')}: {entry.get('label')}"
        for entry in tractability
        if isinstance(entry, dict) and entry.get("value")
    ]


async def search_open_targets(
    query: str, max_results: int = 10
) -> dict[str, Any]:
    """Return a target's disease associations and druggability.

    Args:
        query: A gene or protein symbol, e.g. "WEE1".
        max_results: Maximum disease associations to return, capped at 25.

    Returns:
        A single source-stamped target record carrying scored disease
        associations and the tractability buckets it satisfies, or an
        empty-records envelope.
    """
    limit = _capped(max_results)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                _OPENTARGETS_URL,
                json={
                    "query": _OPENTARGETS_QUERY,
                    "variables": {"q": query, "n": limit},
                },
            )
            response.raise_for_status()
        hits = (
            ((response.json().get("data") or {}).get("search") or {}).get(
                "hits"
            )
        ) or []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Open Targets lookup failed for %r: %s", query, exc)
        return _empty_result("Open Targets", query)
    if not hits:
        return _empty_result("Open Targets", query)
    return {
        "source": "Open Targets",
        "query": query,
        "records": [_open_targets_record(hits[0])],
    }


def _open_targets_record(hit: dict[str, Any]) -> dict[str, Any]:
    """Flattens one Open Targets search hit into a record."""
    target = hit.get("object") or {}
    associations = (target.get("associatedDiseases") or {}).get("rows") or []
    return {
        "ensembl_id": hit.get("id"),
        "symbol": target.get("approvedSymbol"),
        "name": target.get("approvedName"),
        "associated_diseases": [
            {
                "disease": (row.get("disease") or {}).get("name"),
                "score": row.get("score"),
            }
            for row in associations
            if isinstance(row, dict)
        ],
        "tractability": _tractable_modalities(target.get("tractability") or []),
        "url": f"https://platform.opentargets.org/target/{hit.get('id')}",
    }

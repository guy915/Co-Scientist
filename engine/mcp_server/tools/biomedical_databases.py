"""Direct ChEMBL and UniProt retrieval tools for biomedical grounding."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CHEMBL_URL = "https://www.ebi.ac.uk/chembl/api/data"
_UNIPROT_URL = "https://rest.uniprot.org/uniprotkb/search"


def _response_records(
    response: httpx.Response, field: str
) -> list[dict[str, Any]]:
    """Reads a provider's list of records, rejecting malformed JSON shapes.

    Args:
        response: A successful HTTP response from a biomedical provider.
        field: The top-level JSON key containing records.

    Returns:
        A list of record objects, or an empty list when there are no hits.

    Raises:
        ValueError: If the response is not a JSON object with a record list.
    """
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    if field not in payload:
        raise ValueError("response omitted its record list")
    records = payload[field]
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise ValueError("expected a list of JSON objects")
    return records


def _failure_result(
    source: str, query: str, exc: Exception, provider_name: str
) -> dict[str, Any]:
    """Returns an empty, non-fatal envelope with safe failure metadata.

    Args:
        source: The provenance stamp a successful call would carry.
        query: The original search text.
        exc: The HTTP or response parsing error.
        provider_name: Human-readable name used in the warning log.

    Returns:
        The usual result envelope with a non-secret ``error`` object.
    """
    if isinstance(exc, httpx.TimeoutException):
        error: dict[str, Any] = {"kind": "timeout"}
    elif isinstance(exc, httpx.HTTPStatusError):
        error = {
            "kind": "http_status",
            "status_code": exc.response.status_code,
        }
    elif isinstance(
        exc, (ValueError, TypeError, AttributeError, KeyError, IndexError)
    ):
        error = {"kind": "invalid_response"}
    else:
        error = {"kind": "network_error"}

    logger.warning(
        "%s search failed for %r (%s)", provider_name, query, error["kind"]
    )
    return {"source": source, "query": query, "records": [], "error": error}


def _chembl_record(molecule: dict[str, Any]) -> dict[str, Any]:
    """Normalize one ChEMBL molecule into a flat record."""
    chembl_id = molecule.get("molecule_chembl_id")
    return {
        "chembl_id": chembl_id,
        "name": molecule.get("pref_name"),
        "type": molecule.get("molecule_type"),
        "max_phase": molecule.get("max_phase"),
        "first_approval": molecule.get("first_approval"),
        "url": f"https://www.ebi.ac.uk/chembl/explore/compound/{chembl_id}",
    }


async def search_chembl(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search ChEMBL molecules and return normalized drug records.

    Args:
        query: Molecule, synonym, target, or indication search text.
        max_results: Maximum records to return, capped at 25.

    Returns:
        Source-stamped ChEMBL molecule records, or an empty-records envelope
        with non-secret error metadata if the request fails.
    """
    limit = max(1, min(max_results, 25))
    params: dict[str, str | int] = {
        "q": query,
        "limit": limit,
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{_CHEMBL_URL}/molecule/search.json", params=params
            )
            response.raise_for_status()
        molecules = _response_records(response, "molecules")
        records = [_chembl_record(molecule) for molecule in molecules[:limit]]
    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        IndexError,
    ) as exc:
        # Network/parsing failures degrade to no results rather than
        # propagating, so a single failed source doesn't fail the whole
        # literature-review step.
        return _failure_result("ChEMBL", query, exc, "ChEMBL")
    return {"source": "ChEMBL", "query": query, "records": records}


def _uniprot_record(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize one UniProtKB result into a flat record.

    Args:
        result: A single entry from the UniProt search response.

    Returns:
        A record with accession, gene, protein name, organism, functional
        summaries, and the entry URL.
    """
    genes = result.get("genes") or []
    primary_gene = (
        (genes[0].get("geneName") or {}).get("value") if genes else None
    )
    protein = result.get("proteinDescription") or {}
    recommended = protein.get("recommendedName") or {}
    protein_name = (recommended.get("fullName") or {}).get("value")
    return {
        "accession": result.get("primaryAccession"),
        "gene": primary_gene,
        "protein_name": protein_name,
        "organism": (result.get("organism") or {}).get("scientificName"),
        "functions": [
            comment.get("texts", [{}])[0].get("value")
            for comment in result.get("comments") or []
            if comment.get("commentType") == "FUNCTION" and comment.get("texts")
        ],
        "url": (
            "https://www.uniprot.org/uniprotkb/"
            f"{result.get('primaryAccession')}/entry"
        ),
    }


async def search_uniprot(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search reviewed UniProtKB protein records with functional summaries.

    Args:
        query: UniProt query syntax or free-text protein/gene search.
        max_results: Maximum records to return, capped at 25.

    Returns:
        Source-stamped reviewed protein records, or an empty-records envelope
        with non-secret error metadata if the request fails.
    """
    limit = max(1, min(max_results, 25))
    params: dict[str, str | int] = {
        "query": f"({query}) AND reviewed:true",
        "size": limit,
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(_UNIPROT_URL, params=params)
            response.raise_for_status()
        results = _response_records(response, "results")[:limit]
        records = [_uniprot_record(result) for result in results]
    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        IndexError,
    ) as exc:
        # Network/parsing failures degrade to no results rather than
        # propagating, so a single failed source doesn't fail the whole
        # literature-review step.
        return _failure_result("UniProtKB/Swiss-Prot", query, exc, "UniProt")
    return {
        "source": "UniProtKB/Swiss-Prot",
        "query": query,
        "records": records,
    }

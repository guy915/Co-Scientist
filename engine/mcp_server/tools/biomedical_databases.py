"""Direct ChEMBL and UniProt retrieval tools for biomedical grounding."""

from typing import Any

import httpx

_CHEMBL_URL = "https://www.ebi.ac.uk/chembl/api/data"
_UNIPROT_URL = "https://rest.uniprot.org/uniprotkb/search"


async def search_chembl(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search ChEMBL molecules and return normalized drug records.

    Args:
        query: Molecule, synonym, target, or indication search text.
        max_results: Maximum records to return, capped at 25.

    Returns:
        Source-stamped ChEMBL molecule records and response provenance.
    """
    limit = max(1, min(max_results, 25))
    params: dict[str, str | int] = {
        "q": query,
        "limit": limit,
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{_CHEMBL_URL}/molecule/search.json", params=params
        )
        response.raise_for_status()
    molecules = response.json().get("molecules") or []
    records = [
        {
            "chembl_id": molecule.get("molecule_chembl_id"),
            "name": molecule.get("pref_name"),
            "type": molecule.get("molecule_type"),
            "max_phase": molecule.get("max_phase"),
            "first_approval": molecule.get("first_approval"),
            "url": (
                "https://www.ebi.ac.uk/chembl/explore/compound/"
                f"{molecule.get('molecule_chembl_id')}"
            ),
        }
        for molecule in molecules[:limit]
    ]
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
        Source-stamped reviewed protein records and response provenance.
    """
    limit = max(1, min(max_results, 25))
    params: dict[str, str | int] = {
        "query": f"({query}) AND reviewed:true",
        "size": limit,
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(_UNIPROT_URL, params=params)
        response.raise_for_status()
    results = (response.json().get("results") or [])[:limit]
    records = [_uniprot_record(result) for result in results]
    return {
        "source": "UniProtKB/Swiss-Prot",
        "query": query,
        "records": records,
    }

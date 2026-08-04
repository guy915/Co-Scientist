"""Drug target, indication, side effect, and clinical trial queries."""

import logging
from typing import Any

from mcp_server.tools.indra_cogex.client import (
    cap_results,
    indra_post,
    parse_id,
    run_indra_tool,
    tool_error,
)

logger = logging.getLogger(__name__)

# Maps query_type -> (endpoint, param_name, result_key)
_DRUG_ENDPOINTS = {
    "targets": ("/api/get_targets_for_drug", "drug", "targets"),
    "drugs_for_target": ("/api/get_drugs_for_target", "target", "drugs"),
    "indications": ("/api/get_indications_for_drug", "molecule", "indications"),
    "side_effects": ("/api/get_side_effects_for_drug", "drug", "side_effects"),
}


async def query_drug_info(
    identifier: str,
    query_type: str = "targets",
    max_results: int = 50,
) -> dict[str, Any]:
    """Queries drug-related information from the INDRA knowledge graph.

    Looks up drug targets (proteins), drugs for a protein target,
    therapeutic indications, or known side effects.

    Args:
        identifier: Entity in "NAMESPACE:id" format.
            For drugs: "CHEBI:CHEBI:27690" (metformin), "CHEBI:CHEBI:90227"
                (sotorasib)
            For protein targets: "HGNC:6407" (KRAS), "HGNC:3236" (EGFR)
        query_type: What to query:
            "targets" - protein targets of this drug (identifier=drug)
            "drugs_for_target" - drugs targeting this protein (identifier=gene)
            "indications" - therapeutic uses of this drug (identifier=drug)
            "side_effects" - known side effects (identifier=drug)
        max_results: Max results to return (default 50).

    Returns:
        Dict with query results and metadata.
    """
    return await run_indra_tool(
        logger,
        "query_drug_info",
        {"identifier": identifier, "query_type": query_type},
        _run_drug_query(identifier, query_type, max_results),
    )


async def _run_drug_query(
    identifier: str,
    query_type: str,
    max_results: int,
) -> dict[str, Any]:
    """Resolves a drug query against the _DRUG_ENDPOINTS dispatch table.

    Args:
        identifier: Entity in "NAMESPACE:id" format.
        query_type: Key into _DRUG_ENDPOINTS selecting the CoGex endpoint.
        max_results: Max results to return.

    Returns:
        Dict with query results and metadata, or an error payload for an
        unknown query_type.
    """
    curie = parse_id(identifier)
    query_meta = {"identifier": identifier, "query_type": query_type}
    if query_type not in _DRUG_ENDPOINTS:
        valid = ", ".join(_DRUG_ENDPOINTS.keys())
        return tool_error(
            f"invalid query_type '{query_type}', use: {valid}", query_meta
        )

    result: dict[str, Any] = {"query": query_meta}
    # Generic dispatch: look up the CoGex endpoint, the payload key it
    # expects the entity under, and the key to store results under.
    endpoint, param_name, result_key = _DRUG_ENDPOINTS[query_type]
    raw = await indra_post(endpoint, {param_name: curie})
    items, total = cap_results(raw, max_results)
    result[result_key] = items
    result[f"total_{result_key}"] = total
    return result


async def query_clinical_trials(
    identifier: str,
    entity_type: str = "disease",
    max_results: int = 50,
) -> dict[str, Any]:
    """Queries clinical trial data from the INDRA knowledge graph.

    Finds clinical trials associated with a specific disease or drug.

    Args:
        identifier: Entity in "NAMESPACE:id" format.
            Diseases: "DOID:162" (cancer), "MESH:D000544" (Alzheimer disease)
            Drugs: "CHEBI:CHEBI:27690" (metformin)
        entity_type: "disease" or "drug".
        max_results: Max trials to return (default 50).

    Returns:
        Dict with clinical trials and metadata.
    """
    return await run_indra_tool(
        logger,
        "query_clinical_trials",
        {"identifier": identifier, "entity_type": entity_type},
        _run_clinical_trials(identifier, entity_type, max_results),
    )


async def _run_clinical_trials(
    identifier: str,
    entity_type: str,
    max_results: int,
) -> dict[str, Any]:
    """Fetches clinical trials for a disease or drug from INDRA.

    Args:
        identifier: Entity in "NAMESPACE:id" format.
        entity_type: "disease" or "drug".
        max_results: Max trials to return.

    Returns:
        Dict with clinical trials and metadata, or an error payload for an
        invalid entity_type.
    """
    curie = parse_id(identifier)
    query_meta = {"identifier": identifier, "entity_type": entity_type}
    if entity_type == "disease":
        # Trials that study this disease/condition.
        raw = await indra_post(
            "/api/get_trials_for_disease", {"disease": curie}
        )
    elif entity_type == "drug":
        # Trials that test this drug as an intervention.
        raw = await indra_post("/api/get_trials_for_drug", {"drug": curie})
    else:
        entity_err = f"invalid entity_type '{entity_type}'"
        return tool_error(f"{entity_err}, use 'disease' or 'drug'", query_meta)

    trials, total = cap_results(raw, max_results)
    return {
        "trials": trials,
        "total_trials": total,
        "query": query_meta,
    }

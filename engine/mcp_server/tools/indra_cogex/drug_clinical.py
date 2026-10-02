"""Drug target, indication, side effect, and clinical trial queries."""

import logging
from typing import Any

from mcp_server.tools.indra_cogex.client import (
    cap_results,
    indra_post,
    parse_id,
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
    query_meta = {"identifier": identifier, "query_type": query_type}
    try:
        curie = parse_id(identifier)
        if query_type not in _DRUG_ENDPOINTS:
            valid = ", ".join(_DRUG_ENDPOINTS)
            return tool_error(
                f"invalid query_type '{query_type}', use: {valid}", query_meta
            )
        endpoint, param_name, result_key = _DRUG_ENDPOINTS[query_type]
        raw = await indra_post(endpoint, {param_name: curie})
        items, total = cap_results(raw, max_results)
        return {
            result_key: items,
            f"total_{result_key}": total,
            "query": query_meta,
        }
    except Exception as exc:
        logger.error("query_drug_info failed: %s", exc)
        return tool_error(str(exc), query_meta)


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
    query_meta = {"identifier": identifier, "entity_type": entity_type}
    try:
        curie = parse_id(identifier)
        if entity_type not in ("disease", "drug"):
            return tool_error(
                f"invalid entity_type '{entity_type}', use 'disease' or 'drug'",
                query_meta,
            )
        raw = await indra_post(
            f"/api/get_trials_for_{entity_type}", {entity_type: curie}
        )
        trials, total = cap_results(raw, max_results)
        return {"trials": trials, "total_trials": total, "query": query_meta}
    except Exception as exc:
        logger.error("query_clinical_trials failed: %s", exc)
        return tool_error(str(exc), query_meta)

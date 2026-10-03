"""INDRA CoGex knowledge graph queries and shared HTTP client."""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Public INDRA CoGex REST deployment; override via env var to point at a
# local or self-hosted instance.
INDRA_BASE_URL = os.getenv("INDRA_COGEX_URL", "https://discovery.indra.bio")
# Some CoGex queries (e.g. enrichment, subnetwork search) run slow graph
# traversals server-side, hence the generous default timeout.
INDRA_TIMEOUT = float(os.getenv("INDRA_COGEX_TIMEOUT", "120"))


def parse_id(identifier: str) -> list[str]:
    """Parses 'NAMESPACE:id' into [namespace, id] for the INDRA API.

    Examples:
        "HGNC:6407" -> ["HGNC", "6407"]
        "MESH:D002289" -> ["MESH", "D002289"]
        "CHEBI:CHEBI:27690" -> ["CHEBI", "CHEBI:27690"]

    Args:
        identifier: Entity identifier string in NAMESPACE:id format.

    Returns:
        Two-element list [namespace, id].

    Raises:
        ValueError: If the identifier is not in a valid NAMESPACE:id format.
    """
    # Split on the first ":" only, since some ids (e.g.
    # "CHEBI:CHEBI:27690") contain additional colons that belong to the
    # id portion.
    parts = identifier.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"invalid identifier: '{identifier}'. "
            f"expected 'NAMESPACE:id' (e.g. 'HGNC:6407')"
        )
    return parts


def maybe_parse_agent(value: str) -> str | list[str]:
    """Parses value as CURIE tuple if it contains ':', otherwise returns as-is.

    The INDRA get_statements endpoint accepts both plain names ("KRAS")
    and CURIE tuples (["HGNC", "6407"]).

    Args:
        value: Agent name or CURIE string.

    Returns:
        A two-element list [namespace, id] if parseable as CURIE, else the
        original string.
    """
    # A colon usually signals a CURIE ("HGNC:6407"), but URLs also contain
    # colons ("http://...") and are not identifiers, so exclude them.
    if ":" in value and not value.startswith("http"):
        try:
            return parse_id(value)
        except ValueError:
            return value
    return value


async def indra_post(endpoint: str, payload: dict[str, Any]) -> Any:
    """POSTs to the INDRA CoGex API and returns parsed JSON.

    Args:
        endpoint: API path, e.g. "/api/get_genes_for_disease".
        payload: JSON-serializable request body.

    Returns:
        Parsed JSON response from the API.
    """
    url = f"{INDRA_BASE_URL}{endpoint}"
    logger.debug("indra request: %s", endpoint)
    # A fresh client per call keeps each tool invocation independent;
    # CoGex calls are infrequent enough that connection reuse isn't worth
    # the added lifecycle complexity here.
    async with httpx.AsyncClient(timeout=INDRA_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def tool_error(message: str, query_meta: dict[str, Any]) -> dict[str, Any]:
    """Builds the payload every CoGex tool returns when it cannot answer.

    Args:
        message: Human-readable failure description.
        query_meta: The same query metadata a successful response echoes, so
            a caller can identify the request whatever the outcome.

    Returns:
        Dict with "error" and "query" keys.
    """
    return {"error": message, "query": query_meta}


def cap_results(items: list[Any] | Any, limit: int) -> tuple[list[Any], int]:
    """Caps a list at limit and returns (capped_list, original_count).

    Args:
        items: List to cap, or any non-list value.
        limit: Maximum number of items to return.

    Returns:
        Tuple of (capped list, original total count). If items is not a list,
        returns (items, 0).
    """
    # Some CoGex endpoints return an error dict instead of a list; pass it
    # through unchanged rather than truncating or raising.
    if not isinstance(items, list):
        return items, 0
    total = len(items)
    return items[:limit], total


async def query_gene_disease_network(
    identifier: str,
    entity_type: str = "disease",
    include_variants: bool = False,
    max_results: int = 50,
) -> dict[str, Any]:
    """Queries gene-disease-variant associations from INDRA's knowledge graph.

    Given a disease, find associated genes (and optionally genetic variants).
    Given a gene, find associated diseases (and optionally genetic variants).

    Args:
        identifier: Entity in "NAMESPACE:id" format.
            Diseases: "DOID:162" (cancer), "MESH:D000544" (Alzheimer disease),
                "MESH:D002289" (non-small cell lung carcinoma)
            Genes: "HGNC:6407" (KRAS), "HGNC:3236" (EGFR),
                "HGNC:11730" (TREM2)
        entity_type: "disease" to find genes for a disease, "gene" to find
            diseases for a gene.
        include_variants: Also return associated genetic variants.
        max_results: Max results per category (default 50).

    Returns:
        Dict with associated entities, counts, and query metadata.
    """
    query_meta = {"identifier": identifier, "entity_type": entity_type}
    try:
        curie = parse_id(identifier)
        if entity_type not in ("disease", "gene"):
            return tool_error(
                f"invalid entity_type '{entity_type}', use 'disease' or 'gene'",
                query_meta,
            )
        result: dict[str, Any] = {"query": query_meta}
        result_key = "genes" if entity_type == "disease" else "diseases"
        raw = await indra_post(
            f"/api/get_{result_key}_for_{entity_type}", {entity_type: curie}
        )
        result[result_key], result[f"total_{result_key}"] = cap_results(
            raw, max_results
        )
        if include_variants:
            raw = await indra_post(
                f"/api/get_variants_for_{entity_type}", {entity_type: curie}
            )
            result["variants"], result["total_variants"] = cap_results(
                raw, max_results
            )
        return result
    except Exception as exc:
        logger.error("query_gene_disease_network failed: %s", exc)
        return tool_error(str(exc), query_meta)


async def query_gene_codependents(
    gene_id: str,
    max_results: int = 50,
) -> dict[str, Any]:
    """Finds genes codependent with a given gene from DepMap CRISPR screens.

    Codependent genes are functionally linked: when one is essential in a cell
    line, the other tends to be too. Useful for discovering synthetic lethal
    targets and functional gene networks in cancer research.

    Args:
        gene_id: Gene in "HGNC:id" format.
            Examples: "HGNC:6407" (KRAS), "HGNC:3236" (EGFR),
                "HGNC:1097" (BRAF)
        max_results: Max codependent genes to return (default 50).

    Returns:
        Dict with codependent genes and counts.
    """
    query_meta = {"gene_id": gene_id}
    try:
        raw = await indra_post(
            "/api/get_codependents_for_gene", {"gene": parse_id(gene_id)}
        )
        genes, total = cap_results(raw, max_results)
        return {
            "codependent_genes": genes,
            "total_codependents": total,
            "query": query_meta,
        }
    except Exception as exc:
        logger.error("query_gene_codependents failed: %s", exc)
        return tool_error(str(exc), query_meta)


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


async def run_enrichment_analysis(
    gene_list: list[str],
    analysis_type: str = "discrete",
    alpha: float = 0.05,
    negative_genes: list[str] | None = None,
    keep_insignificant: bool = False,
    minimum_evidence_count: int = 1,
    minimum_belief: float = 0.0,
) -> dict[str, Any]:
    """Runs statistical enrichment analysis on gene/phosphosite sets via INDRA.

    Analysis types:
    - "discrete": over-representation analysis on a gene list.
    - "signed": reverse causal reasoning on up/down-regulated genes.
    - "kinase": kinase enrichment on phosphosite data.

    Args:
        gene_list: Gene identifiers. Discrete/signed: HGNC IDs. Kinase:
            phosphosites as "GENE-SITE" (e.g. "MAPK1-Y187").
        analysis_type: "discrete", "signed", or "kinase".
        alpha: Significance threshold (default 0.05).
        negative_genes: Downregulated genes (required for signed only).
        keep_insignificant: Include non-significant results (default False).
        minimum_evidence_count: Min supporting evidence (default 1).
        minimum_belief: Min belief score threshold (default 0.0).

    Returns:
        Dict with enrichment results and metadata.
    """
    query_meta = {"analysis_type": analysis_type, "gene_count": len(gene_list)}
    if analysis_type == "signed" and not negative_genes:
        return tool_error(
            "signed analysis requires 'negative_genes'", query_meta
        )
    if analysis_type not in ("discrete", "signed", "kinase"):
        return tool_error(
            f"invalid analysis_type '{analysis_type}', "
            "use: discrete, signed, kinase",
            query_meta,
        )

    payload: dict[str, Any] = {
        "alpha": alpha,
        "keep_insignificant": keep_insignificant,
        "minimum_evidence_count": minimum_evidence_count,
        "minimum_belief": minimum_belief,
    }
    gene_key = {
        "discrete": "gene_list",
        "signed": "positive_genes",
        "kinase": "phosphosite_list",
    }[analysis_type]
    payload[gene_key] = gene_list
    if analysis_type == "signed":
        payload["negative_genes"] = negative_genes
    try:
        raw = await indra_post(f"/api/{analysis_type}_analysis", payload)
        return {"results": raw, "query": query_meta}
    except Exception as exc:
        logger.error("run_enrichment_analysis failed: %s", exc)
        return tool_error(str(exc), query_meta)


async def query_pathways(
    gene_ids: list[str],
    max_results: int = 50,
) -> dict[str, Any]:
    """Queries biological pathways for genes from the INDRA knowledge graph.

    For a single gene, returns all pathways containing that gene.
    For multiple genes, returns shared pathways across all of them.

    Args:
        gene_ids: One or more gene identifiers in "HGNC:id" format.
            Single: ["HGNC:6407"] for KRAS pathways.
            Multiple: ["HGNC:6407", "HGNC:1097"] for shared KRAS/BRAF pathways.
        max_results: Max pathways to return (default 50).

    Returns:
        Dict with pathways and metadata.
    """
    query_meta = {"gene_ids": gene_ids}
    try:
        curies = [parse_id(gene_id) for gene_id in gene_ids]
        if len(curies) == 1:
            raw = await indra_post(
                "/api/get_pathways_for_gene", {"gene": curies[0]}
            )
        else:
            raw = await indra_post(
                "/api/get_shared_pathways_for_genes", {"genes": curies}
            )
        pathways, total = cap_results(raw, max_results)
        return {
            "pathways": pathways,
            "total_pathways": total,
            "query": {
                **query_meta,
                "mode": "shared" if len(curies) > 1 else "single",
            },
        }
    except Exception as exc:
        logger.error("query_pathways failed: %s", exc)
        return tool_error(str(exc), query_meta)


async def query_causal_subnetwork(
    node_ids: list[str],
    find_mediators: bool = True,
    max_results: int = 50,
) -> dict[str, Any]:
    """Queries causal subnetwork between biological entities from INDRA.

    Finds mechanistic connections between entities. When find_mediators is
    True, discovers intermediate nodes X such that A -> X -> B, revealing
    indirect regulatory pathways.

    Args:
        node_ids: Two or more entity identifiers in "NAMESPACE:id" format.
            E.g. ["HGNC:6407", "HGNC:5173"] to find paths between KRAS and
            HRAS. Supports genes (HGNC), protein families (FPLX), etc.
        find_mediators: If True (default), find mediated pathways (A -> X -> B).
            If False, return direct relations between the given nodes.
        max_results: Max relations to return (default 50).

    Returns:
        Dict with subnetwork relations and metadata.
    """
    query_meta = {"node_ids": node_ids}
    try:
        curies = [parse_id(node_id) for node_id in node_ids]
        if find_mediators:
            raw = await indra_post(
                "/api/indra_mediated_subnetwork",
                {"nodes": curies, "order_by_ev_count": True},
            )
        else:
            raw = await indra_post(
                "/api/indra_subnetwork_relations",
                {"nodes": curies, "include_db_evidence": True},
            )
        items, total = cap_results(raw, max_results)
        return {
            "subnetwork": items,
            "total_relations": total,
            "query": {**query_meta, "find_mediators": find_mediators},
        }
    except Exception as exc:
        logger.error("query_causal_subnetwork failed: %s", exc)
        return tool_error(str(exc), query_meta)


async def query_mechanistic_statements(
    agent: str | None = None,
    other_agent: str | None = None,
    relation_types: list[str] | None = None,
    agent_role: str | None = None,
    mesh_term: str | None = None,
    limit: int = 30,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    """Queries INDRA mechanistic statements from curated biomedical knowledge.

    INDRA statements are structured causal claims extracted from scientific
    papers. Query by agent name(s) (plain names like "KRAS" or CURIEs like
    "HGNC:6407"), or by a MeSH disease/topic term.

    Args:
        agent: Gene, protein, or drug name, or a "NAMESPACE:id" identifier.
        other_agent: Second entity to find relationships between.
        relation_types: Filter by relation type(s), e.g. Activation,
            Inhibition, Phosphorylation, IncreaseAmount, Complex.
        agent_role: "subject" or "object" to constrain the agent's role.
        mesh_term: MeSH disease/topic ID in "MESH:id" format, e.g.
            "MESH:D002289" (lung neoplasms).
        limit: Max statements to return (default 30).
        evidence_limit: Max evidence entries per statement (default 5).

    Returns:
        Dict with mechanistic statements, evidence, and metadata.
    """
    query_meta = {
        "agent": agent,
        "other_agent": other_agent,
        "mesh_term": mesh_term,
        "relation_types": relation_types,
    }
    try:
        if mesh_term:
            # MeSH descendants and curated database evidence are included.
            raw = await indra_post(
                "/api/get_stmts_for_mesh",
                {
                    "mesh_term": parse_id(mesh_term),
                    "include_child_terms": True,
                    "evidence_limit": evidence_limit,
                    "include_db_evidence": True,
                },
            )
        elif agent:
            # An omitted filter differs from a present-but-empty one in CoGex.
            payload: dict[str, Any] = {
                "agent": maybe_parse_agent(agent),
                "limit": limit,
                "evidence_limit": evidence_limit,
            }
            if other_agent:
                payload["other_agent"] = maybe_parse_agent(other_agent)
            payload.update(
                {
                    key: value
                    for key, value in (
                        ("rel_types", relation_types),
                        ("agent_role", agent_role),
                    )
                    if value
                }
            )
            raw = await indra_post("/api/get_statements", payload)
        else:
            return tool_error(
                "provide either 'agent' or 'mesh_term'", query_meta
            )
        statements, total = cap_results(raw, limit)
        return {
            "statements": statements,
            "total_statements": total,
            "query": query_meta,
        }
    except Exception as exc:
        logger.error("query_mechanistic_statements failed: %s", exc)
        return tool_error(str(exc), query_meta)

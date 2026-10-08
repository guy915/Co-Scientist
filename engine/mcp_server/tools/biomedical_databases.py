import logging
import re
from datetime import datetime, timezone
from typing import Any, TypedDict, Unpack

import httpx

from mcp_server.http_client import make_client
from mcp_server.tools import _results
from mcp_server.tools._pacing import RequestPacer

logger = logging.getLogger(__name__)

_CHEMBL_URL = "https://www.ebi.ac.uk/chembl/api/data"
_UNIPROT_URL = "https://rest.uniprot.org/uniprotkb/search"


class _GetOptions(TypedDict, total=False):
    params: dict[str, str | int]
    headers: dict[str, str]


async def _get_json(url: str, **options: Unpack[_GetOptions]) -> Any:
    async with make_client(30) as client:
        response = await client.get(url, **options)
        response.raise_for_status()
    return response.json()


def _response_records(payload: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    if field not in payload:
        raise ValueError("response omitted its record list")
    records = payload[field]
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError("expected a list of JSON objects")
    return records


# Unreachable, refused and malformed answers all fail the lookup, never empty it.
_LOOKUP_ERRORS = (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError, IndexError)


def _failed_lookup(source: str, query: str, exc: Exception) -> dict[str, Any]:
    error = _results.failure(exc)
    logger.warning("%s lookup failed for %r (%s)", source, query, error["detail"])
    return _results.failed_records(source, query, error)


def _chembl_record(molecule: dict[str, Any]) -> dict[str, Any]:
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
        payload = await _get_json(f"{_CHEMBL_URL}/molecule/search.json", params=params)
        molecules = _response_records(payload, "molecules")
        records = [_chembl_record(molecule) for molecule in molecules[:limit]]
    except _LOOKUP_ERRORS as exc:
        # Per-source network/parsing failure must not abort the whole literature
        # review.
        return _failed_lookup("ChEMBL", query, exc)
    return {"source": "ChEMBL", "query": query, "records": records}


def _uniprot_record(result: dict[str, Any]) -> dict[str, Any]:
    genes = result.get("genes") or []
    primary_gene = (genes[0].get("geneName") or {}).get("value") if genes else None
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
        "url": (f"https://www.uniprot.org/uniprotkb/{result.get('primaryAccession')}/entry"),
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
        payload = await _get_json(_UNIPROT_URL, params=params)
        results = _response_records(payload, "results")[:limit]
        records = [_uniprot_record(result) for result in results]
    except _LOOKUP_ERRORS as exc:
        # Per-source network/parsing failure must not abort the whole literature
        # review.
        return _failed_lookup("UniProtKB/Swiss-Prot", query, exc)
    return {
        "source": "UniProtKB/Swiss-Prot",
        "query": query,
        "records": records,
    }


_TRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"


def _record(study: dict[str, Any]) -> dict[str, Any]:
    """Missing ClinicalTrials v2 modules are ordinary, so lookups tolerate
    absence.
    """
    protocol = study.get("protocolSection") or {}
    identification = protocol.get("identificationModule") or {}
    status = protocol.get("statusModule") or {}
    design = protocol.get("designModule") or {}
    conditions = protocol.get("conditionsModule") or {}
    arms = protocol.get("armsInterventionsModule") or {}
    nct_id = identification.get("nctId")
    return {
        "nct_id": nct_id,
        "title": identification.get("briefTitle"),
        # Withdrawn/terminated trials are negative evidence least likely to
        # appear in publications.
        "status": status.get("overallStatus"),
        "why_stopped": status.get("whyStopped"),
        "phases": design.get("phases"),
        "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
        "conditions": conditions.get("conditions"),
        "interventions": [
            intervention.get("name")
            for intervention in (arms.get("interventions") or [])
            if isinstance(intervention, dict)
        ],
        "start_date": (status.get("startDateStruct") or {}).get("date"),
        "url": f"https://clinicaltrials.gov/study/{nct_id}",
    }


async def search_clinical_trials(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search registered clinical trials by intervention, condition or term.

    Args:
        query: An intervention, condition, or free-text search term.
        max_results: Maximum studies to return, capped at 25.

    Returns:
        Source-stamped trial records carrying status and, where a trial
        stopped early, why -- or an empty-records envelope, with non-secret
        error metadata if the lookup fails.
    """
    limit = max(1, min(max_results, 25))
    params: dict[str, str | int] = {
        "query.term": query,
        "pageSize": limit,
        "format": "json",
    }
    try:
        payload = await _get_json(_TRIALS_URL, params=params)
        studies = (payload.get("studies") or [])[:limit]
        records = [_record(study) for study in studies]
    except _LOOKUP_ERRORS as exc:
        return _failed_lookup("ClinicalTrials.gov", query, exc)
    return _results.records("ClinicalTrials.gov", query, records)


_ENSEMBL_URL = "https://rest.ensembl.org/lookup/symbol/homo_sapiens"
_GNOMAD_URL = "https://gnomad.broadinstitute.org/api"


async def search_ensembl_gene(query: str, max_results: int = 1) -> dict[str, Any]:
    """Resolve a gene symbol to its canonical Ensembl record.

    Args:
        query: A human gene symbol, e.g. "WEE1".
        max_results: Unused -- a symbol resolves to one gene. Accepted so
            every search tool shares one parameter mapping.

    Returns:
        A source-stamped record with the stable id, locus, biotype and
        description, or an empty-records envelope (an unknown symbol), with
        non-secret error metadata if the lookup fails.
    """
    del max_results
    try:
        gene = await _get_json(
            f"{_ENSEMBL_URL}/{query}",
            headers={"Content-Type": "application/json"},
        )
        if not isinstance(gene, dict):
            raise ValueError("expected a JSON object")
    except httpx.HTTPStatusError as exc:
        # Ensembl answers an unknown symbol with 404: that is no match, not an outage.
        if exc.response.status_code == 404:
            return _results.records("Ensembl", query, [])
        return _failed_lookup("Ensembl", query, exc)
    except _LOOKUP_ERRORS as exc:
        return _failed_lookup("Ensembl", query, exc)
    record = {
        "ensembl_id": gene.get("id"),
        "symbol": gene.get("display_name"),
        "biotype": gene.get("biotype"),
        "description": gene.get("description"),
        "locus": (f"{gene.get('seq_region_name')}:{gene.get('start')}-{gene.get('end')}"),
        "strand": gene.get("strand"),
        "url": f"https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={gene.get('id')}",
    }
    return _results.records("Ensembl", query, [record])


_GNOMAD_QUERY = """
query($symbol: String!) {
  gene(gene_symbol: $symbol, reference_genome: GRCh38) {
    gene_id
    symbol
    gnomad_constraint {
      pli
      oe_lof
      oe_lof_lower
      oe_lof_upper
      mis_z
    }
  }
}
"""


async def search_gnomad_constraint(query: str, max_results: int = 1) -> dict[str, Any]:
    """Return how strongly a gene is depleted of damaging variation.

    Args:
        query: A human gene symbol, e.g. "WEE1".
        max_results: Unused -- a symbol resolves to one gene. Accepted so
            every search tool shares one parameter mapping.

    Returns:
        A source-stamped constraint record, or an empty-records envelope,
        with non-secret error metadata if the lookup fails.
    """
    del max_results
    try:
        async with make_client(45) as client:
            response = await client.post(
                _GNOMAD_URL,
                json={"query": _GNOMAD_QUERY, "variables": {"symbol": query}},
            )
            response.raise_for_status()
        gene = ((response.json().get("data") or {}).get("gene")) or {}
        constraint = gene.get("gnomad_constraint") or {}
    except _LOOKUP_ERRORS as exc:
        return _failed_lookup("gnomAD", query, exc)
    if not gene.get("gene_id") or not constraint:
        return _results.records("gnomAD", query, [])
    return _results.records("gnomAD", query, [_constraint_record(gene, constraint)])


def _constraint_record(gene: dict[str, Any], constraint: dict[str, Any]) -> dict[str, Any]:
    """pLI near 1 means intolerant; LOEUF below 0.35 means constrained."""
    return {
        "gene_id": gene.get("gene_id"),
        "symbol": gene.get("symbol"),
        "pli": constraint.get("pli"),
        "loeuf": constraint.get("oe_lof_upper"),
        "observed_expected_lof": constraint.get("oe_lof"),
        "missense_z": constraint.get("mis_z"),
        "interpretation": (
            "pLI near 1 means intolerant of heterozygous loss of function; "
            "LOEUF (loeuf) below 0.35 marks a constrained gene, above 1.0 an "
            "unconstrained one; missense_z above 3.09 marks missense "
            "constraint."
        ),
        "url": f"https://gnomad.broadinstitute.org/gene/{gene.get('gene_id')}",
    }


_STRING_URL = "https://string-db.org/api/json/interaction_partners"
_REACTOME_SEARCH = "https://reactome.org/ContentService/search/query"
_REACTOME_PATHWAYS = "https://reactome.org/ContentService/data/pathways/low"
_OPENTARGETS_URL = "https://api.platform.opentargets.org/api/v4/graphql"

# Human. Every consumer of these tools is a human-biology run, and the
# APIs require a taxon rather than defaulting to one.
_HUMAN_TAXON = 9606


def _capped(max_results: int) -> int:
    return max(1, min(max_results, 25))


async def search_string_interactions(query: str, max_results: int = 10) -> dict[str, Any]:
    """Return the proteins a gene or protein is linked to.

    Args:
        query: A gene or protein symbol, e.g. "WEE1" or "SLC9A1".
        max_results: Maximum partners to return, capped at 25.

    Returns:
        Source-stamped interaction partners with STRING's combined score
        and its evidence channels, or an empty-records envelope, with
        non-secret error metadata if the lookup fails.
    """
    limit = _capped(max_results)
    params: dict[str, str | int] = {
        "identifiers": query,
        "species": _HUMAN_TAXON,
        "limit": limit,
    }
    try:
        partners = await _get_json(_STRING_URL, params=params)
        records = _string_records(partners, limit)
    except _LOOKUP_ERRORS as exc:
        return _failed_lookup("STRING", query, exc)
    return _results.records("STRING", query, records)


def _string_records(partners: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(partners, list):
        raise ValueError("expected a JSON list of interaction partners")
    return [
        {
            "partner": partner.get("preferredName_B"),
            "combined_score": partner.get("score"),
            # Keep STRING evidence channels separate: text mining is not
            # experimental support.
            "experimental_score": partner.get("escore"),
            "database_score": partner.get("dscore"),
            "coexpression_score": partner.get("ascore"),
            "textmining_score": partner.get("tscore"),
            "url": f"https://string-db.org/network/{partner.get('stringId_B')}",
        }
        for partner in partners[:limit]
        if isinstance(partner, dict)
    ]


async def _reactome_entity(client: httpx.AsyncClient, query: str) -> str | None:
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


async def search_reactome_pathways(query: str, max_results: int = 10) -> dict[str, Any]:
    """Return the curated pathways a gene or protein participates in.

    Two calls rather than one: Reactome's free-text search returns the
    entity, and pathway membership is a separate lookup from it. Searching
    for the pathway name directly finds pathways *called* that, which is a
    different question from the one a mechanism needs answered.

    Args:
        query: A gene or protein symbol, e.g. "WEE1".
        max_results: Maximum pathways to return, capped at 25.

    Returns:
        Source-stamped pathway records, or an empty-records envelope, with
        non-secret error metadata if the lookup fails.
    """
    limit = _capped(max_results)
    try:
        async with make_client(30) as client:
            entity = await _reactome_entity(client, query)
            if entity is None:
                return _results.records("Reactome", query, [])
            response = await client.get(
                f"{_REACTOME_PATHWAYS}/entity/{entity}/allForms",
                params={"species": str(_HUMAN_TAXON)},
            )
            response.raise_for_status()
        pathways = response.json()
        if not isinstance(pathways, list):
            raise ValueError("expected a JSON list of pathways")
    except _LOOKUP_ERRORS as exc:
        return _failed_lookup("Reactome", query, exc)
    records = [
        {
            "pathway_id": pathway.get("stId"),
            "name": pathway.get("displayName"),
            "url": f"https://reactome.org/content/detail/{pathway.get('stId')}",
        }
        for pathway in pathways[:limit]
        if isinstance(pathway, dict)
    ]
    return _results.records("Reactome", query, records)


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
    """Open Targets includes false buckets; carry only satisfied modalities
    to avoid meaningless clutter.
    """
    return [
        f"{entry.get('modality')}: {entry.get('label')}"
        for entry in tractability
        if isinstance(entry, dict) and entry.get("value")
    ]


async def search_open_targets(query: str, max_results: int = 10) -> dict[str, Any]:
    """Return a target's disease associations and druggability.

    Args:
        query: A gene or protein symbol, e.g. "WEE1".
        max_results: Maximum disease associations to return, capped at 25.

    Returns:
        A single source-stamped target record carrying scored disease
        associations and the tractability buckets it satisfies, or an
        empty-records envelope, with non-secret error metadata if the lookup
        fails.
    """
    limit = _capped(max_results)
    try:
        async with make_client(30) as client:
            response = await client.post(
                _OPENTARGETS_URL,
                json={
                    "query": _OPENTARGETS_QUERY,
                    "variables": {"q": query, "n": limit},
                },
            )
            response.raise_for_status()
        hits = (((response.json().get("data") or {}).get("search") or {}).get("hits")) or []
        records = [_open_targets_record(hits[0])] if hits else []
    except _LOOKUP_ERRORS as exc:
        return _failed_lookup("Open Targets", query, exc)
    return _results.records("Open Targets", query, records)


def _open_targets_record(hit: dict[str, Any]) -> dict[str, Any]:
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


_API_URL = "https://www.ebi.ac.uk/gwas/rest/api/v2/associations"
_FAQ_URL = "https://www.ebi.ac.uk/gwas/docs/faq/"
_RS_ID_RE = re.compile(r"^rs[0-9]+$", re.IGNORECASE)
MAX_PAGE_SIZE = 100
MAX_PAGE = 100
_REQUEST_TIMEOUT_SECONDS = 15
# Process-wide start slots stay below EBI's documented 15 qps cap.
_wait_for_request_slot = RequestPacer(0.1).wait


def _gwas_catalog_empty_result(
    rs_id: str, page: int, size: int, source_url: str, error: dict[str, Any] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": "GWAS Catalog",
        "query": {"rs_id": rs_id, "page": page, "size": size},
        "source_url": source_url,
        "access_date": datetime.now(timezone.utc).date().isoformat(),
        "service_terms": _FAQ_URL,
        "interpretation": (
            "These are literature-curated variant-trait associations; an "
            "association or mapped gene does not establish causality."
        ),
        "records": [],
    }
    if error:
        result["error"] = error
    return result


def _page_number(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _trait_names(row: dict[str, Any]) -> list[str]:
    efo_traits = row.get("efo_traits") or []
    traits = [
        item["efo_trait"]
        for item in efo_traits
        if isinstance(item, dict) and isinstance(item.get("efo_trait"), str)
    ]
    return traits or _strings(row.get("reported_trait"))


def _record_urls(association_id: int | str, accession: str, pubmed_id: Any) -> dict[str, str]:
    urls = {
        "source_url": f"{_API_URL}/{association_id}",
        "study_url": f"https://www.ebi.ac.uk/gwas/studies/{accession}",
    }
    if pubmed_id is not None and str(pubmed_id).isdigit():
        urls["pubmed_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pubmed_id}/"
    return urls


def _association_effects(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "p_value": _number(row.get("p_value")),
        "pvalue_mantissa": _number(row.get("pvalue_mantissa")),
        "pvalue_exponent": _number(row.get("pvalue_exponent")),
        "beta": row.get("beta"),
        "odds_ratio": row.get("odds_ratio"),
        "risk_frequency": row.get("risk_frequency"),
        "confidence_interval": [
            _number(row.get("ci_lower")),
            _number(row.get("ci_upper")),
        ],
    }


def _association(row: dict[str, Any], rs_id: str) -> dict[str, Any]:
    association_id = row.get("association_id")
    accession = row.get("accession_id")
    pubmed_id = row.get("pubmed_id")
    if not isinstance(association_id, (int, str)) or not str(association_id).isdigit():
        raise ValueError("GWAS Catalog association is missing its source ID")
    if not isinstance(accession, str) or not re.fullmatch(r"GCST[0-9]+", accession):
        raise ValueError("GWAS Catalog association is missing a valid study accession")
    traits = _trait_names(row)

    result: dict[str, Any] = {
        "rs_id": rs_id,
        "association_id": association_id,
        "study_accession": accession,
        "trait": traits[0] if traits else None,
        "traits": traits,
        "reported_traits": _strings(row.get("reported_trait")),
        **_association_effects(row),
        "mapped_genes": _strings(row.get("mapped_genes")),
        "pubmed_id": str(pubmed_id) if pubmed_id is not None else None,
        "effect_alleles": _strings(row.get("snp_effect_allele")),
        "interpretation": (
            "The association does not establish causality or a mapped-gene mechanism."
        ),
    }
    result.update(_record_urls(association_id, accession, pubmed_id))
    return result


async def _request_page(params: dict[str, str | int]) -> Any:
    await _wait_for_request_slot()
    async with make_client(
        _REQUEST_TIMEOUT_SECONDS,
        headers={"Accept": "application/json"},
        honour_proxy_env=False,
    ) as client:
        response = await client.get(_API_URL, params=params)
        response.raise_for_status()
    return response.json()


def _association_rows(payload: dict[str, Any], page_data: dict[str, Any]) -> list[Any]:
    if "_embedded" not in payload:
        total_elements = page_data.get("totalElements")
        if (
            isinstance(total_elements, int)
            and not isinstance(total_elements, bool)
            and total_elements == 0
        ):
            return []
        raise ValueError("invalid GWAS Catalog association list")

    embedded = payload.get("_embedded")
    associations = embedded.get("associations") if isinstance(embedded, dict) else None
    if not isinstance(associations, list) or any(not isinstance(row, dict) for row in associations):
        raise ValueError("invalid GWAS Catalog association list")
    return associations


def _parse_page(
    payload: Any, rs_id: str, page: int, size: int
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("invalid GWAS Catalog response")
    page_data = payload.get("page") or {}
    if not isinstance(page_data, dict):
        raise ValueError("invalid GWAS Catalog page metadata")

    associations = _association_rows(payload, page_data)
    page_result = {
        "number": _page_number(page_data.get("number"), page),
        "size": _page_number(page_data.get("size"), size),
        "total_elements": _page_number(page_data.get("totalElements"), 0),
        "total_pages": _page_number(page_data.get("totalPages"), 0),
    }
    return page_result, [_association(row, rs_id) for row in associations]


async def search_gwas_catalog_associations(
    rs_id: str, size: int = 20, page: int = 0
) -> dict[str, Any]:
    """Return a bounded page of GWAS Catalog associations for one rsID.

    This lookup reports statistical associations and their published effect
    context. Neither an associated variant nor a mapped gene establishes a
    causal mechanism.
    """
    normalized = rs_id.strip().lower()
    if len(normalized) > 24 or not _RS_ID_RE.fullmatch(normalized):
        return _gwas_catalog_empty_result(
            normalized,
            0,
            20,
            _API_URL,
            _results.invalid_request("rs_id must be an rs identifier such as rs334"),
        )

    bounded_size = max(1, min(size, MAX_PAGE_SIZE))
    bounded_page = max(0, min(page, MAX_PAGE))
    params: dict[str, str | int] = {
        "rs_id": normalized,
        "page": bounded_page,
        "size": bounded_size,
    }
    request_url = str(httpx.URL(_API_URL).copy_merge_params(params))
    result = _gwas_catalog_empty_result(normalized, bounded_page, bounded_size, request_url)

    try:
        payload = await _request_page(params)
        result["page"], result["records"] = _parse_page(
            payload, normalized, bounded_page, bounded_size
        )
    except (httpx.HTTPError, ValueError) as exc:
        result["error"] = _results.failure(exc)
        logger.warning(
            "GWAS Catalog lookup failed for %s: %s", normalized, result["error"]["detail"]
        )
    return result

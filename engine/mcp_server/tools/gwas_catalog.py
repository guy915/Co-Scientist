"""Bounded variant-association lookup through the GWAS Catalog v2 API."""

import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://www.ebi.ac.uk/gwas/rest/api/v2/associations"
_FAQ_URL = "https://www.ebi.ac.uk/gwas/docs/faq/"
_RS_ID_RE = re.compile(r"^rs[0-9]+$", re.IGNORECASE)
MAX_PAGE_SIZE = 100
MAX_PAGE = 100
_REQUEST_TIMEOUT_SECONDS = 15
_REQUEST_INTERVAL_SECONDS = 0.1
_request_pacing_lock = threading.Lock()
_next_request_at = 0.0


def _empty_result(
    rs_id: str, page: int, size: int, source_url: str, error: str | None = None
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
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool)
        else fallback
    )


def _number(value: Any) -> int | float | None:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _strings(value: Any) -> list[str]:
    return (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )


def _trait_names(row: dict[str, Any]) -> list[str]:
    efo_traits = row.get("efo_traits") or []
    traits = [
        item["efo_trait"]
        for item in efo_traits
        if isinstance(item, dict) and isinstance(item.get("efo_trait"), str)
    ]
    return traits or _strings(row.get("reported_trait"))


def _record_urls(
    association_id: int | str, accession: str, pubmed_id: Any
) -> dict[str, str]:
    urls = {
        "source_url": f"{_API_URL}/{association_id}",
        "study_url": f"https://www.ebi.ac.uk/gwas/studies/{accession}",
    }
    if pubmed_id is not None and str(pubmed_id).isdigit():
        urls["pubmed_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pubmed_id}/"
    return urls


def _association(row: dict[str, Any], rs_id: str) -> dict[str, Any]:
    association_id = row.get("association_id")
    accession = row.get("accession_id")
    pubmed_id = row.get("pubmed_id")
    if (
        not isinstance(association_id, (int, str))
        or not str(association_id).isdigit()
    ):
        raise ValueError("GWAS Catalog association is missing its source ID")
    if not isinstance(accession, str) or not re.fullmatch(
        r"GCST[0-9]+", accession
    ):
        raise ValueError(
            "GWAS Catalog association is missing a valid study accession"
        )
    traits = _trait_names(row)

    result: dict[str, Any] = {
        "rs_id": rs_id,
        "association_id": association_id,
        "study_accession": accession,
        "trait": traits[0] if traits else None,
        "traits": traits,
        "reported_traits": _strings(row.get("reported_trait")),
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
        "mapped_genes": _strings(row.get("mapped_genes")),
        "pubmed_id": str(pubmed_id) if pubmed_id is not None else None,
        "effect_alleles": _strings(row.get("snp_effect_allele")),
        "interpretation": (
            "The association does not establish causality or a mapped-gene "
            "mechanism."
        ),
    }
    result.update(_record_urls(association_id, accession, pubmed_id))
    return result


def _reserve_request_slot(now: float) -> float:
    """Reserve a process-wide start slot below EBI's documented 15 qps cap."""
    global _next_request_at
    with _request_pacing_lock:
        start = max(now, _next_request_at)
        _next_request_at = start + _REQUEST_INTERVAL_SECONDS
    return start


async def _wait_for_request_slot() -> None:
    now = time.monotonic()
    delay = _reserve_request_slot(now) - now
    if delay > 0:
        await asyncio.sleep(delay)


async def _request_page(params: dict[str, str | int]) -> Any:
    await _wait_for_request_slot()
    async with httpx.AsyncClient(
        timeout=_REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
        headers={"Accept": "application/json"},
    ) as client:
        response = await client.get(_API_URL, params=params)
        response.raise_for_status()
    return response.json()


def _association_rows(
    payload: dict[str, Any], page_data: dict[str, Any]
) -> list[Any]:
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
    associations = (
        embedded.get("associations") if isinstance(embedded, dict) else None
    )
    if not isinstance(associations, list) or any(
        not isinstance(row, dict) for row in associations
    ):
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
        return _empty_result(
            normalized,
            0,
            20,
            _API_URL,
            "rs_id must be an rs identifier such as rs334",
        )

    bounded_size = max(1, min(size, MAX_PAGE_SIZE))
    bounded_page = max(0, min(page, MAX_PAGE))
    params: dict[str, str | int] = {
        "rs_id": normalized,
        "page": bounded_page,
        "size": bounded_size,
    }
    request_url = str(httpx.URL(_API_URL).copy_merge_params(params))
    result = _empty_result(normalized, bounded_page, bounded_size, request_url)

    try:
        payload = await _request_page(params)
        result["page"], result["records"] = _parse_page(
            payload, normalized, bounded_page, bounded_size
        )
    except (httpx.HTTPError, ValueError) as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "GWAS Catalog lookup failed for %s: %s", normalized, detail
        )
        result["error"] = detail
    return result

"""Bounded citation-edge lookup through OpenCitations Index v2."""

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://api.opencitations.net/index/v2"
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_OCI_RE = re.compile(r"^\d{1,32}-\d{1,32}$")
_IDENTIFIER_RE = re.compile(
    r"^(?:doi:[^\s]{1,256}|pmid:\d{1,12}|"
    r"omid:[a-z0-9._/-]{1,64}|openalex:w\d{1,20})$",
    re.IGNORECASE,
)
# A semicolon belongs to the separator only when it introduces another
# explicitly indexed value; DOI suffixes can contain semicolons themselves.
_INDEX_SEGMENT_RE = re.compile(r";\s*(?=\[[^\]\r\n]{1,64}\]\s*=>)")
_INDEX_PREFIX_RE = re.compile(r"^\s*\[[^\]\r\n]{1,64}\]\s*=>\s*")
_MAX_DOI_LENGTH = 256
_MAX_IDENTIFIER_TEXT = 1024
_MAX_IDENTIFIERS_PER_WORK = 16
_MAX_EDGES = 50
_MAX_RESPONSE_BYTES = 1_000_000
_REQUEST_TIMEOUT_SECONDS = 10
_TOTAL_TIMEOUT_SECONDS = 30
_REQUEST_INTERVAL_SECONDS = 1.0
_request_pacing_lock = threading.Lock()
_next_request_at = 0.0


def _reserve_request_at(now: float) -> float:
    """Reserve a process-wide request start slot at least one second apart."""
    global _next_request_at
    with _request_pacing_lock:
        reserved = max(now, _next_request_at)
        _next_request_at = reserved + _REQUEST_INTERVAL_SECONDS
    return reserved


async def _wait_for_request_slot() -> None:
    """Pace upstream starts across concurrent event loops and tool calls."""
    now = time.monotonic()
    delay = _reserve_request_at(now) - now
    if delay > 0:
        await asyncio.sleep(delay)


async def _response_json(client: httpx.AsyncClient, url: str) -> Any:
    """Fetch one JSON response, enforcing a decoded body size limit."""
    await _wait_for_request_slot()
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        length = response.headers.get("content-length")
        if length and length.isdecimal() and int(length) > _MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds the 1 MB limit")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds the 1 MB limit")
    return json.loads(body)


def _count(payload: Any) -> int:
    """Read the documented count field without treating malformed data as 0."""
    rows = payload if isinstance(payload, list) else [payload]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("invalid OpenCitations count response")
    value = rows[0].get("count")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    raise ValueError("invalid OpenCitations count value")


def _identifiers(value: Any) -> list[str]:
    """Normalize OpenCitations' whitespace-separated PIDs into a list."""
    if not isinstance(value, str):
        raise ValueError("citation edge is missing an identifier field")
    if len(value) > _MAX_IDENTIFIER_TEXT:
        raise ValueError("citation edge identifier text exceeds its limit")
    identifiers = _parse_identifiers(value)
    return list(
        dict.fromkeys(
            f"{identifier.partition(':')[0].lower()}:"
            f"{identifier.partition(':')[2]}"
            for identifier in identifiers
        )
    )


def _parse_identifiers(value: str) -> list[str]:
    """Validate and split a bounded OpenCitations identifier field."""
    identifiers = [
        identifier
        for segment in _INDEX_SEGMENT_RE.split(value)
        for identifier in _INDEX_PREFIX_RE.sub("", segment, count=1).split()
    ]
    if (
        not identifiers
        or len(identifiers) > _MAX_IDENTIFIERS_PER_WORK
        or any(not _IDENTIFIER_RE.fullmatch(item) for item in identifiers)
    ):
        raise ValueError("citation edge has invalid identifiers")
    return identifiers


def _edge(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize one directed citation record."""
    oci = row.get("oci")
    if not isinstance(oci, str) or not _OCI_RE.fullmatch(oci):
        raise ValueError("citation edge is missing a valid OCI")
    edge: dict[str, Any] = {
        "oci": oci,
        "citing": _identifiers(row.get("citing")),
        "cited": _identifiers(row.get("cited")),
        "citing_raw": row["citing"],
        "cited_raw": row["cited"],
    }
    for field in ("creation", "timespan", "journal_sc", "author_sc"):
        if isinstance(row.get(field), str):
            edge[field] = row[field]
    return edge


def _edges(payload: Any) -> list[dict[str, Any]]:
    """Normalize directed citation records while retaining edge metadata."""
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) for row in payload
    ):
        raise ValueError("invalid OpenCitations edge response")
    return [_edge(row) for row in payload[:_MAX_EDGES]]


def _normalize_doi(doi: str) -> str:
    """Strip an optional prefix and validate the bounded DOI input."""
    normalized_doi = doi.strip()
    if normalized_doi.lower().startswith("doi:"):
        normalized_doi = normalized_doi[4:]
    if len(normalized_doi) > _MAX_DOI_LENGTH or not _DOI_RE.fullmatch(
        normalized_doi
    ):
        raise ValueError("doi must be a valid DOI such as 10.1234/example")
    return normalized_doi


def _citation_urls(doi: str) -> dict[str, str]:
    """Build the count and edge endpoint URLs for a normalized DOI."""
    encoded_id = f"doi:{quote(doi, safe='/')}"
    return {
        "citations_count": f"{_API_URL}/citation-count/{encoded_id}",
        "references_count": f"{_API_URL}/reference-count/{encoded_id}",
        "citations": f"{_API_URL}/citations/{encoded_id}",
        "references": f"{_API_URL}/references/{encoded_id}",
    }


async def _fetch_citation_data(
    doi: str, urls: dict[str, str]
) -> tuple[int, int, list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch counts first, then only edge sets within the configured bound."""
    try:
        async with asyncio.timeout(_TOTAL_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=_REQUEST_TIMEOUT_SECONDS,
                follow_redirects=False,
                trust_env=False,
                headers={"Accept": "application/json"},
            ) as client:
                # Counts always precede the potentially large, unpaginated
                # edge requests.
                citation_count = _count(
                    await _response_json(client, urls["citations_count"])
                )
                reference_count = _count(
                    await _response_json(client, urls["references_count"])
                )
                citation_fetched = 0 < citation_count <= _MAX_EDGES
                reference_fetched = 0 < reference_count <= _MAX_EDGES
                citation_rows = (
                    await _response_json(client, urls["citations"])
                    if citation_fetched
                    else []
                )
                reference_rows = (
                    await _response_json(client, urls["references"])
                    if reference_fetched
                    else []
                )
                citations = _edges(citation_rows)
                references = _edges(reference_rows)
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        logger.warning("OpenCitations lookup failed for %s: %s", doi, exc)
        raise RuntimeError(
            f"OpenCitations Index unavailable: {type(exc).__name__}: {exc}"
        ) from exc
    return citation_count, reference_count, citations, references


def _directional_edges(
    direction: str,
    count: int,
    edges: list[dict[str, Any]],
    count_url: str,
    edge_url: str,
) -> dict[str, Any]:
    """Assemble edge data and fetch provenance for one direction."""
    return {
        "direction": direction,
        "count": count,
        "edges": edges,
        "count_request_url": count_url,
        "edge_request_url": edge_url if 0 < count <= _MAX_EDGES else None,
        "edge_fetch_status": _fetch_status(count, edges),
    }


async def get_opencitations_citation_edges(doi: str) -> dict[str, Any]:
    """Return bounded incoming and outgoing citation edges for a DOI.

    The API's count endpoints are queried before its unpaginated edge
    endpoints. Edges are fetched only when the respective count is at most
    50; every response is capped at 1 MB and the whole lookup at 30 seconds.
    A successful count of zero means no edges are indexed. Upstream and
    malformed-response failures raise instead of being represented as zero.

    Citation links indicate bibliographic relationships only; they do not
    establish whether one work supports or contradicts a scientific claim.

    Args:
        doi: DOI in raw form, optionally prefixed with ``doi:``.

    Returns:
        Directional citation and reference edges with counts and provenance.

    Raises:
        ValueError: If ``doi`` is not a DOI.
        RuntimeError: If OpenCitations is unavailable or returns invalid data.
    """
    normalized_doi = _normalize_doi(doi)
    urls = _citation_urls(normalized_doi)
    (
        citation_count,
        reference_count,
        citations,
        references,
    ) = await _fetch_citation_data(normalized_doi, urls)
    return {
        "source": "OpenCitations Index v2",
        "source_url": _API_URL,
        "accessed_at": datetime.now(timezone.utc).isoformat(),
        "doi": normalized_doi,
        "citation_count": citation_count,
        "reference_count": reference_count,
        "citations": _directional_edges(
            "incoming",
            citation_count,
            citations,
            urls["citations_count"],
            urls["citations"],
        ),
        "references": _directional_edges(
            "outgoing",
            reference_count,
            references,
            urls["references_count"],
            urls["references"],
        ),
        "interpretation_note": (
            "Citation links indicate bibliographic relationships only; they "
            "do not establish whether a work supports or contradicts a claim."
        ),
    }


def _fetch_status(count: int, edges: list[dict[str, Any]]) -> str:
    """Explain why edge records are absent or whether the fetch was complete."""
    if count == 0:
        return "zero_indexed"
    if count > _MAX_EDGES:
        return "count_exceeds_edge_limit"
    return "complete" if len(edges) == count else "partial"

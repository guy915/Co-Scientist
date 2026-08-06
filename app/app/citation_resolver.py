"""Live resolvability check for evidence identifiers (DOI/PMID/URL).

``app/claims_gate.py`` documents this module as the live counterpart to
``offline_resolver``: the offline resolver reads back the metadata a source
already claimed (a non-empty URL string, an ``is_retracted`` flag); this one
actually dereferences the identifier against the real web, so "available"
means "resolved", not "the string was non-empty".

A PMID is looked up through NCBI's ESummary API rather than the human-facing
``pubmed.ncbi.nlm.nih.gov`` page: that page sits behind bot-management that
returns 403 to a plain HTTP client regardless of headers (verified against
the live site while building this), which would misreport every reachable
PubMed article as unresolvable. ESummary is a documented programmatic
endpoint and always answers 200, echoing an ``"error"`` field inside the
per-id record for an id it does not recognize, so a resolvable PMID is
distinguished by that field's absence rather than by status code.

Runs on a small bounded thread pool rather than an event loop. The drain
calls ``resolve_many`` from inside a running asyncio loop
(``engine_tasks_node.execute_finalize``), where ``asyncio.run`` would raise;
a blocking thread pool sidesteps that the same way
``app.claim_grounding_assess`` already does for its own provider calls, and
each thread opens its own short-lived client rather than sharing one, since
``httpx.Client`` is not guaranteed safe for concurrent use across threads.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.claims_gate import Resolvability

logger = logging.getLogger(__name__)

# A run's evidence budget is a few dozen items at most; this bounds how many
# sockets are open at once without serializing the whole set behind the
# slowest single request.
_RESOLVE_CONCURRENCY = 6
_RESOLVE_TIMEOUT_SECONDS = 8.0

_PUBMED_ESUMMARY_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
)

# One identifier request: (doi, pmid, url, retracted). A plain tuple (not a
# dataclass) so callers can build the list directly from evidence metadata.
IdentifierRequest = tuple[str, str, str, bool]


def _doi_url(doi: str) -> str:
    return f"https://doi.org/{doi.strip()}"


def _reachable(client: httpx.Client, url: str) -> bool:
    """Dereference one URL by status code, tolerant of HEAD-averse servers."""
    try:
        response = client.head(url, follow_redirects=True)
        if response.status_code in (403, 405):
            # Some hosts (doi.org among them) reject HEAD outright; a GET
            # without reading the body still proves the address resolves.
            response = client.get(url, follow_redirects=True)
        return response.status_code < 400
    except httpx.HTTPError as exc:
        logger.debug("dereference failed for %s: %s", url, exc)
        return False


def _pmid_found(client: httpx.Client, pmid: str) -> bool:
    """Look up a PMID via NCBI's ESummary API (see the module docstring)."""
    try:
        response = client.get(
            _PUBMED_ESUMMARY_URL,
            params={"db": "pubmed", "id": pmid, "retmode": "json"},
        )
        if response.status_code >= 400:
            return False
        record = response.json().get("result", {}).get(pmid, {})
        return bool(record) and "error" not in record
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("PMID lookup failed for %s: %s", pmid, exc)
        return False


def _resolve_with_client(
    client: httpx.Client | None, check: Callable[[httpx.Client], bool]
) -> Resolvability:
    """Run one check, opening a client only when the caller has none."""
    owns_client = client is None
    active = client or httpx.Client(timeout=_RESOLVE_TIMEOUT_SECONDS)
    try:
        found = check(active)
    finally:
        if owns_client:
            active.close()
    return Resolvability.RESOLVABLE if found else Resolvability.UNRESOLVABLE


def resolve_one(
    *,
    doi: str,
    pmid: str,
    url: str,
    retracted: bool,
    client: httpx.Client | None = None,
) -> Resolvability:
    """Dereference one evidence identifier against the live web.

    Retraction is decided from metadata alone -- there is nothing to
    dereference that would reverse it. A DOI is preferred over a PMID
    (resolves through its own registry regardless of which URL the source
    attached), a PMID over a bare source-supplied URL, and everything else
    is judged by actually resolving the identifier, never by inspecting
    whether a URL string happens to be non-empty.

    Args:
        doi: The article's DOI, or empty.
        pmid: The article's PMID, or empty.
        url: A source-supplied URL, used only when neither identifier above
            is present.
        retracted: Whether the source already flagged this as retracted.
        client: Optional client to reuse (single-threaded callers only).

    Returns:
        RETRACTED without any network call when ``retracted`` is set,
        otherwise RESOLVABLE or UNRESOLVABLE from the live check.
    """
    if retracted:
        return Resolvability.RETRACTED
    if doi:
        return _resolve_with_client(
            client, lambda c: _reachable(c, _doi_url(doi))
        )
    if pmid:
        return _resolve_with_client(client, lambda c: _pmid_found(c, pmid))
    if url:
        return _resolve_with_client(client, lambda c: _reachable(c, url))
    return Resolvability.UNRESOLVABLE


def _resolve_request(request: IdentifierRequest) -> Resolvability:
    doi, pmid, url, retracted = request
    return resolve_one(doi=doi, pmid=pmid, url=url, retracted=retracted)


def resolve_many(
    requests: Iterable[IdentifierRequest],
) -> list[Resolvability]:
    """Dereference many identifiers concurrently, in input order.

    Args:
        requests: Each item's ``(doi, pmid, url, retracted)``.

    Returns:
        One :class:`Resolvability` per request, same order as ``requests``.
    """
    items = list(requests)
    if not items:
        return []
    with ThreadPoolExecutor(
        max_workers=min(_RESOLVE_CONCURRENCY, len(items))
    ) as pool:
        return list(pool.map(_resolve_request, items))

"""The live ``Resolver``: dereference an identifier against the real web.

:func:`live_resolver` is the production implementation of
``app.citations.metadata.Resolver``, and the offline default there is its
counterpart: that one reads back the metadata a source already claimed (an
identifier string, an ``is_retracted`` flag); this one actually dereferences
the identifier, so "available" means "resolved", not "the string was
non-empty". Both are reached through the same
``citation_metadata.assess_resolvability`` seam -- including by
:func:`resolve_many` below, which adds only concurrency, never a second
implementation of the verdict.

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
(``engine_tasks.node.execute_finalize``), where ``asyncio.run`` would raise;
a blocking thread pool sidesteps that the same way
``app.claims.grounding_assess`` already does for its own provider calls, and
each thread opens its own short-lived client rather than sharing one, since
``httpx.Client`` is not guaranteed safe for concurrent use across threads.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

import httpx

from app import retraction_set
from app.citations import metadata as citation_metadata
from app.citations.metadata import CitationMetadata, Resolvability, Resolver

logger = logging.getLogger(__name__)

# A run's evidence budget is a few dozen items at most; this bounds how many
# sockets are open at once without serializing the whole set behind the
# slowest single request.
_RESOLVE_CONCURRENCY = 6
_RESOLVE_TIMEOUT_SECONDS = 8.0

_PUBMED_ESUMMARY_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
)


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


def _resolve_doi(doi: str, client: httpx.Client | None) -> Resolvability:
    """Resolve a DOI: offline retraction set first, then a live dereference."""
    if retraction_set.is_known_retracted(doi):
        return Resolvability.RETRACTED
    return _resolve_with_client(client, lambda c: _reachable(c, _doi_url(doi)))


def resolve_one(
    *,
    doi: str,
    pmid: str,
    url: str,
    retracted: bool,
    client: httpx.Client | None = None,
) -> Resolvability:
    """Dereference one evidence identifier against the live web.

    Retraction is decided first from metadata (the source already flagged
    it), then, for a DOI the source did not flag, from a second and
    independent offline check (see ``app.retraction_set``) -- source
    databases can take months to propagate a retraction, so this is the
    only defense against one they have not (yet) caught. Neither check
    dereferences anything. A DOI is preferred over a PMID (resolves
    through its own registry regardless of which URL the source attached),
    a PMID over a bare source-supplied URL, and everything else is judged
    by actually resolving the identifier, never by inspecting whether a URL
    string happens to be non-empty.

    Args:
        doi: The article's DOI, or empty.
        pmid: The article's PMID, or empty.
        url: A source-supplied URL, used only when neither identifier above
            is present.
        retracted: Whether the source already flagged this as retracted.
        client: Optional client to reuse (single-threaded callers only).

    Returns:
        RETRACTED without any network call when ``retracted`` is set or the
        DOI is in the offline retraction set, otherwise RESOLVABLE or
        UNRESOLVABLE from the live check.
    """
    if retracted:
        return Resolvability.RETRACTED
    if doi:
        return _resolve_doi(doi, client)
    if pmid:
        return _resolve_with_client(client, lambda c: _pmid_found(c, pmid))
    if url:
        return _resolve_with_client(client, lambda c: _reachable(c, url))
    return Resolvability.UNRESOLVABLE


def live_resolver(meta: CitationMetadata) -> Resolvability:
    """Resolve one citation's metadata by dereferencing its identifier.

    The production ``Resolver`` (``settings.evidence_resolver == "live"``),
    passed to ``citation_metadata.assess_resolvability`` rather than called
    around it, so the live and offline paths differ only in this argument.

    Args:
        meta: The citation's metadata.

    Returns:
        The source's :class:`Resolvability`.
    """
    return resolve_one(
        doi=meta.doi,
        pmid=meta.pmid,
        url=meta.url,
        retracted=meta.retracted,
    )


def resolve_many(
    metas: Iterable[CitationMetadata], *, resolver: Resolver
) -> list[Resolvability]:
    """Assess many citations concurrently, in input order.

    Each verdict still comes from
    ``citation_metadata.assess_resolvability``; this adds only the bounded
    fan-out a live resolver needs, and is looked up on the module (not
    bound at import) so a test can substitute the seam. An offline
    resolver runs through the same pool -- once per run, over a few dozen
    pure calls -- rather than earning a second code path for the saving.

    Args:
        metas: The citations to assess.
        resolver: The resolver every verdict goes through.

    Returns:
        One :class:`Resolvability` per citation, same order as ``metas``.
    """
    items = list(metas)
    if not items:
        return []
    assess = functools.partial(
        citation_metadata.assess_resolvability, resolver=resolver
    )
    with ThreadPoolExecutor(
        max_workers=min(_RESOLVE_CONCURRENCY, len(items))
    ) as pool:
        return list(pool.map(assess, items))

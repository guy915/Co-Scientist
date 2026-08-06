"""Live availability resolution for the engine drain's retrieved evidence.

Runs strictly before the drain's first transaction opens: dereferencing a
DOI or PMID is network I/O, and the drain must never hold SQLite's write
lock across it (see AGENTS.md's "never hold the SQLite write lock across
network I/O"). ``settings.evidence_resolver`` switches between the live
dereference (``app.citation_resolver``) and the offline metadata heuristic
the test suite pins, mirroring how ``settings.claim_assessor`` switches the
grounding assessor.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app import citation_resolver as citation_resolver
from app.claims_gate import Resolvability
from app.config import settings

_PUBMED_URL_PMID = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")


@dataclass(frozen=True)
class ResolvedArticle:
    """One article's persisted identity and its resolved availability."""

    doi: str | None
    pmid: str | None
    available: bool


def _article_doi(art: dict[str, Any]) -> str:
    return str(art.get("doi") or "").strip()


def _article_pmid(art: dict[str, Any]) -> str:
    """Return the article's PMID, from its source id or a PubMed URL.

    ``source_id`` is the PMID verbatim for a PubMed-sourced article (see
    ``build_article_from_metadata``); other sources carry no PMID unless
    their URL happens to be a PubMed link.
    """
    if str(art.get("source") or "").lower() == "pubmed":
        source_id = str(art.get("source_id") or "").strip()
        if source_id.isdigit():
            return source_id
    match = _PUBMED_URL_PMID.search(str(art.get("url") or ""))
    return match.group(1) if match else ""


def _article_retracted(art: dict[str, Any]) -> bool:
    return bool(art.get("is_retracted")) or (
        str(art.get("correction_status") or "").lower() == "retracted"
    )


def _article_request(
    art: dict[str, Any],
) -> tuple[str, str, str, bool]:
    """Extract one article's (doi, pmid, url, retracted) resolver request."""
    return (
        _article_doi(art),
        _article_pmid(art),
        str(art.get("url") or ""),
        _article_retracted(art),
    )


def _offline_available(request: tuple[str, str, str, bool]) -> bool:
    """The pre-existing metadata-only heuristic, kept for offline/tests.

    A non-empty identifier or URL and no retraction flag -- unlike the live
    path, this never leaves the process.
    """
    doi, pmid, url, retracted = request
    return bool(doi or pmid or url) and not retracted


def _resolved_from_requests(
    requests: list[tuple[str, str, str, bool]],
) -> list[ResolvedArticle]:
    """Build the persisted (doi, pmid, available) triple for each request."""
    verdicts: Sequence[Resolvability | bool]
    if settings.evidence_resolver == "live":
        verdicts = citation_resolver.resolve_many(requests)
    else:
        verdicts = [_offline_available(r) for r in requests]
    resolved = []
    for (doi, pmid, _url, _retracted), verdict in zip(
        requests, verdicts, strict=True
    ):
        available = (
            verdict is Resolvability.RESOLVABLE
            if isinstance(verdict, Resolvability)
            else bool(verdict)
        )
        resolved.append(ResolvedArticle(doi or None, pmid or None, available))
    return resolved


def resolve_articles(
    articles: list[dict[str, Any]],
) -> list[ResolvedArticle]:
    """Resolve every article's identity and availability, in input order.

    Live mode (``settings.evidence_resolver == "live"``, the production
    default) dereferences each identifier against the real web; offline
    mode (the hermetic test default) judges availability from metadata
    alone and never performs network I/O.

    Args:
        articles: The engine's retrieved articles (``Article.to_dict()``
            payloads).

    Returns:
        One :class:`ResolvedArticle` per article, same order as ``articles``.
    """
    requests = [_article_request(art) for art in articles]
    return _resolved_from_requests(requests)

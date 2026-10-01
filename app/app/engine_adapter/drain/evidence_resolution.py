"""Citation-metadata resolution for the engine drain's retrieved evidence.

Every verdict is computed by ``citation_metadata.assess_resolvability``;
``settings.evidence_resolver`` chooses only which ``Resolver`` it is handed
-- the live dereference (``app.citation_resolver.live_resolver``, the
production default) or the offline metadata reader the test suite pins --
mirroring how ``settings.claim_assessor`` switches the grounding assessor.
There is no second implementation of the verdict behind that switch; there
was, and only one of the two ever ran.

Runs strictly before the drain's first transaction opens: dereferencing a
DOI or PMID is network I/O, and the drain must never hold SQLite's write
lock across it (see AGENTS.md's "never hold the SQLite write lock across
network I/O").

Source type is classified here rather than at render time because this is
the last point it is fully knowable: the engine's ``Article`` carries a
publisher-declared ``publication_type`` -- the one signal that separates a
preprint indexed in PubMed from the journal articles beside it -- and the
evidence table does not store it. The publication *date* is the opposite
case: ``evidence.year`` persists the datum itself, so its judgement is
derived where it is read (``report.markdown.bibliography``) rather than
duplicated into a column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app import citation_resolver as citation_resolver
from app.citation_metadata import (
    CitationMetadata,
    Resolvability,
    Resolver,
    SourceType,
    classify_source_type,
    offline_resolver,
)
from app.config import settings

_PUBMED_URL_PMID = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")


@dataclass(frozen=True)
class ResolvedArticle:
    """One article's persisted identity, availability, and source type.

    ``retracted`` is reported alongside ``available`` rather than folded
    into it: a retracted source and a merely-unresolvable one both persist
    as ``available=False`` (every gate that reads ``available`` -- citation
    classification, claim grounding -- keeps treating them alike), but they
    are different facts for a reader, who should be told which one it was.
    ``source_type`` gates nothing at all: a preprint is a perfectly usable
    source, and withholding one would be a research decision this check has
    no business making.
    """

    doi: str | None
    pmid: str | None
    available: bool
    retracted: bool = False
    source_type: str = SourceType.UNKNOWN.value


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


def _article_year(art: dict[str, Any]) -> int | None:
    """Read the article's publication year, tolerating a string value."""
    try:
        return int(art["year"])
    except (KeyError, TypeError, ValueError):
        return None


def _article_metadata(art: dict[str, Any]) -> CitationMetadata:
    """Extract one article's citation metadata, the check's only input."""
    return CitationMetadata(
        url=str(art.get("url") or ""),
        doi=_article_doi(art),
        pmid=_article_pmid(art),
        retracted=_article_retracted(art),
        source=str(art.get("source") or ""),
        publication_type=str(art.get("publication_type") or ""),
        year=_article_year(art),
    )


def _configured_resolver() -> Resolver:
    """Return the ``Resolver`` this deployment resolves citations through."""
    if settings.evidence_resolver == "live":
        return citation_resolver.live_resolver
    return offline_resolver


def _resolved_article(
    meta: CitationMetadata, verdict: Resolvability
) -> ResolvedArticle:
    """Build one article's persisted row from its metadata and verdict.

    The verdict is already RETRACTED for both retraction sources -- the
    article's own metadata flag and, on the live path, the resolver's
    independent ``retraction_set`` lookup -- so it alone decides both
    flags, and the retraction fact is carried through rather than
    collapsed into plain unavailability.
    """
    return ResolvedArticle(
        doi=meta.doi or None,
        pmid=meta.pmid or None,
        available=verdict is Resolvability.RESOLVABLE,
        retracted=verdict is Resolvability.RETRACTED,
        source_type=classify_source_type(meta).value,
    )


def resolve_articles(
    articles: list[dict[str, Any]],
) -> list[ResolvedArticle]:
    """Resolve every article's identity and availability, in input order.

    Live mode (``settings.evidence_resolver == "live"``, the production
    default) dereferences each identifier against the real web; offline
    mode (the hermetic test default) judges availability from metadata
    alone and never performs network I/O. Both go through the same
    ``assess_resolvability`` seam.

    Args:
        articles: The engine's retrieved articles (``Article.to_dict()``
            payloads).

    Returns:
        One :class:`ResolvedArticle` per article, same order as ``articles``.
    """
    metas = [_article_metadata(art) for art in articles]
    verdicts = citation_resolver.resolve_many(
        metas, resolver=_configured_resolver()
    )
    return [
        _resolved_article(meta, verdict)
        for meta, verdict in zip(metas, verdicts, strict=True)
    ]

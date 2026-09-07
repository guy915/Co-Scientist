"""The evidence corpus both research-overview calls are given.

Split from ``research_overview.py`` on that module's size cap. It is one
subject: which analyzed articles are offered to the synthesis, in what
order, under what per-source budget, and how the same records are reused
afterwards to attach immutable source metadata to whatever the model
cited. The overview call and the deep knowledge-base call (F8) share it,
so neither can be given a differently-built corpus than the other.
"""

from __future__ import annotations

import itertools
from typing import Any, Final

from co_scientist.agents.meta_review.research_overview_contacts import (
    _format_or_placeholder,
)
from co_scientist.constants import strip_citation_markers
from co_scientist.models import Article

_EVIDENCE_ABSTRACT_CHARS: Final = 3000
"""Per-source abstract budget in the evidence corpus."""


def _interleave_by_source(articles: list[Article]) -> list[Article]:
    """Round-robin analyzed articles across their source.

    Search results reach this node ranked best-first by retrieval score, which
    clusters each source's top papers at the front of the list. Presenting that
    order to the synthesis LLM makes it over-cite the first few references and
    ignore the tail, so the knowledge base ends up drawn from one source's top
    hits. Interleaving one paper per source at a time keeps best-first order
    within each source while ensuring the head of the corpus samples the full
    breadth of retrieved evidence rather than a single leading cluster.

    Args:
        articles: Analyzed articles in their incoming best-first order.

    Returns:
        The same articles reordered round-robin across ``source``.
    """
    groups: dict[str, list[Article]] = {}
    for article in articles:
        groups.setdefault(article.source, []).append(article)
    interleaved: list[Article] = []
    for row in itertools.zip_longest(*groups.values()):
        interleaved.extend(article for article in row if article is not None)
    return interleaved


def _build_evidence_corpus(
    articles: list[Article] | None,
) -> dict[str, dict[str, Any]]:
    """Build the terminal synthesis corpus from articles actually analyzed.

    Evidence ids are assigned by presentation order (contiguous
    ``evidence-1..N``) over the source-interleaved list; downstream consumers
    treat the id as an opaque handle and the app re-resolves cited topics by
    title, so the numbering carries no rank meaning.
    """
    analyzed = [
        article for article in (articles or []) if article.used_in_analysis
    ]
    corpus: dict[str, dict[str, Any]] = {}
    for index, article in enumerate(_interleave_by_source(analyzed)):
        evidence_id = f"evidence-{index + 1}"
        corpus[evidence_id] = {
            "evidence_id": evidence_id,
            "source_id": article.source_id or "",
            "title": article.title,
            "abstract": (article.abstract or "")[:_EVIDENCE_ABSTRACT_CHARS],
            "source": article.source,
            "url": article.url or "",
        }
    return corpus


def _format_evidence_corpus(corpus: dict[str, dict[str, Any]]) -> str:
    """Format bounded analyzed evidence for cross-source synthesis.

    Strips each source's own inline citation markers from the prompt
    copy only. ``corpus`` itself is left untouched -- it is reused
    verbatim to attach source metadata to the synthesis LLM's cited
    topics (``_validate_knowledge_base``), which is the evidence
    excerpt the finished report ships, and that must stay the abstract
    as retrieved.
    """
    for_prompt = {
        evidence_id: {
            **record,
            "abstract": strip_citation_markers(record["abstract"]),
        }
        for evidence_id, record in corpus.items()
    }
    return _format_or_placeholder(
        for_prompt,
        (
            "- {evidence_id}: title={title}; source={source}; "
            "source_id={source_id}; abstract={abstract}"
        ),
        "No verified evidence corpus available.",
    )

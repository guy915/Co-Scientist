"""Targeted probe-evidence retrieval for deep verification and reviews.

Live literature search when the MCP back end is reachable, and graceful
grounding against the run's already-retrieved corpus when it is not
(audit E8): an unavailable search must not switch grounding off, because
the ungrounded path is exactly the failure mode the paper measured
(novelty collapsing once retrieval is removed). Both paths return the
same shape -- articles plus per-source notes -- so callers are identical
either way.
"""

import dataclasses
import logging
import re
from typing import Any

from co_scientist.agents.reflection.evidence_context import (
    RETRIEVED_LABEL,
    build_evidence_context,
    showable_articles,
)
from co_scientist.models import Article
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# How many keyword searches one verification round may spend.
_MAX_PROBE_QUERIES = 3

# How many sources one round of probe retrieval may hand to the prompt.
_MAX_PROBE_SOURCES = 6

# Corpus text considered per article when matching probe queries: title,
# abstract, and a bounded slice of fulltext. Matching is a filter, not a
# read-through, so the slice only has to reach far enough to tell a
# relevant source from an unrelated one.
_CORPUS_MATCH_CHARS = 4000

# A source must carry at least this fraction of a query's terms to count
# as grounding for it. One shared word out of six retrieves nothing worth
# reading; half or more is a real topical match.
_MIN_QUERY_COVERAGE = 0.5

# Recorded among retrieval errors when the live search is replaced by
# corpus grounding, so persisted results can tell the two paths apart.
CORPUS_FALLBACK_NOTE = (
    "MCP unavailable; probes grounded against the run's retrieved corpus"
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> frozenset[str]:
    """Lowercase alphanumeric terms of a text, for coverage matching."""
    return frozenset(_TOKEN_RE.findall(text.casefold()))


def _query_coverage(query_terms: frozenset[str], article: Article) -> float:
    """Fraction of a query's terms the article carries.

    Coverage over the *query's* terms, never a Jaccard-style union: the
    article side is orders of magnitude longer, and dividing by the union
    would cap the score near zero however perfectly the source matches.
    """
    searchable = " ".join(
        (article.title, article.abstract or "", article.content or "")
    )[:_CORPUS_MATCH_CHARS]
    matches = query_terms & _tokens(searchable)
    return len(matches) / len(query_terms)


def _corpus_probe_evidence(
    state: WorkflowState, queries: list[str]
) -> tuple[list[Article], list[str]]:
    """Ground probes against the run's retrieved corpus when MCP is down.

    Selects the corpus sources matching any probe query best-first, so a
    verification without a live search back end still judges against what
    the run already retrieved rather than against nothing.

    Returns:
        Matching corpus articles (bounded) and a single-element note
        recording that the fallback ran.
    """
    query_term_sets = [terms for terms in map(_tokens, queries) if terms]
    scored: list[tuple[float, int, str, Article]] = []
    for article in showable_articles(
        state.get("articles"), require_analyzed=False
    ):
        coverage = max(
            (_query_coverage(terms, article) for terms in query_term_sets),
            default=0.0,
        )
        if coverage < _MIN_QUERY_COVERAGE:
            continue
        scored.append((-coverage, -article.citations, article.title, article))
    ranked = [entry[-1] for entry in sorted(scored)]
    return ranked[:_MAX_PROBE_SOURCES], [CORPUS_FALLBACK_NOTE]


def _probe_queries(result: dict[str, Any]) -> list[str]:
    """Return the keyword searches for the load-bearing probing questions.

    Each probe carries its own ``search_query`` because the question it was
    written from is prose, and the literature back end ANDs every term of
    it: asking "Does tamoxifen reduce acrB transcript levels by >=50%
    within 1-2 hours?" demands a paper containing "does", "1-2" and "50",
    which matches nothing. A probe that omitted the query falls back to
    its question, which at least preserves the old behaviour rather than
    dropping the search.
    """
    probes = result.get("probes") or []
    ordered = sorted(
        probes,
        key=lambda probe: not bool(probe.get("assumption_is_fundamental")),
    )
    queries: list[str] = []
    seen: set[str] = set()
    for probe in ordered:
        raw = probe.get("search_query") or probe.get("question") or ""
        query = " ".join(str(raw).split())
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        queries.append(query)
        if len(queries) == _MAX_PROBE_QUERIES:
            break
    return queries


def merge_retrieved_articles(
    existing: list[Article] | None,
    results: list[dict[str, Any] | None],
) -> list[Article]:
    """Merge targeted verification sources into the run evidence corpus."""
    merged = list(existing or [])
    identities = {
        (article.source, article.source_id or article.doi or article.url)
        for article in merged
    }
    for result in results:
        if not result:
            continue
        for payload in result.get("retrieved_articles") or []:
            article = Article.from_dict(payload)
            identity = (
                article.source,
                article.source_id or article.doi or article.url,
            )
            if identity in identities:
                continue
            identities.add(identity)
            merged.append(article)
    return merged


async def _retrieve_probe_evidence(
    state: WorkflowState, queries: list[str]
) -> tuple[list[Article], list[str]]:
    """Execute targeted literature searches for verification questions.

    Without a live search back end the probes are grounded against the
    run's own retrieved corpus instead (audit E8); only when there are no
    queries is there nothing to ground either way.
    """
    if not queries:
        return [], []
    if not state.get("mcp_available"):
        return _corpus_probe_evidence(state, queries)

    from co_scientist.agents.generation.literature_review.helpers import (
        build_articles_from_metadata,
    )
    from co_scientist.agents.generation.literature_review.orchestration import (
        _phase2_collect_papers,
    )
    from co_scientist.agents.generation.literature_review.run_config import (
        _get_search_config,
    )
    from co_scientist.mcp_client import get_mcp_client

    config = dataclasses.replace(
        _get_search_config(state), papers_to_read_count=_MAX_PROBE_SOURCES
    )
    errors: list[str] = []
    try:
        client = await get_mcp_client(tool_registry=config.tool_registry)
        metadata, _ = await _phase2_collect_papers(
            queries, state, config, client, errors
        )
    except Exception as exc:
        logger.warning("Probe evidence retrieval unavailable: %s", exc)
        return [], [*errors, str(exc)]

    articles = build_articles_from_metadata(metadata, config.source_name)
    usable = [
        article
        for article in articles
        if not article.is_retracted and (article.abstract or article.content)
    ]
    return usable[:_MAX_PROBE_SOURCES], errors


def _retrieved_evidence_context(articles: list[Article]) -> str:
    """Format newly retrieved sources with stable verification keys.

    Keyed ``V`` because this block is appended to the opening evidence in
    one prompt, so the two must not share key space. Uncapped in
    aggregate: the probe cap already bounds the list.
    """
    return build_evidence_context(
        articles, require_analyzed=False, article_label=RETRIEVED_LABEL
    )

"""Probe-evidence retrieval and explicit prompt context for grounded reviews."""

import dataclasses
import logging
import re
from typing import TYPE_CHECKING, Any

from co_scientist.constants import strip_citation_markers
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.models import Article, Hypothesis
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


# One public source's slice of an evidence block. An abstract is a summary
# already, so this is effectively the whole of a typical one; the ceiling
# only bites on the fulltext fallback.
PUBLIC_SNIPPET_CHARS = 2000

# A private, scientist-supplied source's slice. Deliberately wider than a
# public source's, and written as a multiple of it so the two cannot drift
# apart again: private sources are raw notes, protocols, and unpublished
# results rather than a published summary, so they say less per character,
# and a run carries a handful of them against dozens of papers.
PRIVATE_SNIPPET_CHARS = PUBLIC_SNIPPET_CHARS * 5 // 4

# Section key prefixes. They only have to be distinct from each other:
# deep verification concatenates its opening block with a probe block in
# one prompt, so a shared prefix would give two different sources the
# same key.
PUBLIC_LABEL = "P"
PRIVATE_LABEL = "E"
RETRIEVED_LABEL = "V"


@dataclasses.dataclass(frozen=True)
class EvidenceCaps:
    """Aggregate bounds one prompt puts on its evidence block.

    Per-source truncation is not here: it is the same everywhere and lives
    in the module constants. These are the caller's own limits on how much
    evidence its prompt can carry at all.

    Attributes:
        articles: Most public sources to render, best-first, or None for
            all of them.
        private_sources: Most private sources to render, or None for all.
        total_chars: Ceiling on the assembled block, or None for none.
    """

    articles: int | None = None
    private_sources: int | None = None
    total_chars: int | None = None


_NO_CAPS = EvidenceCaps()


def showable_articles(
    articles: list[Article] | None, *, require_analyzed: bool = True
) -> list[Article]:
    """Return the articles a reflection prompt may show a model.

    Retracted papers are excluded on every path. Ranking already demotes
    them hard during retrieval, but demotion is not exclusion -- a
    retracted paper still lands in the corpus whenever the evidence budget
    is not filled by better sources.

    Args:
        articles: Candidate sources, or None.
        require_analyzed: Whether to keep only articles literature review
            actually read. False for lists that are already the result of
            a targeted retrieval, where nothing has been marked analyzed.

    Returns:
        The articles that may be rendered, in the order given.
    """
    return [
        article
        for article in (articles or [])
        if (article.used_in_analysis or not require_analyzed)
        and not article.is_retracted
    ]


def _article_excerpt(article: Article) -> str:
    """Return one article's bounded excerpt for an evidence section.

    Falls back to fulltext when the abstract is empty: an article can be
    analyzed on either field, so reading only the abstract drops a source
    that has content, silently.

    Strips the source's own inline citation markers -- left in, a review
    or verification model can copy one into its own prose. Not applied to
    ``_private_sections``: a scientist-supplied source's citations are
    its own intentional content, not another paper's contamination.
    """
    excerpt = (article.abstract or article.content or "")[:PUBLIC_SNIPPET_CHARS]
    return strip_citation_markers(excerpt)


def _head(items: list[Any], cap: int | None) -> list[Any]:
    """Return the first ``cap`` items, or all of them when cap is None."""
    return items if cap is None else items[:cap]


def _article_sections(articles: list[Article], label: str) -> list[str]:
    """Render one keyed section per article, numbered from 1.

    Numbering is over the rendered sections rather than the caller's
    source list, so the keys a prompt shows are contiguous. Skipping
    numbers reads to a model as evidence withheld.
    """
    return [
        f"[{label}{index}] {article.title}: {_article_excerpt(article)}"
        for index, article in enumerate(articles, start=1)
    ]


def _private_sections(sources: list[dict[str, Any]]) -> list[str]:
    """Render one keyed section per private, scientist-supplied source."""
    return [
        f"[{PRIVATE_LABEL}{index}] "
        f"{str(source.get('display') or '')[:PRIVATE_SNIPPET_CHARS]}"
        for index, source in enumerate(sources, start=1)
    ]


def build_evidence_context(
    articles: list[Article] | None,
    *,
    private_sources: list[dict[str, Any]] | None = None,
    caps: EvidenceCaps = _NO_CAPS,
    require_analyzed: bool = True,
    article_label: str = PUBLIC_LABEL,
) -> str:
    """Format retrieved public and private evidence for a reflection prompt.

    Args:
        articles: Public sources retrieved for this run.
        private_sources: Scientist-supplied context enrichment sources.
        caps: This prompt's aggregate bounds on the assembled block.
        require_analyzed: See :func:`showable_articles`.
        article_label: Key prefix for the public sections, so a prompt
            carrying two blocks can keep their keys apart.

    Returns:
        The assembled evidence block, or an empty string when nothing is
        showable. Callers own the wording of their "no evidence" fallback.
    """
    usable = showable_articles(articles, require_analyzed=require_analyzed)
    sections = [
        *_article_sections(_head(usable, caps.articles), article_label),
        *_private_sections(
            _head(list(private_sources or []), caps.private_sources)
        ),
    ]
    joined = "\n\n".join(sections)
    return joined if caps.total_chars is None else joined[: caps.total_chars]


if TYPE_CHECKING:
    from co_scientist.evidence.search_support import (
        SearchConfig,
    )


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

    from co_scientist.evidence.article_support import (
        build_articles_from_metadata,
    )

    config = _probe_search_config(state)
    metadata, errors, failure = await _collect_probe_papers(
        state, queries, config
    )
    if failure is not None:
        return [], failure

    articles = build_articles_from_metadata(metadata, config.source_name)
    usable = [
        article
        for article in articles
        if not article.is_retracted and (article.abstract or article.content)
    ]
    return usable[:_MAX_PROBE_SOURCES], errors


def _probe_search_config(state: WorkflowState) -> "SearchConfig":
    """Narrow the run's search config to what one probe round may spend.

    Two departures from the run-level review. The read budget drops to
    the probe's own cap, and the model-judged relevance pass is off: it
    costs one LLM call per candidate, which the review spends once per
    run but which probe retrieval would re-spend per hypothesis, per
    cycle, in each of its three callers. See
    ``SearchConfig.semantic_relevance_enabled``.
    """
    from co_scientist.evidence.run_config import (
        search_config_for,
    )

    return dataclasses.replace(
        search_config_for(state),
        papers_to_read_count=_MAX_PROBE_SOURCES,
        semantic_relevance_enabled=False,
    )


async def _collect_probe_papers(
    state: WorkflowState, queries: list[str], config: "SearchConfig"
) -> tuple[dict[str, Any], list[str], list[str] | None]:
    """Run the probe searches, reporting failure as data rather than raising.

    Returns:
        ``(metadata, errors, None)`` on success, or ``(_, _, failure)``
        where ``failure`` is the error list the caller returns with no
        articles -- a probe whose search back end is unreachable degrades
        to ungrounded rather than aborting the verification around it.
    """
    from co_scientist.evidence.search import (
        collect_papers,
    )
    from co_scientist.mcp_client import get_mcp_client

    errors: list[str] = []
    try:
        client = await get_mcp_client(tool_registry=config.tool_registry)
        metadata, _ = await collect_papers(
            queries, state, config, client, errors
        )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as exc:
        logger.warning("Probe evidence retrieval unavailable: %s", exc)
        return {}, errors, [*errors, str(exc)]
    return metadata, errors, None


def _retrieved_evidence_context(articles: list[Article]) -> str:
    """Format newly retrieved sources with stable verification keys.

    Keyed ``V`` because this block is appended to the opening evidence in
    one prompt, so the two must not share key space. Uncapped in
    aggregate: the probe cap already bounds the list.
    """
    return build_evidence_context(
        articles, require_analyzed=False, article_label=RETRIEVED_LABEL
    )


def with_researched(
    state: WorkflowState,
    hypothesis: Hypothesis,
    probed: list[Article],
) -> list[Article]:
    """Add the research already gathered for this hypothesis, if any.

    This is what makes deep verification the third owner of the research
    loop. The gathering is not started here and never will be: it runs
    after comprehensive reflection on the same cohort's loop, so where
    the reviews bought research for a leader the result is already in
    hand, and where they did not, this adds nothing and verification is
    the probe-only one it has always been. A gathering begun here would
    be a third per-hypothesis retrieval, multiplying by pool size and by
    iteration -- the shape that turned an express run into 299 calls.

    Deduplicated on ``source_id`` because a probe query and a research
    question can surface the same paper, and a document repeated in the
    prompt spends the evidence budget twice to say one thing while
    reading to the model as two sources agreeing.

    Args:
        state: Current workflow state.
        hypothesis: The hypothesis being verified.
        probed: What this verification's own probe round retrieved.

    Returns:
        The probe articles, followed by any researched ones they do not
        already include.
    """
    from co_scientist.agents.reflection.review_evidence import (
        researched_articles_for,
    )

    known = {article.source_id for article in probed}
    return probed + [
        article
        for article in researched_articles_for(state, hypothesis)
        if article.source_id not in known
    ]


def _augment_evidence_context_with_meta_review(
    evidence_context: str, state: WorkflowState
) -> str:
    """Appends cross-agent meta-review feedback to the evidence context.

    Cross-agent meta-review feedback names recurring error patterns across
    the run; appending it lets deep verification's probing questions target
    those patterns, so meta-review reaches this agent too (the disclosed
    all-agent feedback loop, audit E28). Returns evidence_context unchanged
    when no meta-review exists yet.
    """
    meta_context = _format_meta_review_context(state.get("meta_review"))
    if not meta_context:
        return evidence_context
    return (
        f"{evidence_context}\n\nCross-agent meta-review feedback "
        f"(recurring patterns to probe):\n{meta_context}"
    )

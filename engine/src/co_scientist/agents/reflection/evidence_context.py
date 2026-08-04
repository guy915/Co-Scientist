"""One formatter for the evidence a reflection prompt shows a model.

Reflection hands retrieved evidence to a model on three paths: the
full/simulation review cascade (``comprehensive_reflection``), deep
verification's opening context, and the targeted probe evidence it
retrieves mid-verification. Each used to format its own block, and the
three drifted:

* Only the review cascade excluded retracted papers, so a paper the
  reviews refused to read still reached the gate whose whole job is to
  challenge what a hypothesis rests on. A retracted source is not
  demoted evidence there, it is evidence pointing the wrong way.
* Only two of the three fell back to an article's fulltext when its
  abstract was empty. Retrieval marks an article analyzed on either
  field, so an abstract-less article with real fulltext rendered as a
  bare title in the verification prompt while contributing its text
  everywhere else -- a silent hole, not an error.
* The per-source truncation had grown three values (1800/2000/2500) with
  no relationship between them.

So selection and rendering live here once. What still differs per caller
is only the *aggregate* bound a given prompt can afford, passed as
``EvidenceCaps``.

Everything in this module is pure string work over already-fetched
articles; retrieval and the LLM calls stay in the calling nodes.
"""

import dataclasses
from typing import Any

from co_scientist.models import Article

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
    """
    return (article.abstract or article.content or "")[:PUBLIC_SNIPPET_CHARS]


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

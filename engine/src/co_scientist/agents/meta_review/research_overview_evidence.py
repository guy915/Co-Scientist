"""The evidence corpus both research-overview calls are given.

Split from ``research_overview.py`` on that module's size cap. It is one
subject: which analyzed articles are offered to the synthesis, in what
order, under what per-source budget, and how the same records are reused
afterwards to attach immutable source metadata to whatever the model
cited. The overview call and the deep knowledge-base call (F8) share it,
so neither can be given a differently-built corpus than the other. The
run-scoped prompt context those calls render against lives here for the
same reason: every call this node makes must be given the same one.
"""

from __future__ import annotations

import itertools
from typing import Any, Final

from co_scientist.agents.meta_review.research_overview_contacts import (
    _format_or_placeholder,
)
from co_scientist.constants import strip_citation_markers
from co_scientist.models import Article
from co_scientist.prompts import PromptRunContext
from co_scientist.state import WorkflowState

_EVIDENCE_ABSTRACT_CHARS: Final = 3000
"""Per-source abstract budget in the evidence corpus.

Measured rather than assumed, and deliberately left where it is. Over
the analyzed articles of six real-provider runs (239 sources, checkpoint
state, 2026-08/09) abstracts average ~1,590 characters and **two** of the
239 exceeded this cap, by 80 and 306 characters: 386 characters withheld
in total, none of them carrying a number, a unit or an entity name.
Raising the cap therefore buys the deep knowledge-base call (F8) nothing.
It is not what bounds that section's detail.

What bounds it is the field this reads. ``Article.abstract`` is the
abstract as retrieved, while the PMC full text the search tool already
downloaded (``pubmed_search_with_fulltext``) sits unused beside it in
``Article.content`` -- present on 157 of those same 239 analyzed
articles, averaging ~14,000 characters and reaching 68,000. That is where
the published exemplar's class of detail lives: across three of those
runs the corpus abstracts carry 0.0-0.4 number-with-unit mentions per
thousand words against the exemplar knowledge base's 1.9, while their
unread full texts hold roughly ten times the absolute count (196
percentages and 19 dosed concentrations in one run, against 20 and 3 in
the abstracts it did send). So the ceiling on evidence detail here is
corpus *composition* -- abstracts only -- not this cap.

Reading full text in is not the fix either, and the arithmetic is the
reason. The assembled corpus already measures ~400 tokens per source, so
the 132-source production run ``d1273490`` sent roughly 52,000 tokens of
corpus; that run's ``research_overview``-bucket calls billed 337,400
prompt tokens over six attempts, ~56,200 each, i.e. the corpus is nearly
the whole prompt. The same corpus carrying full text would be an order
of magnitude larger than any context this chain's models offer, and
prompt tokens are billed like any other. Moving detail into the section
means *selecting* passages, not lifting a cap -- and note the section
that this corpus produced was not itself numerically thin (3.1
number-with-unit mentions per thousand words on ``d1273490``, above the
exemplar's own 1.9), so the shortfall ``ecc4ec10`` closed was the ask,
not the evidence.

None of the above bounds *how many* sources the corpus holds, and that is
a separate failure with its own measurement. Every parsed search result is
marked ``used_in_analysis`` (``tools/response_parser.py``) and deep
verification appends its probe articles every cycle
(``reflection/deep_verification_evidence.merge_retrieved_articles``), so
the analyzed set grows without bound across a long run. Production
extended run ``bc77950f`` (2026-09-08, cycle 2 interim overview) reached
``prompt_tokens=126,975``; ``openrouter/minimax/minimax-m3:free`` dropped
the stream mid-reasoning on 8 of 8 attempts across two durable task
attempts, and the first fallback answered only at 108,753 prompt tokens on
the third -- 11 provider requests against a ~100/day free cap and ~50
minutes for one answer. ``RESEARCH_OVERVIEW_MAX_SOURCES`` below is the cap
that fixes that, and it is **orthogonal to this one**: it bounds how many
sources are sent, this bounds how much of each. Neither substitutes for
the other, so removing either re-opens a different failure.
"""


RESEARCH_OVERVIEW_MAX_SOURCES: Final = 130
"""How many analyzed sources the corpus may carry.

Set at the largest corpus this chain is known to answer: the assembled
corpus measures ~400 tokens per source, so 130 sources is ~52,000 tokens
of corpus, which is what production run ``d1273490`` sent (132 sources,
~56,200 prompt tokens per call) and had answered. The same three calls
that share this corpus at the terminal firing (draft, accuracy review,
knowledge base's outline, whose own writing calls resend it once per
theme) still fit their output budget beside it. Capping here covers all
of them, since each reaches the corpus through ``_build_evidence_corpus``.
"""


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

    The analyzed list is round-robined across its sources and then cut to
    ``RESEARCH_OVERVIEW_MAX_SOURCES``. Selection is positional, never a
    global sort by ``retrieval_score``: that score floors every web result
    at a normalized 0.0, so sorting by it would drop the web sources whole
    rather than thin every source evenly. Round-robin's first row is one
    article per source, so every source type present survives the cut.

    Evidence ids are assigned by presentation order (contiguous
    ``evidence-1..N`` over the selected articles); downstream consumers
    treat the id as an opaque handle and the app re-resolves cited topics by
    title, so the numbering carries no rank meaning.
    """
    analyzed = [
        article for article in (articles or []) if article.used_in_analysis
    ]
    selected = _interleave_by_source(analyzed)[:RESEARCH_OVERVIEW_MAX_SOURCES]
    corpus: dict[str, dict[str, Any]] = {}
    for index, article in enumerate(selected):
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


def prompt_context(state: WorkflowState) -> PromptRunContext:
    """The run-scoped prompt context this node's calls render against.

    Args:
        state: The workflow state at the terminal synthesis node.

    Returns:
        The tool registry and run guidance every call here is given.
    """
    return PromptRunContext(
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )

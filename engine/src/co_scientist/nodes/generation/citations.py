"""Structured citation utilities for hypothesis generation.

Replaces fragile author-year string matching with explicit citation keys.
All sources use sequential [C*] keys regardless of type — domain-agnostic
and works uniformly for papers, knowledge-graph statements, CVE entries, etc.

Usage:
  1. Build a ReferenceIndex before generation.
  2. Inject reference_index.text into LLM prompts via
  citation_reference_section.
  3. After the LLM writes literature_grounding, call resolve_citation_keys()
     to build citation_map from the keys it used.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import GenerationMethod, Hypothesis


@dataclass
class ReferenceIndex:
    """Bidirectional map: citation key ↔ full source metadata + prompt text."""

    text: str
    """Formatted reference list for LLM prompt injection, e.g.:
    '[C1] Smith et al., 2023 — Targeted therapies for KRAS...'
    '[C3] INDRA: KRAS → RAF1 [Activation] (belief: 0.95)'
    Empty string when no sources are available.
    """

    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    """key → source dict, e.g. {'C1': {'type': 'paper', 'title': ..., ...}}"""

    def is_empty(self) -> bool:
        """Returns True when no reference sources have been indexed."""
        return not self.sources


def _paper_citation_label(
    authors: list[str], year: int | None, title: str
) -> str:
    """Build the short author/year (or title-fallback) label for a citation.

    Args:
        authors: article authors, "First [Middle] Last" format.
        year: publication year, if known.
        title: article title, used as a fallback label source.

    Returns:
        "<Surname> et al., <year>" when a year is known, else a truncated
        title.
    """
    # Assumes "First [Middle] Last" author-string format; takes the last
    # whitespace-separated token as the surname.
    first_author = authors[0].strip().split()[-1] if authors else "Unknown"
    # Fall back to a truncated title when no year is known, since
    # "et al., None" would be a confusing citation label.
    return f"{first_author} et al., {year}" if year else title[:50]


def _article_paper_fields(
    article: Any,
) -> tuple[str, str, list[str], int | None]:
    """Extract title/url/authors/year from an article, defaulting empties.

    Args:
        article: An Article object (or article-shaped object) from a lit
            review pass.

    Returns:
        Tuple of (title, url, authors, year), with title/url/authors
        defaulted to falsy-safe empty values when absent.
    """
    title = getattr(article, "title", "") or ""
    url = getattr(article, "url", "") or ""
    authors = getattr(article, "authors", []) or []
    year = getattr(article, "year", None)
    return title, url, authors, year


def _paper_reference_entries(
    articles: list[Any] | None,
    start_counter: int,
) -> tuple[list[str], dict[str, dict[str, Any]], int]:
    """Build [C*] reference lines/sources for analyzed lit-review articles.

    Only includes articles with used_in_analysis=True — only papers actually
    read/analyzed (not just found by search) are trustworthy enough to
    ground a hypothesis.

    Args:
        articles: Article objects from state.articles.
        start_counter: First [C*] key number to assign.

    Returns:
        Tuple of (formatted lines, key -> source dict, next free counter).
    """
    sources: dict[str, dict[str, Any]] = {}
    lines: list[str] = []
    counter = start_counter

    for article in articles or []:
        if not getattr(article, "used_in_analysis", False):
            continue
        key = f"C{counter}"
        title, url, authors, year = _article_paper_fields(article)
        label = _paper_citation_label(authors, year, title)
        lines.append(f"[{key}] {label} — {title[:80]}")
        sources[key] = {
            "type": "paper",
            "title": title,
            "url": url,
            "authors": authors,
            "year": year,
        }
        counter += 1

    return lines, sources, counter


def _enrichment_reference_entries(
    context_enrichment_sources: list[dict[str, Any]] | None,
    start_counter: int,
) -> tuple[list[str], dict[str, dict[str, Any]], int]:
    """Build [C*] reference lines/sources for external enrichment sources.

    These come from domain-specific tool integrations run earlier in the
    pipeline (e.g. INDRA statements, CVE entries); "display" is a
    pre-formatted, human-readable summary.

    Args:
        context_enrichment_sources: Structured items from
            state.context_enrichment_sources.
        start_counter: First [C*] key number to assign.

    Returns:
        Tuple of (formatted lines, key -> source dict, next free counter).
    """
    sources: dict[str, dict[str, Any]] = {}
    lines: list[str] = []
    counter = start_counter

    for item in context_enrichment_sources or []:
        key = f"C{counter}"
        display = item.get("display", "External source")
        lines.append(f"[{key}] {display}")
        sources[key] = {
            "type": "knowledge_graph",
            "display": display,
            "tool_id": item.get("tool_id", ""),
            "data": item.get("data", {}),
        }
        counter += 1

    return lines, sources, counter


def build_reference_index(
    articles: list[Any] | None,
    context_enrichment_sources: list[dict[str, Any]] | None,
) -> ReferenceIndex:
    """Build a sequential reference index from lit-review articles and sources.

    All sources share a single [C*] key namespace — domain-agnostic.
    Papers come first (they're the primary grounding), enrichment sources
    follow.
    Only includes articles with used_in_analysis=True.

    Args:
        articles: Article objects from state.articles
        context_enrichment_sources: Structured items from
            state.context_enrichment_sources

    Returns:
        ReferenceIndex with formatted text and sources dict
    """
    # Papers first; the returned counter continues into the enrichment pass
    # below so papers and enrichment sources share one continuous [C*] key
    # sequence.
    paper_lines, sources, counter = _paper_reference_entries(articles, 1)
    enrichment_lines, enrichment_sources, _ = _enrichment_reference_entries(
        context_enrichment_sources, counter
    )
    sources.update(enrichment_sources)

    return ReferenceIndex(
        text="\n".join(paper_lines + enrichment_lines), sources=sources
    )


def _record_citation_key(
    raw_key: str,
    sources: dict[str, dict[str, Any]],
    seen: set[str],
    result: dict[str, dict[str, Any]],
) -> None:
    """Resolve one raw "[Cn]" occurrence into result, if valid and unseen.

    Keys the LLM hallucinated or mistyped (not present in sources) are
    dropped silently rather than raising, since citation_map is best-effort
    metadata, not a correctness-critical field.
    """
    key = raw_key[1:-1]  # strip brackets → "C1"
    if key not in sources or key in seen:
        return
    result[key] = sources[key]
    seen.add(key)


def resolve_citation_keys(
    literature_grounding: str | None,
    sources: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Parse [C*] keys from text and resolve them to source metadata.

    Returns a citation_map dict: {key: full source metadata dict}.
    Keys that appear in the text but are absent from sources are silently
    dropped.
    Preserves insertion order (first occurrence of each key).
    """
    # Nothing to resolve without grounding text to scan or a source table to
    # resolve keys against.
    if not literature_grounding or not sources:
        return {}
    # Extract every [C<n>] occurrence in order; duplicate occurrences are
    # collapsed below while insertion order (first occurrence) is preserved
    # via the seen set plus dict insertion order.
    keys = re.findall(r"\[C\d+\]", literature_grounding)
    seen: set[str] = set()
    result: dict[str, dict[str, Any]] = {}
    for raw_key in keys:
        _record_citation_key(raw_key, sources, seen, result)
    return result


def hypothesis_from_llm_output(
    hyp_data: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    generation_method: GenerationMethod,
    **extra: Any,
) -> Hypothesis:
    """Build a Hypothesis from a raw LLM hypothesis dict.

    Extracts the shared fields (text/category/explanation/literature_grounding/
    experiment), resolves citation keys against ``sources``, and applies the
    default score and initial Elo. ``extra`` supplies generation-path-specific
    kwargs such as ``debate_id`` or ``novelty_validation``.

    Args:
        hyp_data: Raw hypothesis dict emitted by the LLM.
        sources: Reference-index sources for citation-key resolution.
        generation_method: The generation path that produced the hypothesis.
        **extra: Additional Hypothesis kwargs specific to the caller.

    Returns:
        The constructed Hypothesis.
    """
    # Captured once so it can be reused both for the Hypothesis field and
    # for citation-key resolution below without re-reading hyp_data.
    literature_grounding = hyp_data.get("literature_grounding")
    return Hypothesis(
        # Different prompt schemas key the hypothesis text differently
        # ("hypothesis" vs "text"); support both without requiring every
        # caller to normalize the raw LLM dict first.
        text=hyp_data.get("hypothesis") or hyp_data.get("text", ""),
        category=hyp_data.get("category"),
        explanation=hyp_data.get("explanation"),
        literature_grounding=literature_grounding,
        experiment=hyp_data.get("experiment"),
        score=0.0,
        elo_rating=INITIAL_ELO_RATING,
        generation_method=generation_method,
        citation_map=resolve_citation_keys(literature_grounding, sources),
        **extra,
    )

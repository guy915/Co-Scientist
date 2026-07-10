"""Formatting helpers shared across the generation prompt builders."""

from typing import Any

# Formatting helpers for generate node
# Used by the generation prompt getters in this module (draft and debate);
# each turns an optional user input into prompt-ready text, substituting a
# sensible default when the input is absent.


def format_preferences(preferences: str | None) -> str:
    """Format user preferences for prompts."""
    if preferences:
        return preferences
    return "Focus on novelty, testability, and potential impact."


def format_attributes(attributes: list[str] | None) -> str:
    """Format user attributes for prompts."""
    if attributes:
        return "\n".join(f"- {attr}" for attr in attributes)
    return "- Novel\n- Testable\n- Impactful"


def format_user_hypotheses(user_hypotheses: list[str] | None) -> str:
    """Format user-provided starting hypotheses for prompts."""
    if user_hypotheses:
        return "\n".join(f"- {hyp}" for hyp in user_hypotheses)
    return "No user-provided starting hypotheses."


def format_supervisor_guidance_for_generation(
    supervisor_guidance: dict[str, Any] | None,
) -> str:
    """Format supervisor guidance for generation prompts.

    Renders the guidance as a research-strategy section.
    """
    if not supervisor_guidance:
        return ""

    # Unlike the other guidance formatters, this reads a free-text
    # "research_plan" key rather than SUPERVISOR_SCHEMA fields, so it only
    # renders when a caller supplies that plan-style guidance shape.
    research_plan = supervisor_guidance.get("research_plan", "")
    if research_plan and research_plan.strip():
        return f"""
## Research Strategy

{research_plan}
"""
    return ""


def _format_pdf_status(article: Any) -> str:
    """Format the PDF availability status for one article's metadata line."""
    if article.pdf_links:
        return f"Available - {article.pdf_links[0]}"
    return "No PDF found (abstract only)"


def _used_articles(articles: list[Any]) -> list[Any]:
    """Filter to articles marked used_in_analysis=True."""
    return [art for art in articles if art.used_in_analysis]


def _format_article_authors(article: Any) -> str:
    """Format up to 3 authors, with an 'et al.' suffix when there are more."""
    authors = ", ".join(article.authors[:3])
    if len(article.authors) > 3:
        return f"{authors} et al."
    return authors


def _format_article_entry(index: int, article: Any) -> str:
    """Format one analyzed article's metadata block."""
    return (
        f"**{index + 1}. {article.title}**\n"
        f"   - Authors: {_format_article_authors(article)}\n"
        f"   - Year: {article.year or 'Unknown'}\n"
        f"   - Citations: {article.citations}\n"
        f"   - PDF: {_format_pdf_status(article)}\n"
        f"   - URL: {article.url}"
    )


def format_articles_metadata(articles: list[Any]) -> str:
    """Format analyzed articles with metadata for tool-based generation prompts.

    Returns structured list of articles with titles, authors, year, citations,
    pdf availability.
    Only includes articles with used_in_analysis=True.
    """
    if not articles:
        return ""

    used_articles = _used_articles(articles)
    if not used_articles:
        return ""

    articles_list_text = "\n\n".join(
        _format_article_entry(i, art) for i, art in enumerate(used_articles)
    )

    n = len(used_articles)
    return (
        "\n### Papers Analyzed in Literature Review\n\n"
        f"These {n} papers were ranked highest and analyzed."
        " Some may have had accessibility issues"
        " (abstracts only, paywalls, captchas).\n"
        "You can use tools to:\n"
        "- Try accessing PDFs that weren't available initially\n"
        "- Query specific papers for detailed information\n"
        "- Search for alternative papers if these have issues\n"
        f"\n{articles_list_text}\n"
    )


def _build_citation_reference_section(reference_list: str) -> str:
    """Build the Citation Reference List prompt section.

    Returns an empty string when reference_list is empty so the LLM
    never sees citation instructions that don't apply to its run.
    The section is intentionally domain-agnostic — no INDRA/KG language.
    """
    if not reference_list.strip():
        return ""
    return (
        "\n## Citation Reference List\n\n"
        "Use **only** these `[C*]` citation keys inline in"
        " `literature_grounding` "
        "— do NOT invent author-year citations.\n\n" + reference_list + "\n"
    )

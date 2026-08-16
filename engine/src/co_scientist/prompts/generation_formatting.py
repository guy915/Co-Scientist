"""Formatting helpers shared across the generation prompt builders."""

from typing import Any

from ._common import _csv_value, _guidance_items

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


# Header for each writer mode's own slice of config_synthesis. The
# supervisor writes one list per mode because the two writers are asked for
# different things -- a draft is written straight from the literature, a
# debate is argued out over turns -- so guidance that sharpens one can be
# noise or an outright miscue in the other.
_MODE_INSTRUCTION_HEADERS = {
    "draft_instructions": "\n**How to draft in this run:**\n",
    "debate_instructions": "\n**How to run the debate in this run:**\n",
}


def _format_guidance_bullets(header: str, value: Any) -> list[str]:
    """Render one bolded header plus a bullet per item, or nothing."""
    items = _guidance_items(value)
    if not items:
        return []
    return [header, *(f"- {item}\n" for item in items)]


def format_config_generation_guidance(
    supervisor_guidance: dict[str, Any], instructions_key: str
) -> list[str]:
    """Format the config_synthesis slices a writing agent should read.

    `preferences` is the run's "what makes a good idea" list, which the
    schema has always described as steering generation as well as review
    even though only the review prompt read it back out. It is rendered
    here alongside the mode's own instruction list.

    Args:
        supervisor_guidance: Supervisor guidance dict from workflow state.
        instructions_key: The config_synthesis field holding this writer
            mode's instructions; a key of `_MODE_INSTRUCTION_HEADERS`.

    Returns:
        Section lines, or an empty list when the run carries neither
        preferences nor instructions for this mode.
    """
    config = supervisor_guidance.get("config_synthesis")
    if not isinstance(config, dict):
        return []
    sections = _format_guidance_bullets(
        "**Preferences (a good idea should satisfy):**\n",
        config.get("preferences"),
    )
    sections.extend(
        _format_guidance_bullets(
            _MODE_INSTRUCTION_HEADERS[instructions_key],
            config.get(instructions_key),
        )
    )
    return sections


def format_supervisor_guidance_for_generation(
    supervisor_guidance: dict[str, Any] | None,
) -> str:
    """Format supervisor guidance for the draft-with-tools generation prompt.

    This used to render a free-text "research_plan" key, which no run ever
    supplies: `research_plan` is what the *streamed output payload* renames
    supervisor_guidance to, not a field inside it, so the draft writer was
    handed an empty block on every real run while every other agent read
    the plan. It now reads the same SUPERVISOR_SCHEMA fields the sibling
    formatters do.

    Args:
        supervisor_guidance: Supervisor guidance dict from workflow state.

    Returns:
        A guidance section, or an empty string when the plan carries
        nothing the drafting writer acts on.
    """
    if not isinstance(supervisor_guidance, dict) or not supervisor_guidance:
        return ""

    # Every .get() below is isinstance-guarded because production runs on a
    # provider whose json_object mode does not enforce the schema, so an
    # object field can come back as a scalar.
    workflow_plan = supervisor_guidance.get("workflow_plan")
    generation_phase = (
        workflow_plan.get("generation_phase")
        if isinstance(workflow_plan, dict)
        else None
    )
    sections = []
    if isinstance(generation_phase, dict) and generation_phase.get(
        "focus_areas"
    ):
        focus = _csv_value(generation_phase["focus_areas"])
        sections.append(f"**Focus on:** {focus}\n\n")
    sections.extend(
        format_config_generation_guidance(
            supervisor_guidance, "draft_instructions"
        )
    )
    if not sections:
        return ""
    return "## Supervisor Guidance for Generation\n\n" + "".join(sections)


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

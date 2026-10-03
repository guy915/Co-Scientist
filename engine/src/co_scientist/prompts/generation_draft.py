"""Generation prompt formatting, tool instructions and draft assembly."""

from dataclasses import dataclass, field
from typing import Any

from co_scientist.prompts._common import (
    PromptRunContext,
    PromptSections,
    _format_meta_review_context,
    _run_guidance_section,
    format_lab_constraints_section,
)
from co_scientist.prompts.loading import _build_prompt

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


def _format_tool_entry(tool_config: Any) -> list[str]:
    """Format one tool's markdown bullet entry, plus its indented snippet.

    Args:
        tool_config: A ToolConfig with ``mcp_tool_name``, ``description``,
            and an optional ``prompt_snippet``.

    Returns:
        Lines for this tool's entry, ending with a blank line separating it
        from the next tool.
    """
    lines = [f"- `{tool_config.mcp_tool_name}`: {tool_config.description}"]

    # Add prompt snippet if available
    # prompt_snippet is per-tool usage guidance authored in the YAML
    # config, indented here so it nests under the tool's list entry.
    if tool_config.prompt_snippet:
        snippet_lines = tool_config.prompt_snippet.strip().split("\n")
        lines.extend(f"  {line}" for line in snippet_lines)

    lines.append("")  # blank line between tools
    return lines


def _resolve_tool_registry(
    tool_ids: list[str],
    tool_registry: Any | None,
) -> tuple[Any | None, list[str]]:
    """Fall back to the global tool registry when none is supplied.

    Also defaults tool_ids to the draft-generation workflow's tool list when
    the caller passed none, since that default only makes sense once a
    registry is available to resolve it against.

    Args:
        tool_ids: Caller-supplied tool IDs, possibly empty.
        tool_registry: Caller-supplied registry, or None to fall back to the
            global one.

    Returns:
        The resolved (tool_registry, tool_ids) pair. tool_registry may still
        be None if the global registry is unavailable.
    """
    if tool_registry is None:
        try:
            from co_scientist.config import (
                get_tool_registry,
            )

            tool_registry = get_tool_registry()
            # If no tool_ids provided, get them from draft workflow
            if not tool_ids:
                tool_ids = tool_registry.get_tools_for_workflow(
                    "draft_generation"
                )
        except Exception:
            pass

    return tool_registry, tool_ids


def _tool_entry_sections(tool_id: str, tool_registry: Any) -> list[str]:
    """Format one tool_id's entry lines, or [] if unknown/disabled."""
    tool_config = tool_registry.get_tool(tool_id)
    if not tool_config or not tool_config.enabled:
        return []
    return _format_tool_entry(tool_config)


def build_tool_instructions(
    tool_ids: list[str],
    tool_registry: Any | None = None,
) -> str:
    """Build dynamic tool instructions section from tool registry.

    Args:
        tool_ids: List of tool IDs to include in instructions
        tool_registry: ToolRegistry instance with tool configurations

    Returns:
        Formatted markdown section describing available tools
    """
    tool_registry, tool_ids = _resolve_tool_registry(tool_ids, tool_registry)

    if not tool_registry or not tool_ids:
        # Minimal fallback when no config available
        return (
            "No tool configuration available."
            " Literature tools may not be accessible."
        )

    sections = []
    for tool_id in tool_ids:
        sections.extend(_tool_entry_sections(tool_id, tool_registry))

    if not sections:
        return "No tools available."

    return "\n".join(sections).strip()


def _resolve_draft_tool_instructions(tool_registry: Any | None) -> str:
    """Resolve tool instructions for the draft-generation workflow."""
    tool_ids = []
    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("draft_generation")
    return build_tool_instructions(tool_ids, tool_registry)


@dataclass(frozen=True)
class DraftPromptRequest:
    """Inputs for the Phase 1 draft-with-tools prompt.

    Attributes:
        research_goal: The run's research goal.
        hypotheses_count: How many draft hypotheses to produce.
        articles: Literature-review articles for citation metadata.
        articles_with_reasoning: The literature-review synthesis text.
        preferences: Free-text user preferences, if any.
        attributes: Desired hypothesis attributes.
        user_hypotheses: Seed hypotheses supplied by the user.
        instructions: Custom drafting instructions.
        max_iterations: The agent's max tool iterations.
        reference_list: The ``[C*]`` citation reference list.
        research_expansion_section: Rendered research-expansion guidance
            for post-iteration generate cycles (E11b); empty on the
            initial cycle, which keeps focused-grounding behavior.
        falsified_assumptions_section: Rendered avoid-or-rework guidance
            for assumptions verification found incorrect (K9); empty
            until deep verification records one.
        lab_constraints: The scientist's lab constraints elicited by
            the goal interview (K5); empty or absent renders no section.
        skills_section: Rendered science-skills instructions, appended
            to the tool instructions. Empty unless the drafting pass was
            actually given them, which depends on the deployment and on
            whether commands can be confined on this host -- so it is
            passed in by the caller that offered them rather than
            derived here from what is installed.
        context: Run-scoped prompt context (supervisor guidance,
            meta-review, tool registry, run setup/focus guidance).
    """

    research_goal: str
    hypotheses_count: int
    articles: list[Any] | None = None
    articles_with_reasoning: str | None = None
    preferences: str | None = None
    attributes: list[str] | None = None
    user_hypotheses: list[str] | None = None
    instructions: str | None = None
    max_iterations: int = 8
    reference_list: str = ""
    research_expansion_section: str = ""
    falsified_assumptions_section: str = ""
    lab_constraints: list[str] | None = None
    skills_section: str = ""
    context: PromptRunContext = field(default_factory=PromptRunContext)


def _build_draft_prompt_variables(req: DraftPromptRequest) -> dict[str, Any]:
    """Build the template variables for the Phase 1 draft-with-tools prompt."""
    return {
        "goal": req.research_goal,
        "hypotheses_count": req.hypotheses_count,
        "preferences": format_preferences(req.preferences),
        "attributes": format_attributes(req.attributes),
        "user_hypotheses": format_user_hypotheses(req.user_hypotheses),
        "supervisor_guidance": format_supervisor_guidance_for_generation(
            req.context.supervisor_guidance
        ),
        "articles_with_reasoning": req.articles_with_reasoning
        or "no literature review summary available - examine papers"
        " below directly.",
        "articles_metadata": format_articles_metadata(req.articles or []),
        "citation_reference_section": _build_citation_reference_section(
            req.reference_list or ""
        ),
        "max_iterations": req.max_iterations,
        "instructions": req.instructions
        or "Focus on creative ideation - draft diverse hypotheses"
        " based on literature gaps.",
        "tool_instructions": _resolve_draft_tool_instructions(
            req.context.tool_registry
        )
        + req.skills_section,
        # Empty outside their conditions, so the initial-cycle prompt
        # renders exactly what it did before these sections existed.
        "research_expansion_section": req.research_expansion_section,
        "falsified_assumptions_section": req.falsified_assumptions_section,
        "lab_constraints_section": format_lab_constraints_section(
            req.lab_constraints
        ),
    }


# Renders prompts/generation_draft_with_tools.md for the Phase 1 draft
# agent in agents/generation/literature_tools/draft.py (schema:
# GENERATION_DRAFT_SCHEMA via the prompt-name lookup). Focuses on reading
# papers and identifying gaps, with the lit review summary included as
# context (not instructions).
def get_draft_prompt_with_tools(
    req: DraftPromptRequest,
) -> tuple[str, dict[str, Any] | None]:
    """Get the Phase 1 draft prompt; params doc'd on DraftPromptRequest.

    Args:
        req: The resolved draft-prompt request.

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    return _build_prompt(
        "generation_draft_with_tools",
        _build_draft_prompt_variables(req),
        sections=PromptSections(
            meta_review_context=_format_meta_review_context(
                req.context.meta_review
            ),
            run_guidance=_run_guidance_section(req.context),
        ),
        tool_registry=req.context.tool_registry,
    )

"""Prompt builders and formatting helpers for the generation nodes."""
# pylint: disable=inconsistent-quotes

from typing import Any

from co_scientist.prompts._common import _format_authors
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts._common import _format_run_guidance
from co_scientist.prompts._common import _format_year
from co_scientist.prompts.loading import _build_prompt
from co_scientist.prompts.loading import _get_domain_variables
from co_scientist.prompts.loading import load_prompt
from co_scientist.prompts.loading import load_prompt_with_schema


# Renders prompts/hypothesis_novelty_analysis.md, called by
# nodes/generation/literature_tools/validate.py once per (draft hypothesis,
# paper) pair (paired there with HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA).
def get_hypothesis_novelty_analysis_prompt(hypothesis_text: str, title: str,
                                           authors: list[str], year: int | None,
                                           fulltext: str) -> str:
    """Get the prompt for analyzing a paper for hypothesis novelty."""
    return load_prompt(
        "hypothesis_novelty_analysis",
        {
            "hypothesis_text": hypothesis_text,
            "title": title,
            "authors": _format_authors(authors),
            "year": _format_year(year),
            "fulltext": fulltext,
        },
    )


def _format_hypotheses_with_novelty_analyses(
        hypotheses_with_analyses: list[dict[str, Any]]) -> str:
    """Render draft hypotheses and their per-paper novelty analyses.

    Shared by both validation-synthesis prompt builders so the draft/analysis
    layout has a single definition.

    Args:
        hypotheses_with_analyses: Draft hypotheses, each with a ``draft`` dict
            and a ``novelty_analyses`` list of ``{paper_metadata, analysis}``.

    Returns:
        The formatted block, sections joined by blank lines.
    """
    hypotheses_text = []
    for i, hyp_data in enumerate(hypotheses_with_analyses, 1):
        draft = hyp_data.get("draft", {})
        analyses = hyp_data.get("novelty_analyses", [])

        hyp_section = f"""### draft hypothesis {i}
**text:** {draft.get('text', 'Unknown')}
**gap reasoning:** {draft.get('gap_reasoning', 'N/A')}
**literature sources:** {draft.get('literature_sources', 'N/A')}

**novelty analyses ({len(analyses)} papers examined):**
"""

        for j, analysis_data in enumerate(analyses, 1):
            paper_meta = analysis_data.get("paper_metadata", {})
            analysis = analysis_data.get("analysis", {})
            p_title = paper_meta.get('title', 'Unknown')
            p_year = paper_meta.get('year', 'N/A')

            paper_analysis = (
                f"\n**paper {j}:** {p_title} ({p_year})\n"
                f"- methods used:"
                f" {analysis.get('methods_used', 'N/A')}\n"
                f"- populations studied:"
                f" {analysis.get('populations_studied', 'N/A')}\n"
                f"- mechanisms investigated:"
                f" {analysis.get('mechanisms_investigated', 'N/A')}\n"
                f"- key findings:"
                f" {analysis.get('key_findings', 'N/A')}\n"
                f"- stated limitations:"
                f" {analysis.get('stated_limitations', 'N/A')}\n"
                f"- future work suggested:"
                f" {analysis.get('future_work_suggested', 'N/A')}\n"
                f"- **novelty assessment:"
                f" {analysis.get('novelty_assessment', 'N/A')}**\n"
                f"- overlap explanation:"
                f" {analysis.get('overlap_explanation', 'N/A')}\n")
            hyp_section += paper_analysis

        hypotheses_text.append(hyp_section)
    return "\n\n".join(hypotheses_text)


# Tool-less validation-synthesis variant. No production caller: the
# pipeline uses get_validation_synthesis_prompt_with_tools below; this one
# is retained for tests and tool-free experimentation.
def get_hypothesis_validation_synthesis_prompt(
    research_goal: str,
    hypotheses_with_analyses: list[dict[str, Any]],
    articles: list[Any] | None = None,
    tool_registry: Any | None = None,
    reference_list: str = "",
) -> str:
    """Get the prompt for validation synthesis based on novelty analyses.

    Args:
        research_goal: The research goal
        hypotheses_with_analyses: List of draft hypotheses with novelty analyses
        articles: Optional list of Article objects for citation metadata
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys

    Returns:
        Formatted prompt string
    """
    variables = {
        "research_goal":
            research_goal,
        "hypotheses_with_analyses":
            _format_hypotheses_with_novelty_analyses(hypotheses_with_analyses),
        "articles_metadata":
            format_articles_metadata(articles or []),
        "citation_reference_section":
            _build_citation_reference_section(reference_list),
    }

    # Inject domain-specific prompt customizations
    variables.update(_get_domain_variables(tool_registry))

    return load_prompt("hypothesis_validation_synthesis", variables)


def _build_already_validated_context(
        already_validated_texts: list[str] | None) -> str:
    """Build diversity constraint block for retry path.

    Injected only when retrying failed batches individually, so the model
    knows which hypothesis territory is already claimed and can pivot away.
    """
    if not already_validated_texts:
        return ""
    lines = "\n".join(f"- {t}" for t in already_validated_texts)
    return f"""
## Hypotheses Already Validated (Diversity Constraint)

The following hypotheses have already been validated and will be included in the final output.  # pylint: disable=line-too-long
Your output **must explore different mechanistic territory** from each of these.
If your draft overlaps significantly with any entry below, treat it as saturated and pivot:

{lines}

"""


# Renders prompts/hypothesis_validation_synthesis_with_tools.md for the
# Phase 2 validation agent in nodes/generation/literature_tools/validate.py.
# tool_instructions is built from the "validation" workflow's tool list so
# the agent knows which MCP search tools it may call while pivoting.
def get_validation_synthesis_prompt_with_tools(
    research_goal: str,
    hypotheses_with_analyses: list[dict[str, Any]],
    articles: list[Any] | None = None,
    articles_with_reasoning: str | None = None,
    max_iterations: int = 8,
    tool_registry: Any | None = None,
    reference_list: str = "",
    already_validated_texts: list[str] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get prompt for validation synthesis with tool access.

    This version includes tool instructions so the LLM can search for
    additional papers when deciding to pivot hypotheses.

    Args:
        research_goal: The research goal
        hypotheses_with_analyses: List of draft hypotheses with novelty analyses
        articles: Optional list of Article objects for citation metadata
        articles_with_reasoning: Literature review synthesis
        max_iterations: Max tool iterations for the agent
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys
        already_validated_texts: Hypothesis texts already validated
            (retry path only). Injected as a diversity constraint so the
            model avoids duplicate territory.
    """
    # Get tool IDs for validation workflow
    tool_ids = []
    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("validation")

    # Build dynamic tool instructions
    tool_instructions = build_tool_instructions(tool_ids, tool_registry)

    variables = {
        "research_goal":
            research_goal,
        "hypotheses_with_analyses":
            _format_hypotheses_with_novelty_analyses(hypotheses_with_analyses),
        "hypotheses_count":
            len(hypotheses_with_analyses),
        "articles_metadata":
            format_articles_metadata(articles or []),
        "articles_with_reasoning":
            articles_with_reasoning
            or "no literature review summary available.",
        "citation_reference_section":
            _build_citation_reference_section(reference_list or ""),
        "max_iterations":
            max_iterations,
        "tool_instructions":
            tool_instructions,
        "already_validated_context":
            _build_already_validated_context(already_validated_texts),
    }

    return _build_prompt(
        "hypothesis_validation_synthesis_with_tools",
        variables,
        tool_registry=tool_registry,
    )


# Called by nodes/generation/debate.py once per debate turn. Template
# choice depends on literature availability
# (generation_debate_and_literature vs generation_after_debate), and the
# final turn switches from free-form discussion to schema-constrained JSON
# output (GENERATION_SCHEMA).
def get_debate_generation_prompt(
    research_goal: str,
    hypotheses_count: int,
    transcript: str,
    supervisor_guidance: dict[str, Any] | None = None,
    preferences: str | None = None,
    attributes: str | list[str] | None = None,
    is_final_turn: bool = False,
    articles_with_reasoning: str | None = None,
    articles: list[Any] | None = None,
    tool_registry: Any | None = None,
    reference_list: str = "",
    meta_review: dict[str, Any] | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the debate-based hypothesis generation prompt.

    This uses a multi-turn debate strategy where experts discuss and refine
    hypotheses.
    The transcript accumulates over multiple turns until final hypotheses are
    generated.

    Args:
        research_goal: The research goal
        hypotheses_count: Number of hypotheses to generate
        transcript: Accumulated conversation transcript from previous turns
        supervisor_guidance: Optional guidance from supervisor
        preferences: Criteria for strong hypotheses
        attributes: Key attributes to prioritize
        is_final_turn: Whether this is the final turn (outputs JSON schema)
        articles_with_reasoning: Optional literature review synthesis for
            context
        articles: Optional list of Article objects for citation metadata
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys
        meta_review: Optional cross-iteration meta-review feedback
        run_setup_guidance: Optional durable run setup guidance text
        run_focus_guidance: Optional durable run focus guidance text

    Returns:
        Tuple of (formatted prompt string, JSON schema dict or None)
    """
    variables = {
        "goal":
            research_goal,
        "hypotheses_count":
            hypotheses_count,
        "transcript":
            transcript or "",
        "preferences":
            preferences
            or "Novel, testable, scientifically sound, specific, and diverse"
            " hypotheses",
        "attributes": (", ".join(attributes)
                       if attributes and isinstance(attributes, list) else
                       (attributes or "testable and falsifiable")),
    }

    # Add literature review if provided
    if articles_with_reasoning:
        variables["articles_with_reasoning"] = articles_with_reasoning

    # Add article metadata for citations
    variables["articles_metadata"] = format_articles_metadata(articles or [])
    variables["citation_reference_section"] = _build_citation_reference_section(
        reference_list or "")

    # Format supervisor guidance if available
    if supervisor_guidance and isinstance(supervisor_guidance, dict):
        guidance_sections = []
        has_content = False

        goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
        key_areas = goal_analysis.get("key_areas", [])
        if key_areas:
            if not has_content:
                guidance_sections.append("Key research areas to consider:\n")
                has_content = True
            for area in key_areas:
                guidance_sections.append(f"- {area}\n")

        workflow_plan = supervisor_guidance.get("workflow_plan", {})
        generation_phase = workflow_plan.get("generation_phase", {})
        if generation_phase:
            if not has_content:
                guidance_sections.append("Generation guidance:\n")
                has_content = True
            if generation_phase.get("focus_areas"):
                focus_areas = generation_phase["focus_areas"]
                if isinstance(focus_areas, list):
                    focus_areas = ", ".join(focus_areas)
                guidance_sections.append(f"Focus on: {focus_areas}\n")

        variables["supervisor_guidance"] = "".join(
            guidance_sections) if has_content else ""
    else:
        variables["supervisor_guidance"] = ""

    # Add meta-review context if available (blank on iteration 1).
    variables["meta_review_context"] = _format_meta_review_context(meta_review)
    variables["run_guidance"] = _format_run_guidance(run_setup_guidance,
                                                     run_focus_guidance)

    # Inject domain-specific prompt customizations
    variables.update(_get_domain_variables(tool_registry))

    # Determine which prompt to use based on literature availability
    prompt_name = ("generation_debate_and_literature"
                   if articles_with_reasoning else "generation_after_debate")

    # If final turn, append instruction to output JSON and use schema
    if is_final_turn:
        prompt, schema = load_prompt_with_schema(prompt_name, variables)

        # Append JSON output instructions for final turn
        # Concatenated verbatim after the rendered template (never run
        # through substitute_variables), so the literal braces in the JSON
        # example below need no {{}} escaping.
        final_instructions = """

## FINAL TURN - OUTPUT FORMAT

This is the final turn of the debate. Based on the discussion above, output your finalized hypothesis in JSON format with all four required components:

### 1. hypothesis (required)
Dense technical description following "We want to develop [X] to enable [Y]" format (2-3 sentences).
- Include specific technical details: algorithms, mechanisms, mathematical formulations  # pylint: disable=line-too-long
- Be precise about what will be developed and the technical approach

Example: "We want to develop a 'Dynamic Velocity Sentinel'—which monitors the rate of change in latent activation directions across early-to-mid layers rather than static depths—to enable anticipatory gating that triggers only when precursor signals cross a 'point of no return' for danger features."

### 2. explanation (required)
Clear explanation for technical audiences in layman terms (4-6 sentences).
- Core problem being addressed
- Why key mechanisms work
- How components interact
- Practical advantages

Example: "This approach addresses the computational bottleneck by focusing on early layers where precursor signals first emerge. Rather than analyzing static magnitudes, the technique tracks velocity—the rate of change—which provides earlier detection of trajectories toward dangerous outputs. The system employs autoencoders to identify danger features, with dynamic gating that triggers only when trajectories cross a learned threshold."

### 3. literature_grounding (required)
Explicit grounding with inline citation keys (2-4 sentences).
- If a Citation Reference List was provided above, use ONLY those `[C*]` keys (e.g. `[C1]`, `[C2]`, `[C3]`)
- Do NOT invent author-year citations — only use keys from the list
- If no Citation Reference List was provided, state: "This hypothesis is formulated without access to a literature review."  # pylint: disable=line-too-long

Example: "This approach builds on sparse autoencoder analysis [C1] and circuit tracing [C2]. The velocity monitoring concept addresses a gap in static-analysis methods [C3][C4]."

### 4. experiment (required)
Concrete experiment design with models, datasets, methodology, metrics, and validation (4-6 sentences).  # pylint: disable=line-too-long

Example format: "Objective: Demonstrate that velocity monitoring achieves comparable detection with reduced cost. Models: GPT-2 Medium, pre-trained SAE layers 1-6. Datasets: AdvBench harmful prompts (500 examples), HH-RLHF benign prompts (1000 examples). Methodology: (1) Implement velocity tracking, (2) Train threshold detector, (3) Compare against baseline. Metrics: Detection accuracy, timing, false positive rate, computational overhead. Validation: Success requires >90% detection, <5% false positives, >50% cost reduction."  # pylint: disable=line-too-long

---

Output exactly 1 hypothesis as valid JSON:
{
  "hypotheses": [
    {
      "hypothesis": "...",
      "explanation": "...",
      "literature_grounding": "...",
      "experiment": "..."
    }
  ]
}

IMPORTANT: Use plain text with standard punctuation (no LaTeX, no decorative Unicode).
"""
        prompt = prompt + final_instructions
        return prompt, schema
    else:
        # Non-final turns: no schema, just conversational
        prompt = load_prompt(prompt_name, variables)
        return prompt, None


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
        supervisor_guidance: dict[str, Any] | None) -> str:
    """Format supervisor guidance for generation prompts with research strategy
    section.
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


def format_articles_metadata(articles: list[Any]) -> str:
    """Format analyzed articles with metadata for tool-based generation prompts.

    Returns structured list of articles with titles, authors, year, citations,
    pdf availability.
    Only includes articles with used_in_analysis=True.
    """
    if not articles:
        return ""

    used_articles = [art for art in articles if art.used_in_analysis]
    if not used_articles:
        return ""

    articles_list_text = "\n\n".join([
        f"**{i+1}. {art.title}**\n"
        f"   - Authors: {', '.join(art.authors[:3])}{' et al.' if len(art.authors) > 3 else ''}\n"  # pylint: disable=line-too-long
        f"   - Year: {art.year or 'Unknown'}\n"
        f"   - Citations: {art.citations}\n"
        f"   - PDF: {'Available - ' + art.pdf_links[0] if art.pdf_links else 'No PDF found (abstract only)'}\n"  # pylint: disable=line-too-long
        f"   - URL: {art.url}" for i, art in enumerate(used_articles)
    ])

    n = len(used_articles)
    return ("\n### Papers Analyzed in Literature Review\n\n"
            f"These {n} papers were ranked highest and analyzed."
            " Some may have had accessibility issues"
            " (abstracts only, paywalls, captchas).\n"
            "You can use tools to:\n"
            "- Try accessing PDFs that weren't available initially\n"
            "- Query specific papers for detailed information\n"
            "- Search for alternative papers if these have issues\n"
            f"\n{articles_list_text}\n")


def _build_citation_reference_section(reference_list: str) -> str:
    """Build the Citation Reference List prompt section.

    Returns an empty string when reference_list is empty so the LLM
    never sees citation instructions that don't apply to its run.
    The section is intentionally domain-agnostic — no INDRA/KG language.
    """
    if not reference_list.strip():
        return ""
    return ("\n## Citation Reference List\n\n"
            "Use **only** these `[C*]` citation keys inline in"
            " `literature_grounding` "
            "— do NOT invent author-year citations.\n\n" + reference_list +
            "\n")


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
    # If no registry provided, try to get the global one
    if tool_registry is None:
        try:
            from co_scientist.config import get_tool_registry  # pylint: disable=import-outside-toplevel

            tool_registry = get_tool_registry()
            # If no tool_ids provided, get them from draft workflow
            if not tool_ids:
                tool_ids = tool_registry.get_tools_for_workflow(
                    "draft_generation")
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    if not tool_registry or not tool_ids:
        # Minimal fallback when no config available
        return ("No tool configuration available."
                " Literature tools may not be accessible.")

    sections = []

    for tool_id in tool_ids:
        tool_config = tool_registry.get_tool(tool_id)
        if not tool_config or not tool_config.enabled:
            continue

        # Add tool entry
        sections.append(
            f"- `{tool_config.mcp_tool_name}`: {tool_config.description}")

        # Add prompt snippet if available
        # prompt_snippet is per-tool usage guidance authored in the YAML
        # config, indented here so it nests under the tool's list entry.
        if tool_config.prompt_snippet:
            # Indent the snippet
            snippet_lines = tool_config.prompt_snippet.strip().split("\n")
            for line in snippet_lines:
                sections.append(f"  {line}")

        sections.append("")  # blank line between tools

    if not sections:
        return "No tools available."

    return "\n".join(sections).strip()


# Renders prompts/generation_draft_with_tools.md for the Phase 1 draft
# agent in nodes/generation/literature_tools/draft.py (schema:
# GENERATION_DRAFT_SCHEMA via the prompt-name lookup).
def get_draft_prompt_with_tools(
    research_goal: str,
    hypotheses_count: int,
    supervisor_guidance: dict[str, Any] | None = None,
    articles: list[Any] | None = None,
    articles_with_reasoning: str | None = None,
    preferences: str | None = None,
    attributes: list[str] | None = None,
    user_hypotheses: list[str] | None = None,
    instructions: str | None = None,
    max_iterations: int = 8,
    tool_registry: Any | None = None,
    reference_list: str = "",
    meta_review: dict[str, Any] | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get prompt for Phase 1: drafting hypotheses with tools.

    Uses generation_draft_with_tools.md template.
    Focuses on reading papers and identifying gaps.
    Includes lit review summary as context (not instructions).

    Args:
        research_goal: The research goal
        hypotheses_count: Number of hypotheses to draft
        supervisor_guidance: Optional guidance from supervisor
        articles: List of Article objects from literature review
        articles_with_reasoning: Literature review synthesis
        preferences: Criteria for strong hypotheses
        attributes: Key attributes to prioritize
        user_hypotheses: User-provided starting hypotheses
        instructions: Custom instructions
        max_iterations: Max tool iterations for the agent
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys
        meta_review: Optional cross-iteration meta-review feedback
        run_setup_guidance: Optional durable run setup guidance text
        run_focus_guidance: Optional durable run focus guidance text
    """
    # Get tool IDs for draft generation workflow
    tool_ids = []
    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("draft_generation")

    # Build dynamic tool instructions
    tool_instructions = build_tool_instructions(tool_ids, tool_registry)

    variables = {
        "goal":
            research_goal,
        "hypotheses_count":
            hypotheses_count,
        "preferences":
            format_preferences(preferences),
        "attributes":
            format_attributes(attributes),
        "user_hypotheses":
            format_user_hypotheses(user_hypotheses),
        "supervisor_guidance":
            format_supervisor_guidance_for_generation(supervisor_guidance),
        "articles_with_reasoning":
            articles_with_reasoning
            or "no literature review summary available - examine papers"
            " below directly.",
        "articles_metadata":
            format_articles_metadata(articles or []),
        "citation_reference_section":
            _build_citation_reference_section(reference_list or ""),
        "max_iterations":
            max_iterations,
        "instructions":
            instructions
            or "Focus on creative ideation - draft diverse hypotheses"
            " based on literature gaps.",
        "tool_instructions":
            tool_instructions,
    }

    return _build_prompt(
        "generation_draft_with_tools",
        variables,
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )

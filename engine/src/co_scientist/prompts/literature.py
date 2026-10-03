"""Prompt builders for literature review and hypothesis novelty validation."""

from dataclasses import dataclass
from typing import Any

from co_scientist.prompts._common import (
    _format_authors,
    _format_bullet_list,
    _format_csv_list,
    _format_meta_review_context,
    _format_year,
)
from co_scientist.prompts.generation_draft import (
    _build_citation_reference_section,
    build_tool_instructions,
    format_articles_metadata,
)
from co_scientist.prompts.loading import _build_prompt, load_prompt


@dataclass(frozen=True)
class LiteratureQueryInputs:
    """The user-supplied run inputs that steer query generation.

    Attributes:
        preferences: Free-text user preferences, if any.
        attributes: Desired hypothesis attributes.
        user_literature: Seed literature supplied by the user.
        user_hypotheses: Seed hypotheses supplied by the user.
    """

    preferences: str | None = None
    attributes: list[str] | None = None
    user_literature: list[str] | None = None
    user_hypotheses: list[str] | None = None


# Query-generation entry point used by
# agents/generation/literature_review/queries.py, paired
# there with LITERATURE_QUERY_SCHEMA. Returns a bare string (no schema in
# the tuple) because the schema is imported directly by the caller.
def get_literature_review_query_generation_prompt(
    research_goal: str,
    source_type: str = "academic",
    inputs: LiteratureQueryInputs | None = None,
    meta_review: dict[str, Any] | None = None,
) -> str:
    """Get source-aware query generation prompt.

    Knowledge-graph sources extract entity names, PubMed uses its query
    syntax, and other academic sources use natural-language queries.

    Args:
        research_goal: The research goal
        source_type: Type of literature source (from ToolConfig.source_type)
        inputs: The user-supplied run inputs steering query generation.
        meta_review: Meta-review synthesis from the previous iteration
            (audit E7); the queries should also retrieve what the
            critique flags as missing or weak. Renders nothing on
            iteration 1.

    Returns:
        Formatted prompt string
    """
    inputs = inputs or LiteratureQueryInputs()
    template_name = {
        "knowledge_graph": "literature_review_query_generation_indra",
        "pubmed": "literature_review_query_generation_pubmed",
    }.get(source_type, "literature_review_query_generation_generic")
    return load_prompt(
        template_name,
        {
            "research_goal": research_goal,
            "preferences": inputs.preferences or "None provided",
            "attributes": _format_csv_list(inputs.attributes),
            "user_literature": _format_bullet_list(inputs.user_literature),
            "user_hypotheses": _format_bullet_list(inputs.user_hypotheses),
            "meta_review_context": _format_meta_review_context(meta_review),
        },
    )


# Renders prompts/hypothesis_query_generation.md, paired with
# LITERATURE_QUERY_SCHEMA like the goal-level getter above. Kept separate from
# it because the task differs: that one explores a research goal, this one
# hunts for evidence that could confirm or refute one specific hypothesis, so
# its queries must key on that hypothesis's own entities.
def get_hypothesis_query_generation_prompt(
    research_goal: str,
    hypothesis: str,
) -> str:
    """Get the prompt for hypothesis-targeted literature search queries.

    Args:
        research_goal: The run's research goal, as context.
        hypothesis: The hypothesis whose mechanism the queries must target.

    Returns:
        Formatted prompt string.
    """
    return load_prompt(
        "hypothesis_query_generation",
        {"research_goal": research_goal, "hypothesis": hypothesis},
    )


# Renders prompts/literature_review_paper_analysis.md, called by
# agents/generation/literature_review/analysis.py once per fetched
# paper (paired there with
# LITERATURE_PAPER_ANALYSIS_SCHEMA).
def get_literature_review_paper_analysis_prompt(
    research_goal: str,
    title: str,
    authors: list[str],
    year: int | None,
    fulltext: str,
) -> str:
    """Get the prompt for analyzing a single paper."""
    return load_prompt(
        "literature_review_paper_analysis",
        {
            "research_goal": research_goal,
            "title": title,
            "authors": _format_authors(authors),
            "year": _format_year(year),
            "fulltext": fulltext,
        },
    )


# Renders prompts/literature_review_relevance_batch.md, called by
# evidence/relevance.py once per batch of
# candidate papers in the pre-budget pool (paired there with
# LITERATURE_RELEVANCE_BATCH_SCHEMA): the semantic half of the hybrid
# retrieval score (fidelity-audit G5). candidates_block is a
# pre-formatted text block, not a Python list -- see
# relevance._build_candidates_block.
def get_literature_review_relevance_batch_prompt(
    research_goal: str,
    candidates_block: str,
) -> str:
    """Get the prompt for judging one batch of candidates' relevance."""
    return load_prompt(
        "literature_review_relevance_batch",
        {
            "research_goal": research_goal,
            "candidates_block": candidates_block,
        },
    )


def _format_paper_analyses(paper_analyses: list[dict[str, Any]]) -> str:
    """Render each paper's metadata and analysis as a markdown section.

    Sections are numbered in input order.

    Args:
        paper_analyses: Per-paper entries, each with a ``metadata`` dict and
            an ``analysis`` dict of the fields analyzed for that paper.

    Returns:
        The formatted block, sections joined by blank lines.
    """
    analyses_text = []
    for i, analysis_data in enumerate(paper_analyses, 1):
        metadata = analysis_data.get("metadata", {})
        analysis = analysis_data.get("analysis", {})

        paper_section = f"""### paper {i}: {metadata.get("title", "Unknown")}
**authors:** {", ".join(metadata.get("authors", ["Unknown"]))}
**year:** {metadata.get("year", "Unknown")}

**key findings:** {analysis.get("key_findings", "N/A")}

**gaps identified:** {analysis.get("gaps_identified", "N/A")}

**future work suggested:** {analysis.get("future_work", "N/A")}

**methodology limitations:** {analysis.get("methodology_limitations", "N/A")}

**unexplored areas:** {analysis.get("unexplored_areas", "N/A")}

**relevance:** {analysis.get("relevance", "N/A")}
"""
        analyses_text.append(paper_section)

    return "\n\n".join(analyses_text)


# Renders prompts/literature_review_synthesis.md for
# agents/generation/literature_review/synthesis.py: flattens the
# per-paper analyses into one
# markdown block and optionally appends knowledge-graph background as a
# "Mechanistic Background" section (empty string when unavailable).
def get_literature_review_synthesis_prompt(
    research_goal: str,
    paper_analyses: list[dict[str, Any]],
    background_context: str = "",
    meta_review: dict[str, Any] | None = None,
) -> str:
    """Get the prompt for synthesizing paper analyses.

    Args:
        research_goal: The research goal the synthesis must inform.
        paper_analyses: Per-paper analyses produced by Phase 3.
        background_context: Optional knowledge-graph background text.
        meta_review: Meta-review synthesis from the previous iteration
            (audit E7); focuses the gap analysis on what the critique
            flags as missing or weak. Renders nothing on iteration 1.

    Returns:
        Formatted prompt string.
    """
    background_context_section = (
        "\n## Mechanistic Background (Knowledge Graph)\n\n"
        "The following structured evidence was retrieved from external"
        " knowledge sources "
        "to supplement the literature. Use it to ground the synthesis"
        " in known causal "
        "relationships and flag where hypotheses can leverage or"
        " contradict this background.\n\n" + background_context
        if background_context
        else ""
    )

    return load_prompt(
        "literature_review_synthesis",
        {
            "research_goal": research_goal,
            "paper_analyses": _format_paper_analyses(paper_analyses),
            "background_context_section": background_context_section,
            "meta_review_context": _format_meta_review_context(meta_review),
        },
    )


# Renders prompts/hypothesis_novelty_analysis.md, called by
# agents/generation/literature_tools/validate.py once per (draft hypothesis,
# paper) pair (paired there with HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA).
def get_hypothesis_novelty_analysis_prompt(
    hypothesis_text: str,
    title: str,
    authors: list[str],
    year: int | None,
    fulltext: str,
) -> str:
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


def _format_novelty_paper_analysis(
    j: int, analysis_data: dict[str, Any]
) -> str:
    """Format one paper's novelty analysis within a draft hypothesis section.

    Args:
        j: 1-based index of the paper within its hypothesis's analyses.
        analysis_data: A ``{paper_metadata, analysis}`` entry.

    Returns:
        The formatted paper-analysis block, prefixed with a leading newline.
    """
    paper_meta = analysis_data.get("paper_metadata", {})
    analysis = analysis_data.get("analysis", {})
    p_title = paper_meta.get("title", "Unknown")
    p_year = paper_meta.get("year", "N/A")

    return (
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
        f" {analysis.get('overlap_explanation', 'N/A')}\n"
    )


def _format_novelty_hypothesis_section(i: int, hyp_data: dict[str, Any]) -> str:
    """Format one draft hypothesis section.

    The section includes the hypothesis's per-paper novelty analyses.

    Args:
        i: 1-based index of the hypothesis.
        hyp_data: An entry with a ``draft`` dict and a ``novelty_analyses``
            list of ``{paper_metadata, analysis}``.

    Returns:
        The formatted section for this hypothesis.
    """
    draft = hyp_data.get("draft", {})
    analyses = hyp_data.get("novelty_analyses", [])

    hyp_section = f"""### draft hypothesis {i}
**text:** {draft.get("text", "Unknown")}
**gap reasoning:** {draft.get("gap_reasoning", "N/A")}
**literature sources:** {draft.get("literature_sources", "N/A")}

**novelty analyses ({len(analyses)} papers examined):**
"""

    for j, analysis_data in enumerate(analyses, 1):
        hyp_section += _format_novelty_paper_analysis(j, analysis_data)

    return hyp_section


def _format_hypotheses_with_novelty_analyses(
    hypotheses_with_analyses: list[dict[str, Any]],
) -> str:
    """Render draft hypotheses and their per-paper novelty analyses.

    Args:
        hypotheses_with_analyses: Draft hypotheses, each with a ``draft`` dict
            and a ``novelty_analyses`` list of ``{paper_metadata, analysis}``.

    Returns:
        The formatted block, sections joined by blank lines.
    """
    hypotheses_text = [
        _format_novelty_hypothesis_section(i, hyp_data)
        for i, hyp_data in enumerate(hypotheses_with_analyses, 1)
    ]
    return "\n\n".join(hypotheses_text)


def _build_already_validated_context(
    already_validated_texts: list[str] | None,
) -> str:
    """Build diversity constraint block for retry path.

    Injected only when retrying failed batches individually, so the model
    knows which hypothesis territory is already claimed and can pivot away.
    """
    if not already_validated_texts:
        return ""
    lines = "\n".join(f"- {t}" for t in already_validated_texts)
    return f"""
## Hypotheses Already Validated (Diversity Constraint)

The following hypotheses have already been validated and will be included in \
the final output.
Your output **must explore different mechanistic territory** from each of these.
If your draft overlaps significantly with any entry below, treat it as \
saturated and pivot:

{lines}

"""


def _resolve_validation_tool_instructions(tool_registry: Any | None) -> str:
    """Resolve tool instructions for the validation-synthesis workflow."""
    tool_ids = []
    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("validation")
    return build_tool_instructions(tool_ids, tool_registry)


@dataclass(frozen=True)
class ValidationSynthesisRequest:
    """Inputs for the Phase 2 validation-with-tools synthesis prompt.

    Attributes:
        research_goal: The research goal.
        hypotheses_with_analyses: Draft hypotheses with novelty analyses.
        articles: Article objects supplying citation metadata.
        articles_with_reasoning: Literature review synthesis text.
        max_iterations: Max tool iterations for the agent.
        tool_registry: ToolRegistry for dynamic tool instructions.
        reference_list: Citation reference list of `[C*]` keys.
        already_validated_texts: Hypothesis texts already validated (retry
            path only). Injected as a diversity constraint so the model
            avoids duplicate territory.
    """

    research_goal: str
    hypotheses_with_analyses: list[dict[str, Any]]
    articles: list[Any] | None = None
    articles_with_reasoning: str | None = None
    max_iterations: int = 8
    tool_registry: Any | None = None
    reference_list: str = ""
    already_validated_texts: list[str] | None = None


def _build_validation_synthesis_prompt_variables(
    req: ValidationSynthesisRequest,
) -> dict[str, Any]:
    """Build the Phase 2 validation-with-tools prompt template variables.

    Args:
        req: The resolved validation-synthesis request.

    Returns:
        Dict of template variables for the validation-synthesis prompt.
    """
    return {
        "research_goal": req.research_goal,
        "hypotheses_with_analyses": _format_hypotheses_with_novelty_analyses(
            req.hypotheses_with_analyses
        ),
        "hypotheses_count": len(req.hypotheses_with_analyses),
        "articles_metadata": format_articles_metadata(req.articles or []),
        "articles_with_reasoning": req.articles_with_reasoning
        or "no literature review summary available.",
        "citation_reference_section": _build_citation_reference_section(
            req.reference_list or ""
        ),
        "max_iterations": req.max_iterations,
        "tool_instructions": _resolve_validation_tool_instructions(
            req.tool_registry
        ),
        "already_validated_context": _build_already_validated_context(
            req.already_validated_texts
        ),
    }


# Renders prompts/hypothesis_validation_synthesis_with_tools.md for the
# Phase 2 validation agent in
# agents/generation/literature_tools/validate.py.
# tool_instructions is built from the "validation" workflow's tool list so
# the agent knows which MCP search tools it may call while pivoting.
def get_validation_synthesis_prompt_with_tools(
    req: ValidationSynthesisRequest,
) -> tuple[str, dict[str, Any] | None]:
    """Get prompt for validation synthesis with tool access.

    This version includes tool instructions so the LLM can search for
    additional papers when deciding to pivot hypotheses.

    Args:
        req: The resolved validation-synthesis request; its fields are
            documented on ValidationSynthesisRequest.

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    return _build_prompt(
        "hypothesis_validation_synthesis_with_tools",
        _build_validation_synthesis_prompt_variables(req),
        tool_registry=req.tool_registry,
    )

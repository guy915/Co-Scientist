"""Prompt builders for the literature-review node."""

from dataclasses import dataclass
from typing import Any

from co_scientist.prompts._common import (
    _format_authors,
    _format_bullet_list,
    _format_csv_list,
    _format_year,
)
from co_scientist.prompts.loading import load_prompt


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


def _format_query_generation_variables(
    research_goal: str, inputs: LiteratureQueryInputs
) -> dict[str, Any]:
    """Build the shared template variables for query-generation prompts.

    Identical across the PubMed-specific and source-aware query-generation
    getters below, so it is defined once here.

    Args:
        research_goal: The research goal the queries must explore.
        inputs: The user-supplied run inputs steering query generation.

    Returns:
        Dict of template variables for a query-generation prompt.
    """
    return {
        "research_goal": research_goal,
        "preferences": inputs.preferences or "None provided",
        "attributes": _format_csv_list(inputs.attributes),
        "user_literature": _format_bullet_list(inputs.user_literature),
        "user_hypotheses": _format_bullet_list(inputs.user_hypotheses),
    }


# PubMed-specific variant kept for backwards compatibility; production code
# goes through the source-aware getter below, which dispatches to the same
# template when source_type is "pubmed".
def get_literature_review_query_generation_pubmed_prompt(
    research_goal: str, inputs: LiteratureQueryInputs | None = None
) -> str:
    """Get the PubMed query generation prompt.

    Args:
        research_goal: The research goal the queries must explore.
        inputs: The user-supplied run inputs steering query generation.

    Returns:
        Formatted prompt string.
    """
    return load_prompt(
        "literature_review_query_generation_pubmed",
        _format_query_generation_variables(
            research_goal, inputs or LiteratureQueryInputs()
        ),
    )


def _select_query_generation_template(source_type: str) -> str:
    """Select the query-generation template name for a literature source type.

    - knowledge_graph (INDRA): Extract gene/protein names
    - academic (PubMed, arXiv, Scholar): Natural language queries
    - pubmed: PubMed-specific (backwards compat)
    """
    if source_type == "knowledge_graph":
        return "literature_review_query_generation_indra"
    if source_type == "pubmed":
        return "literature_review_query_generation_pubmed"
    # Generic fallback for other academic sources
    return "literature_review_query_generation_generic"


# Query-generation entry point used by
# agents/generation/literature_review/queries.py, paired
# there with LITERATURE_QUERY_SCHEMA. Returns a bare string (no schema in
# the tuple) because the schema is imported directly by the caller.
def get_literature_review_query_generation_prompt(
    research_goal: str,
    source_type: str = "academic",
    inputs: LiteratureQueryInputs | None = None,
) -> str:
    """Get source-aware query generation prompt.

    Selects the appropriate prompt template based on source type; see
    _select_query_generation_template for the mapping.

    Args:
        research_goal: The research goal
        source_type: Type of literature source (from ToolConfig.source_type)
        inputs: The user-supplied run inputs steering query generation.

    Returns:
        Formatted prompt string
    """
    template_name = _select_query_generation_template(source_type)
    return load_prompt(
        template_name,
        _format_query_generation_variables(
            research_goal, inputs or LiteratureQueryInputs()
        ),
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
) -> str:
    """Get the prompt for synthesizing paper analyses."""
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
        },
    )

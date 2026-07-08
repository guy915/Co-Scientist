"""Prompt builders for the literature-review node."""
# pylint: disable=inconsistent-quotes

from typing import Any

from co_scientist.prompts._common import _format_authors
from co_scientist.prompts._common import _format_year
from co_scientist.prompts.loading import load_prompt


# PubMed-specific variant kept for backwards compatibility; production code
# goes through the source-aware getter below, which dispatches to the same
# template when source_type is "pubmed".
def get_literature_review_query_generation_pubmed_prompt(
    research_goal: str,
    preferences: str | None = None,
    attributes: list[str] | None = None,
    user_literature: list[str] | None = None,
    user_hypotheses: list[str] | None = None,
) -> str:
    """Get the PubMed query generation prompt."""
    return load_prompt(
        "literature_review_query_generation_pubmed",
        {
            "research_goal":
                research_goal,
            "preferences":
                preferences if preferences else "None provided",
            "attributes":
                ", ".join(attributes) if attributes else "None provided",
            "user_literature": ("\n".join(f"- {lit}" for lit in user_literature)
                                if user_literature else "None provided"),
            "user_hypotheses": ("\n".join(f"- {hyp}" for hyp in user_hypotheses)
                                if user_hypotheses else "None provided"),
        },
    )


# Query-generation entry point used by nodes/literature_review.py, paired
# there with LITERATURE_QUERY_SCHEMA. Returns a bare string (no schema in
# the tuple) because the schema is imported directly by the caller.
def get_literature_review_query_generation_prompt(
    research_goal: str,
    source_type: str = "academic",
    preferences: str | None = None,
    attributes: list[str] | None = None,
    user_literature: list[str] | None = None,
    user_hypotheses: list[str] | None = None,
) -> str:
    """Get source-aware query generation prompt.

    Selects the appropriate prompt template based on source type:
    - knowledge_graph (INDRA): Extract gene/protein names
    - academic (PubMed, arXiv, Scholar): Natural language queries
    - pubmed: PubMed-specific (backwards compat)

    Args:
        research_goal: The research goal
        source_type: Type of literature source (from ToolConfig.source_type)
        preferences: Optional user preferences
        attributes: Optional user attributes
        user_literature: Optional user-provided literature
        user_hypotheses: Optional user-provided hypotheses

    Returns:
        Formatted prompt string
    """
    # Select template based on source type
    if source_type == "knowledge_graph":
        template_name = "literature_review_query_generation_indra"
    elif source_type == "pubmed":
        template_name = "literature_review_query_generation_pubmed"
    else:
        # Generic fallback for other academic sources
        template_name = "literature_review_query_generation_generic"

    return load_prompt(
        template_name,
        {
            "research_goal":
                research_goal,
            "preferences":
                preferences if preferences else "None provided",
            "attributes":
                ", ".join(attributes) if attributes else "None provided",
            "user_literature": ("\n".join(f"- {lit}" for lit in user_literature)
                                if user_literature else "None provided"),
            "user_hypotheses": ("\n".join(f"- {hyp}" for hyp in user_hypotheses)
                                if user_hypotheses else "None provided"),
        },
    )


# Renders prompts/literature_review_paper_analysis.md, called by
# nodes/literature_review.py once per fetched paper (paired there with
# LITERATURE_PAPER_ANALYSIS_SCHEMA).
def get_literature_review_paper_analysis_prompt(research_goal: str, title: str,
                                                authors: list[str],
                                                year: int | None,
                                                fulltext: str) -> str:
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


# Renders prompts/literature_review_synthesis.md for
# nodes/literature_review.py: flattens the per-paper analyses into one
# markdown block and optionally appends knowledge-graph background as a
# "Mechanistic Background" section (empty string when unavailable).
def get_literature_review_synthesis_prompt(
    research_goal: str,
    paper_analyses: list[dict[str, Any]],
    background_context: str = "",
) -> str:
    """Get the prompt for synthesizing paper analyses."""
    # Format paper analyses as structured text
    analyses_text = []
    for i, analysis_data in enumerate(paper_analyses, 1):
        metadata = analysis_data.get("metadata", {})
        analysis = analysis_data.get("analysis", {})

        paper_section = f"""### paper {i}: {metadata.get('title', 'Unknown')}
**authors:** {', '.join(metadata.get('authors', ['Unknown']))}
**year:** {metadata.get('year', 'Unknown')}

**key findings:** {analysis.get('key_findings', 'N/A')}

**gaps identified:** {analysis.get('gaps_identified', 'N/A')}

**future work suggested:** {analysis.get('future_work', 'N/A')}

**methodology limitations:** {analysis.get('methodology_limitations', 'N/A')}

**unexplored areas:** {analysis.get('unexplored_areas', 'N/A')}

**relevance:** {analysis.get('relevance', 'N/A')}
"""
        analyses_text.append(paper_section)

    background_context_section = (
        "\n## Mechanistic Background (Knowledge Graph)\n\n"
        "The following structured evidence was retrieved from external"
        " knowledge sources "
        "to supplement the literature. Use it to ground the synthesis"
        " in known causal "
        "relationships and flag where hypotheses can leverage or"
        " contradict this background.\n\n" +
        background_context if background_context else "")

    return load_prompt(
        "literature_review_synthesis",
        {
            "research_goal": research_goal,
            "paper_analyses": "\n\n".join(analyses_text),
            "background_context_section": background_context_section,
        },
    )

"""JSON schemas for the literature-review stage.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during literature search-query generation and
per-paper analysis.
"""

from typing import Any

# Literature review query generation schema
# Imported directly (not via get_schema_for_prompt) by
# nodes/literature_review.py, which pairs it with whichever of the three
# query-generation prompt templates
# (literature_review_query_generation_pubmed/_indra/_generic) source-type
# detection selects; the schema itself is source-agnostic, it just wants a
# flat list of search-query strings.
LITERATURE_QUERY_SCHEMA: dict[str, Any] = {
    "name": "pubmed_query_generation",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "description": ("Natural language search queries for PubMed"
                                " literature search"),
                "items": {
                    "type":
                        "string",
                    "description":
                        ("A focused search phrase covering a specific"
                         " aspect of the research goal"),
                },
            }
        },
        "required": ["queries"],
        "additionalProperties": False,
    },
}
# Literature review paper analysis schema
# Imported directly (not via get_schema_for_prompt) by
# nodes/literature_review.py to structure the per-paper analysis produced
# for each fetched article (used later when synthesizing the literature
# review and, via get_literature_review_synthesis_prompt, when assembling
# the "Papers Analyzed" section of downstream generation prompts).
LITERATURE_PAPER_ANALYSIS_SCHEMA: dict[str, Any] = {
    "name": "paper_analysis",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "key_findings": {
                "type": "string",
                "description": "main contributions and results from this work",
            },
            "gaps_identified": {
                "type":
                    "string",
                "description":
                    "limitations or gaps explicitly mentioned by authors",
            },
            "future_work": {
                "type": "string",
                "description": "future research suggested by the authors",
            },
            "methodology_limitations": {
                "type": "string",
                "description": "constraints or limitations in their methods",
            },
            "unexplored_areas": {
                "type": "string",
                "description": "topics mentioned but not investigated",
            },
            "relevance": {
                "type": "string",
                "description": "how this paper relates to the research goal",
            },
        },
        "required": [
            "key_findings",
            "gaps_identified",
            "future_work",
            "methodology_limitations",
            "unexplored_areas",
            "relevance",
        ],
        "additionalProperties": False,
    },
}

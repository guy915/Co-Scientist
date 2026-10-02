"""JSON schemas for the literature-review stage.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during literature search-query generation and
per-paper analysis.
"""

from typing import Any

from co_scientist.schemas.builders import obj

# Literature review query generation schema
# Imported directly (not via get_schema_for_prompt) by
# agents/generation/literature_review/queries.py, which pairs it with
# whichever of the three
# query-generation prompt templates
# (literature_review_query_generation_pubmed/_indra/_generic) source-type
# detection selects; the schema itself is source-agnostic, it just wants a
# flat list of search-query strings.
LITERATURE_QUERY_SCHEMA: dict[str, Any] = {
    "name": "pubmed_query_generation",
    "strict": False,
    "schema": obj(
        {
            "queries": {
                "type": "array",
                "description": (
                    "Natural language search queries for PubMed"
                    " literature search"
                ),
                "items": {
                    "type": "string",
                    "description": (
                        "A focused search phrase covering a specific"
                        " aspect of the research goal"
                    ),
                },
            }
        }
    ),
}
# Literature review paper analysis schema
# Imported directly (not via get_schema_for_prompt) by
# agents/generation/literature_review/analysis.py to structure the
# per-paper analysis produced
# for each fetched article (used later when synthesizing the literature
# review and, via get_literature_review_synthesis_prompt, when assembling
# the "Papers Analyzed" section of downstream generation prompts).
LITERATURE_PAPER_ANALYSIS_SCHEMA: dict[str, Any] = {
    "name": "paper_analysis",
    "strict": False,
    "schema": obj(
        {
            "key_findings": {
                "type": "string",
                "description": "main contributions and results from this work",
            },
            "gaps_identified": {
                "type": "string",
                "description": (
                    "limitations or gaps explicitly mentioned by authors"
                ),
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
        }
    ),
}

# Literature review semantic relevance schema (batched)
# Imported directly by
# evidence/relevance.py, the model-judged half
# of the hybrid retrieval scorer (fidelity-audit G5): one call judges a
# whole batch of candidates at once (see the module docstring in
# relevance.py for the per-candidate-call incident this replaced), so
# each judgment names the candidate it belongs to by the positional
# index the prompt assigned it -- never by echoing the candidate's title
# or abstract back, which would scale output with the batch size (the
# structured-output pitfall AGENTS.md records).
LITERATURE_RELEVANCE_BATCH_SCHEMA: dict[str, Any] = {
    "name": "literature_relevance_batch",
    "strict": False,
    "schema": obj(
        {
            "judgments": {
                "type": "array",
                "description": "One judgment per candidate in the batch.",
                "items": obj(
                    {
                        "index": {
                            "type": "integer",
                            "description": (
                                "The number assigned to the candidate in"
                                " the prompt: 1 for Candidate 1, 2 for"
                                " Candidate 2, and so on"
                            ),
                        },
                        "relevance": {
                            "type": "number",
                            "description": (
                                "how well this candidate's title and"
                                " abstract bear on the research goal,"
                                " from 0.0 (unrelated) to 1.0 (directly"
                                " on point)"
                            ),
                        },
                        "rationale": {
                            "type": "string",
                            "description": (
                                "one sentence stating why this candidate"
                                " does or does not bear on the research"
                                " goal"
                            ),
                        },
                    }
                ),
            }
        }
    ),
}

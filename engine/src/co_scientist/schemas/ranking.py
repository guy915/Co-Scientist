"""JSON schemas for the ranking and proximity stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during pairwise tournament ranking and
proximity-based similarity clustering.
"""

from typing import Any

# Ranking schema
# Shapes the "ranking" prompt output, consumed by the pairwise tournament
# comparison in nodes/ranking.py. "winner" drives the Elo update
# (calculate_elo_update) for the pair; judgment_explanation breaks the
# comparison down per criterion (mirroring the review criteria, plus
# feasibility) but is not itself parsed by ranking logic beyond
# display/logging.
RANKING_SCHEMA: dict[str, Any] = {
    "name": "ranking_judgment",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "research_goal": {"type": "string"},
            "hypothesis_a": {"type": "string"},
            "hypothesis_b": {"type": "string"},
            "winner": {
                "type": "string",
                "enum": ["a", "b"],
                "description": "The winning hypothesis (a or b)",
            },
            "judgment_explanation": {
                "type": "object",
                "properties": {
                    "scientific_soundness_comparison": {"type": "string"},
                    "novelty_comparison": {"type": "string"},
                    "relevance_comparison": {"type": "string"},
                    "testability_comparison": {"type": "string"},
                    "clarity_comparison": {"type": "string"},
                    "impact_comparison": {"type": "string"},
                    "feasibility_comparison": {"type": "string"},
                },
                "required": [
                    "scientific_soundness_comparison",
                    "novelty_comparison",
                    "relevance_comparison",
                    "testability_comparison",
                    "clarity_comparison",
                    "impact_comparison",
                    "feasibility_comparison",
                ],
                "additionalProperties": False,
            },
            "decision_summary": {"type": "string"},
            "confidence_level": {
                "type": "string",
                "enum": ["High", "Medium", "Low"],
            },
        },
        "required": [
            "research_goal",
            "hypothesis_a",
            "hypothesis_b",
            "winner",
            "judgment_explanation",
            "decision_summary",
            "confidence_level",
        ],
        "additionalProperties": False,
    },
}
# Proximity schema
# Shapes the "proximity" prompt output, consumed by nodes/proximity.py to
# cluster near-duplicate hypotheses before deduplication.
# nodes/proximity.py matches each similar_hypotheses entry back to a
# Hypothesis object by comparing the first 100 characters of "text" (not by
# array position or an id), then groups hypotheses by cluster_id and keeps
# only the strongest of each "high" similarity_degree group.
PROXIMITY_SCHEMA: dict[str, Any] = {
    "name": "proximity_analysis",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "similarity_clusters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cluster_id": {"type": "string"},
                        "cluster_name": {"type": "string"},
                        "central_theme": {"type": "string"},
                        # Members are identified by the index the prompt
                        # assigns, not by echoing their text back: the echo
                        # scaled the response with the pool and overran the
                        # output budget on a large run, truncating the JSON
                        # and costing five identical retries before
                        # deduplication was skipped entirely.
                        "similar_hypotheses": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "index": {"type": "integer"},
                                    "similarity_degree": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                    },
                                },
                                "required": ["index", "similarity_degree"],
                                "additionalProperties": False,
                            },
                        },
                        "synthesis_potential": {"type": "string"},
                    },
                    "required": [
                        "cluster_id",
                        "cluster_name",
                        "central_theme",
                        "similar_hypotheses",
                        "synthesis_potential",
                    ],
                    "additionalProperties": False,
                },
            },
            "diversity_assessment": {"type": "string"},
            "redundancy_assessment": {"type": "string"},
        },
        "required": [
            "similarity_clusters",
            "diversity_assessment",
            "redundancy_assessment",
        ],
        "additionalProperties": False,
    },
}

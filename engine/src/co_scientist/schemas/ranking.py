"""JSON schemas for the ranking and proximity stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during pairwise tournament ranking and
proximity-based similarity clustering.
"""

from typing import Any

from co_scientist.schemas.builders import obj

# Ranking schema
# Shapes the "ranking" prompt output, consumed by the pairwise tournament
# comparison in agents/ranking/ranking.py. "winner" drives the Elo update
# (calculate_elo_update) for the pair; judgment_explanation breaks the
# comparison down per criterion (mirroring the review criteria, plus
# feasibility) but is not itself parsed by ranking logic beyond
# display/logging.
RANKING_SCHEMA: dict[str, Any] = {
    "name": "ranking_judgment",
    "strict": False,
    "schema": obj(
        {
            "research_goal": {"type": "string"},
            "hypothesis_a": {"type": "string"},
            "hypothesis_b": {"type": "string"},
            "winner": {
                "type": "string",
                "enum": ["a", "b"],
                "description": "The winning hypothesis (a or b)",
            },
            "judgment_explanation": obj(
                {
                    "scientific_soundness_comparison": {"type": "string"},
                    "novelty_comparison": {"type": "string"},
                    "relevance_comparison": {"type": "string"},
                    "testability_comparison": {"type": "string"},
                    "clarity_comparison": {"type": "string"},
                    "impact_comparison": {"type": "string"},
                    "feasibility_comparison": {"type": "string"},
                }
            ),
            "decision_summary": {"type": "string"},
            "confidence_level": {
                "type": "string",
                "enum": ["High", "Medium", "Low"],
            },
        }
    ),
}
# Proximity schema
# Shapes the "proximity" prompt output, consumed by
# agents/proximity/proximity.py to cluster near-duplicate hypotheses
# before deduplication. Each similar_hypotheses entry names its
# hypothesis by the "index" the prompt assigned it, which is how both
# deduplication (proximity_dedup._match_cluster_member) and the
# persisted proximity graph (proximity_graph._resolve_member_id)
# resolve a member; comparing the first 100 characters of an echoed
# "text" is only their shared fallback, since this schema forbids
# that key. Members are then grouped by cluster_id, keeping only the
# strongest of each "high" similarity_degree group.
PROXIMITY_SCHEMA: dict[str, Any] = {
    "name": "proximity_analysis",
    "strict": False,
    "schema": obj(
        {
            "similarity_clusters": {
                "type": "array",
                "items": obj(
                    {
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
                            "items": obj(
                                {
                                    "index": {"type": "integer"},
                                    "similarity_degree": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                    },
                                }
                            ),
                        },
                        "synthesis_potential": {"type": "string"},
                    }
                ),
            },
            "diversity_assessment": {"type": "string"},
            "redundancy_assessment": {"type": "string"},
        }
    ),
}

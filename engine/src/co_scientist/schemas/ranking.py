"""JSON schemas for the ranking and proximity stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during pairwise tournament ranking and
proximity-based similarity clustering.
"""

from typing import Any

from co_scientist.schemas.builders import obj

# The five evaluation aspects published ranking-05 tells the panel to
# consider, in the published order: "Potential for correctness/validity",
# "Utility and practical applicability", "Sufficiency of detail and
# specificity", "Novelty and originality", "Desirability for
# implementation". They replace seven clone-invented criteria that had no
# published source. One source for the schema's judgment_explanation
# keys, the aspect-to-key mapping both ranking templates print
# (prompts/templates/ranking_pairwise.md, ranking_debate.md), and the
# parse that collects the assessments onto the match record
# (agents/ranking/ranking_results.py, audit E17).
RANKING_COMPARISON_CRITERIA: tuple[str, ...] = (
    "correctness_comparison",
    "utility_comparison",
    "detail_comparison",
    "novelty_comparison",
    "desirability_comparison",
)

# Ranking schema
# Shapes both ranking prompts' output (ranking_pairwise = published A.4,
# ranking_debate = published A.5), consumed by the pairwise tournament
# comparison in agents/ranking/ranking.py. "winner" drives the Elo update
# (calculate_elo_update) for the pair; judgment_explanation breaks the
# comparison down per published evaluation aspect and is collected onto
# the persisted match record by
# ranking_results._extract_criteria_comparisons. The judge's concluding
# "better idea: <1 or 2>" line in decision_summary is the primary verdict
# (the paper's termination token); "winner" is the machine fallback when
# the line is absent (ranking_debate_turns._parse_matchup_winner).
#
# Echo-free: this schema used to require the model to repeat the research
# goal and both hypothesis texts back, which nothing read and which made
# the reply grow with the pool's text -- the failure mode the root
# CLAUDE.md records for proximity.
RANKING_SCHEMA: dict[str, Any] = {
    "name": "ranking_judgment",
    "strict": False,
    "schema": obj(
        {
            "winner": {
                "type": "string",
                "enum": ["a", "b"],
                "description": "The winning hypothesis (a or b)",
            },
            "judgment_explanation": obj(
                {
                    name: {"type": "string"}
                    for name in RANKING_COMPARISON_CRITERIA
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

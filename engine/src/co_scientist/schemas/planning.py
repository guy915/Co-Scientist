"""JSON schemas for the supervisor-planning and meta-review stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during supervisor workflow planning and
cross-hypothesis meta-review synthesis.
"""

from typing import Any

# Supervisor schema
# Shapes the "supervisor" prompt output, consumed by
# agents/supervisor/supervisor.py at the start (and, for
# iterative runs, between rounds) of a run. This is the
# largest/most structured schema in the file because the supervisor is a
# single planning call whose output threads through nearly every later
# node: research_goal_analysis and workflow_plan feed the various
# "supervisor guidance" formatting helpers in prompts.py
# (_format_supervisor_guidance_for_review/_ranking/_proximity/
# _meta_review, format_supervisor_guidance_for_generation), while
# config_synthesis is the normalized run configuration (preferences,
# review_instructions, attributes) that both generation and review draw on.
SUPERVISOR_SCHEMA: dict[str, Any] = {
    "name": "supervisor_guidance",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            # Restates and decomposes the research goal; key_areas feeds
            # the "Key Research Areas" guidance blocks used by ranking,
            # proximity, and meta-review prompts.
            "research_goal_analysis": {
                "type": "object",
                "properties": {
                    "goal_summary": {
                        "type": "string",
                        "description": (
                            "concise restatement of the research goal"
                        ),
                    },
                    "key_areas": {"type": "array", "items": {"type": "string"}},
                    "constraints_identified": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "success_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "goal_summary",
                    "key_areas",
                    "constraints_identified",
                    "success_criteria",
                ],
                "additionalProperties": False,
            },
            # Per-phase strategic guidance (generation/review/evolution).
            # generation_phase.focus_areas is read inline by
            # get_debate_generation_prompt; review_phase and
            # evolution_phase are read by _format_supervisor_guidance_for_
            # review/_meta_review in prompts.py.
            "workflow_plan": {
                "type": "object",
                "properties": {
                    "generation_phase": {
                        "type": "object",
                        "properties": {
                            "focus_areas": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "diversity_targets": {
                                "type": "string",
                                "description": (
                                    "description of diversity targets"
                                    " for hypotheses"
                                ),
                            },
                            "quantity_target": {
                                "type": "string",
                                "description": "target number of hypotheses",
                            },
                        },
                        "required": [
                            "focus_areas",
                            "diversity_targets",
                            "quantity_target",
                        ],
                        "additionalProperties": False,
                    },
                    "review_phase": {
                        "type": "object",
                        "properties": {
                            "critical_criteria": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "review_depth": {
                                "type": "string",
                                "description": "depth of review required",
                            },
                        },
                        "required": ["critical_criteria", "review_depth"],
                        "additionalProperties": False,
                    },
                    "evolution_phase": {
                        "type": "object",
                        "properties": {
                            "refinement_priorities": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "iteration_strategy": {
                                "type": "string",
                                "description": (
                                    "description of iteration strategy"
                                ),
                            },
                        },
                        "required": [
                            "refinement_priorities",
                            "iteration_strategy",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "generation_phase",
                    "review_phase",
                    "evolution_phase",
                ],
                "additionalProperties": False,
            },
            # Read by _format_supervisor_guidance_for_review in prompts.py.
            # Despite the "used by BOTH generation and review" language in
            # the preferences description below, only the review prompt
            # path currently reads config_synthesis back out.
            "config_synthesis": {
                "type": "object",
                "description": (
                    "Normalized run configuration synthesized from the goal,"
                    " mirroring the reference product's Config. Keep the three"
                    " lists strictly separate."
                ),
                "properties": {
                    "preferences": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Hard scope constraints plus the soft 'what makes"
                            " a good idea' qualities. Used by BOTH generation"
                            " and review."
                        ),
                    },
                    "review_instructions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Comparative critique guidance for reviewers"
                            " ONLY: how to validate soundness and tell strong"
                            " ideas from weak ones. Do NOT restate the"
                            " preferences here."
                        ),
                    },
                    "attributes": {
                        "type": "array",
                        "description": (
                            "Up to 3 axes used to stratify and compare ideas,"
                            " each with a 1-5 scoring rubric."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "short attribute name",
                                },
                                "rubric": {
                                    "type": "string",
                                    "description": (
                                        "how to score this attribute from 1"
                                        " (worst) to 5 (best)"
                                    ),
                                },
                            },
                            "required": ["name", "rubric"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "preferences",
                    "review_instructions",
                    "attributes",
                ],
                "additionalProperties": False,
            },
            # performance_assessment, adjustment_recommendations, and
            # output_preparation below are stored on workflow state
            # (agents/supervisor/supervisor.py) for observability/debugging
            # but are not currently re-read by any prompt-formatting helper.
            "performance_assessment": {
                "type": "object",
                "properties": {
                    "current_status": {
                        "type": "string",
                        "description": "assessment of current workflow status",
                    },
                    "bottlenecks_identified": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "agent_performance": {
                        "type": "object",
                        "properties": {
                            "generation_agent": {
                                "type": "string",
                                "description": (
                                    "assessment of generation agent performance"
                                ),
                            },
                            "reflection_agent": {
                                "type": "string",
                                "description": (
                                    "assessment of reflection agent performance"
                                ),
                            },
                            "ranking_agent": {
                                "type": "string",
                                "description": (
                                    "assessment of ranking agent performance"
                                ),
                            },
                            "evolution_agent": {
                                "type": "string",
                                "description": (
                                    "assessment of evolution agent performance"
                                ),
                            },
                            "proximity_agent": {
                                "type": "string",
                                "description": (
                                    "assessment of proximity agent performance"
                                ),
                            },
                            "meta_review_agent": {
                                "type": "string",
                                "description": (
                                    "assessment of meta-review agent"
                                    " performance"
                                ),
                            },
                        },
                        "required": [
                            "generation_agent",
                            "reflection_agent",
                            "ranking_agent",
                            "evolution_agent",
                            "proximity_agent",
                            "meta_review_agent",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "current_status",
                    "bottlenecks_identified",
                    "agent_performance",
                ],
                "additionalProperties": False,
            },
            "adjustment_recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "aspect": {
                            "type": "string",
                            "description": "aspect to adjust",
                        },
                        "adjustment": {
                            "type": "string",
                            "description": "description of adjustment",
                        },
                        "justification": {
                            "type": "string",
                            "description": "reasoning behind this adjustment",
                        },
                    },
                    "required": ["aspect", "adjustment", "justification"],
                    "additionalProperties": False,
                },
            },
            "output_preparation": {
                "type": "object",
                "properties": {
                    "hypothesis_selection_strategy": {
                        "type": "string",
                        "description": (
                            "strategy for selecting final hypotheses"
                        ),
                    },
                    "presentation_format": {
                        "type": "string",
                        "description": (
                            "format for presenting results to scientist"
                        ),
                    },
                    "key_insights_to_highlight": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "hypothesis_selection_strategy",
                    "presentation_format",
                    "key_insights_to_highlight",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "research_goal_analysis",
            "workflow_plan",
            "config_synthesis",
            "performance_assessment",
            "adjustment_recommendations",
            "output_preparation",
        ],
        "additionalProperties": False,
    },
}
# Meta-review schema
# Shapes the "meta_review" prompt output, consumed by
# agents/meta_review/meta_review.py after a full review pass across
# all hypotheses.
# Synthesizes cross-hypothesis patterns (recurring_themes, strengths,
# weaknesses), assesses each pipeline stage (process_assessment), and
# proposes both concrete next-iteration guidance
# (strategic_recommendations) and cross-hypothesis synthesis opportunities
# (potential_connections). Downstream nodes re-inject this output as
# guidance text for later prompts via _format_meta_review_context() in
# prompts.py (review, ranking, reflection, research-overview, and debate
# generation prompts all accept it).
META_REVIEW_SCHEMA: dict[str, Any] = {
    "name": "meta_review",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "meta_review_summary": {
                "type": "string",
                "description": "Overall summary of meta-review analysis",
            },
            "recurring_themes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "theme": {"type": "string"},
                        "description": {"type": "string"},
                        "frequency": {"type": "string"},
                    },
                    "required": ["theme", "description", "frequency"],
                    "additionalProperties": False,
                },
            },
            "strengths": {"type": "array", "items": {"type": "string"}},
            "weaknesses": {"type": "array", "items": {"type": "string"}},
            "process_assessment": {
                "type": "object",
                "properties": {
                    "generation_process": {"type": "string"},
                    "review_process": {"type": "string"},
                    "evolution_process": {"type": "string"},
                },
                "required": [
                    "generation_process",
                    "review_process",
                    "evolution_process",
                ],
                "additionalProperties": False,
            },
            "strategic_recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "focus_area": {"type": "string"},
                        "recommendation": {"type": "string"},
                        "justification": {"type": "string"},
                    },
                    "required": [
                        "focus_area",
                        "recommendation",
                        "justification",
                    ],
                    "additionalProperties": False,
                },
            },
            "potential_connections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "related_hypotheses": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "connection_type": {"type": "string"},
                        "synthesis_opportunity": {"type": "string"},
                    },
                    "required": [
                        "related_hypotheses",
                        "connection_type",
                        "synthesis_opportunity",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "meta_review_summary",
            "recurring_themes",
            "strengths",
            "weaknesses",
            "process_assessment",
            "strategic_recommendations",
            "potential_connections",
        ],
        "additionalProperties": False,
    },
}

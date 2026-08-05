"""JSON schemas for the supervisor-planning and meta-review stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during supervisor workflow planning and
cross-hypothesis meta-review synthesis.
"""

from typing import Any

from co_scientist.schemas.builders import obj, str_array

# The six agents the supervisor grades, each as a free-text assessment.
_AGENTS_ASSESSED: tuple[str, ...] = (
    "generation",
    "reflection",
    "ranking",
    "evolution",
    "proximity",
    "meta_review",
)

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
    "schema": obj(
        {
            # Restates and decomposes the research goal; key_areas feeds
            # the "Key Research Areas" guidance blocks used by ranking,
            # proximity, and meta-review prompts.
            "research_goal_analysis": obj(
                {
                    "goal_summary": {
                        "type": "string",
                        "description": (
                            "concise restatement of the research goal"
                        ),
                    },
                    "key_areas": str_array(),
                    "constraints_identified": str_array(),
                    "success_criteria": str_array(),
                }
            ),
            # Per-phase strategic guidance (generation/review/evolution).
            # generation_phase.focus_areas is read inline by
            # get_debate_generation_prompt; review_phase and
            # evolution_phase are read by _format_supervisor_guidance_for_
            # review/_meta_review in prompts.py.
            "workflow_plan": obj(
                {
                    "generation_phase": obj(
                        {
                            "focus_areas": str_array(),
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
                        }
                    ),
                    "review_phase": obj(
                        {
                            "critical_criteria": str_array(),
                            "review_depth": {
                                "type": "string",
                                "description": "depth of review required",
                            },
                        }
                    ),
                    "evolution_phase": obj(
                        {
                            "refinement_priorities": str_array(),
                            "iteration_strategy": {
                                "type": "string",
                                "description": (
                                    "description of iteration strategy"
                                ),
                            },
                        }
                    ),
                }
            ),
            # Read by _format_supervisor_guidance_for_review in prompts.py.
            # Despite the "used by BOTH generation and review" language in
            # the preferences description below, only the review prompt
            # path currently reads config_synthesis back out.
            "config_synthesis": {
                **obj(
                    {
                        "preferences": str_array(
                            "Hard scope constraints plus the soft 'what makes"
                            " a good idea' qualities. Used by BOTH generation"
                            " and review."
                        ),
                        "review_instructions": str_array(
                            "Comparative critique guidance for reviewers"
                            " ONLY: how to validate soundness and tell strong"
                            " ideas from weak ones. Do NOT restate the"
                            " preferences here."
                        ),
                        "attributes": {
                            "type": "array",
                            "description": (
                                "Up to 3 axes used to stratify and compare"
                                " ideas, each with a 1-5 scoring rubric."
                            ),
                            "items": obj(
                                {
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
                                }
                            ),
                        },
                    }
                ),
                "description": (
                    "Normalized run configuration synthesized from the goal,"
                    " mirroring the reference product's Config. Keep the three"
                    " lists strictly separate."
                ),
            },
            # performance_assessment, adjustment_recommendations, and
            # output_preparation below are stored on workflow state
            # (agents/supervisor/supervisor.py) for observability/debugging
            # but are not currently re-read by any prompt-formatting helper.
            "performance_assessment": obj(
                {
                    "current_status": {
                        "type": "string",
                        "description": "assessment of current workflow status",
                    },
                    "bottlenecks_identified": str_array(),
                    "agent_performance": obj(
                        {
                            f"{agent}_agent": {
                                "type": "string",
                                "description": (
                                    f"assessment of {agent.replace('_', '-')}"
                                    " agent performance"
                                ),
                            }
                            for agent in _AGENTS_ASSESSED
                        }
                    ),
                }
            ),
            "adjustment_recommendations": {
                "type": "array",
                "items": obj(
                    {
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
                    }
                ),
            },
            "output_preparation": obj(
                {
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
                    "key_insights_to_highlight": str_array(),
                }
            ),
        }
    ),
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
    "schema": obj(
        {
            "meta_review_summary": {
                "type": "string",
                "description": "Overall summary of meta-review analysis",
            },
            "recurring_themes": {
                "type": "array",
                "items": obj(
                    {
                        "theme": {"type": "string"},
                        "description": {"type": "string"},
                        "frequency": {"type": "string"},
                    }
                ),
            },
            "strengths": str_array(),
            "weaknesses": str_array(),
            "process_assessment": obj(
                {
                    "generation_process": {"type": "string"},
                    "review_process": {"type": "string"},
                    "evolution_process": {"type": "string"},
                }
            ),
            "strategic_recommendations": {
                "type": "array",
                "items": obj(
                    {
                        "focus_area": {"type": "string"},
                        "recommendation": {"type": "string"},
                        "justification": {"type": "string"},
                    }
                ),
            },
            "potential_connections": {
                "type": "array",
                "items": obj(
                    {
                        "related_hypotheses": str_array(),
                        "connection_type": {"type": "string"},
                        "synthesis_opportunity": {"type": "string"},
                    }
                ),
            },
        }
    ),
}

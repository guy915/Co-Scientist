"""JSON schemas for the supervisor-planning and meta-review stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during supervisor workflow planning and
cross-hypothesis meta-review synthesis.
"""

from typing import Any, Final

from co_scientist.schemas.builders import obj, str_array

# Re-exported so `from co_scientist.schemas.planning import
# META_REVIEW_SCHEMA` keeps resolving after the split into
# meta_review_schema.py (the file had grown past the 500-line cap).
from co_scientist.schemas.meta_review_schema import (
    META_REVIEW_SCHEMA as META_REVIEW_SCHEMA,
)

# The six agents the supervisor grades, each as a free-text assessment.
_AGENTS_ASSESSED: tuple[str, ...] = (
    "generation",
    "reflection",
    "ranking",
    "evolution",
    "proximity",
    "meta_review",
)

# Bounds on workflow_plan.review_phase.critical_criteria below (R12-23,
# R12-23b). Two different published sections name these criteria, and
# they disagree on the count -- read both before touching either bound.
# The "## **2. Evaluation Criteria**" section (docs/CORPUS-EXTRACTION.md,
# line 2558) names 6: Mechanistic Novelty and Rigor in Fibrosis Reversal,
# Kinetic Feasibility and Experimental Readouts, Human Data Integration
# and Accuracy, Safety and Therapeutic Viability, Targeting and Delivery
# Logic, and Biological Scope Alignment. The later "Review summary"
# exemplar (line 2929) prints only 5 numbered criteria with 4/3/3/4/2
# named yes/no reviewer questions (16 total) -- Targeting and Delivery
# Logic is not a numbered criterion there because it was folded into
# Safety and Therapeutic Viability as one of its own 4 questions (line
# 2955). The count below is the union of the two sections, 6, not the
# Review summary's 5: reading only the Review summary and "correcting"
# this back to 5 silently truncates a real published criterion again.
# CRITICAL_CRITERIA_MAX_QUESTIONS stays at the Review summary's per-
# criterion ceiling (4) -- the folding changes how many *criteria* there
# are, not how many questions any one of them carries. This layer
# multiplies the response by (criteria x questions) on a call site that
# runs per hypothesis, per review, so it is capped here and re-capped
# defensively at the injection point in prompts/review.py, since
# json_object mode (the production downgrade path) does not enforce
# maxItems server-side.
CRITICAL_CRITERIA_MAX_COUNT: Final = 6
CRITICAL_CRITERIA_MAX_QUESTIONS: Final = 4

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
                            # R12-23: named to mirror the published Review
                            # summary rubric -- a criterion name plus its
                            # own named yes/no reviewer questions, not a
                            # bare name. Each question is identified by its
                            # own short name/text; there is no input pool
                            # to echo back by index here. R12-23b adds
                            # `description`, mirroring the published
                            # Evaluation Criteria section's own bolded-
                            # name-plus-prose shape (line 2558) --
                            # report-only (report_markdown_supervisor.py),
                            # deliberately excluded from the reviewer-
                            # prompt injection below (see
                            # _format_critical_criterion in
                            # prompts/review.py for why).
                            "critical_criteria": {
                                "type": "array",
                                "maxItems": CRITICAL_CRITERIA_MAX_COUNT,
                                "description": (
                                    "Up to 6 domain-specific criteria"
                                    " reviewers should emphasize, each with"
                                    " a prose description of what it"
                                    " demands and up to 4 named yes/no"
                                    " questions a reviewer would ask when"
                                    " checking a hypothesis against it."
                                ),
                                "items": obj(
                                    {
                                        "name": {
                                            "type": "string",
                                            "description": (
                                                "short criterion name"
                                            ),
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": (
                                                "one prose paragraph"
                                                " stating what this"
                                                " criterion demands of a"
                                                " hypothesis and why it"
                                                " matters for this"
                                                " research goal"
                                            ),
                                        },
                                        "questions": {
                                            "type": "array",
                                            "maxItems": (
                                                CRITICAL_CRITERIA_MAX_QUESTIONS
                                            ),
                                            "items": obj(
                                                {
                                                    "name": {
                                                        "type": "string",
                                                        "description": (
                                                            "short name for"
                                                            " this question"
                                                        ),
                                                    },
                                                    "question": {
                                                        "type": "string",
                                                        "description": (
                                                            "a specific"
                                                            " yes/no"
                                                            " question a"
                                                            " reviewer"
                                                            " would ask"
                                                        ),
                                                    },
                                                }
                                            ),
                                        },
                                    }
                                ),
                            },
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
            # Read by _format_supervisor_guidance_for_review (preferences,
            # review_instructions, attributes) and by the two generation
            # formatters in prompts/generation_formatting.py and
            # prompts/generation_debate.py (preferences plus that writer
            # mode's own instruction list).
            "config_synthesis": {
                **obj(
                    {
                        "preferences": str_array(
                            "Hard scope constraints plus the soft 'what makes"
                            " a good idea' qualities. Used by BOTH generation"
                            " and review."
                        ),
                        "draft_instructions": str_array(
                            "Writing guidance for the drafting generator"
                            " ONLY, which writes hypotheses straight from the"
                            " literature. Do NOT restate the preferences."
                        ),
                        "debate_instructions": str_array(
                            "Writing guidance for the debate generator ONLY,"
                            " which argues a hypothesis out over several"
                            " turns. Do NOT restate the preferences."
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
                    " mirroring the reference product's Config. Keep the four"
                    " instruction lists strictly separate."
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

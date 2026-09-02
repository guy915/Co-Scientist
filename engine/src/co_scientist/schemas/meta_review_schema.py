"""JSON schema for the meta-review stage.

Split out of schemas/planning.py (R14 wave) to stay under the
repo's 500-line file ceiling -- the supervisor and meta-review
schemas share no symbols, so the split is a pure move.
"""

from typing import Any, Final

from co_scientist.schemas.builders import obj, str_array

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
#
# candidate_comparison/existing_solutions_comparison (R12-9): the
# published report's per-idea comparison and its comparison against
# existing solutions belong here rather than on research_overview because
# they compare the *whole* reviewed pool (this call already sees every
# hypothesis with a review, not just the published top-k research_overview
# synthesizes from) and because Google's own analogous document
# (top-ranking-hypotheses.md, R14-11) bundles these comparisons with the
# recommendation section this schema already produces
# (strategic_recommendations, R12-11). Ideas are identified by the same
# hypothesis_index convention the prompt already establishes for
# potential_connections ("Hypothesis N: <subject>"), never by echoing a
# hypothesis's full text -- see AGENTS.md on echoing-input schemas. Both
# arrays are capped (_MAX_CANDIDATE_COMPARISON_IDEAS/_MAX_EXISTING_
# SOLUTIONS_ROWS) so a large reviewed pool cannot scale the response
# unboundedly, the same caution RESEARCH_OVERVIEW_MAX_SUB_TOPICS documents.
_MAX_CANDIDATE_COMPARISON_IDEAS: Final = 10
_MAX_EXISTING_SOLUTIONS_ROWS: Final = 6

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
                        # R14-8: the published roadmap's richer step
                        # shape -- a time estimate, an optional lettered
                        # sub-phase, and which reviewed idea a step
                        # selects. All three are empty on most steps
                        # (only some published phases carry a letter),
                        # so none can be required.
                        "time_estimate": {
                            "type": "string",
                            "description": (
                                "This step's timeline, in the run's own"
                                " units, e.g. 'Weeks 1-2' or 'Month 3+'."
                                " Empty when this step carries no"
                                " explicit timeline."
                            ),
                        },
                        "phase_label": {
                            "type": "string",
                            "description": (
                                "A lettered sub-phase name when this"
                                " step splits into parts, e.g."
                                " 'Phase A'. Empty otherwise."
                            ),
                        },
                        "recommended_idea": {
                            "type": "string",
                            "description": (
                                "Names which reviewed idea(s) this step"
                                " selects, by the same hypothesis_index"
                                " convention as candidate_comparison."
                                "ideas (e.g. 'Hypothesis 1, building on"
                                " Hypothesis 4'). Refer to ideas by"
                                " number only -- never restate their"
                                " text. Empty when this step does not"
                                " single out one idea."
                            ),
                        },
                    },
                    optional=(
                        "time_estimate",
                        "phase_label",
                        "recommended_idea",
                    ),
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
            "candidate_comparison": obj(
                {
                    "thematic_summary": {
                        "type": "string",
                        "description": (
                            "How the candidate hypotheses group into"
                            " mechanistic themes, and which is best"
                            " supported by the reviewed evidence."
                        ),
                    },
                    "ideas": {
                        "type": "array",
                        "maxItems": _MAX_CANDIDATE_COMPARISON_IDEAS,
                        "items": obj(
                            {
                                "idea": {
                                    "type": "string",
                                    "description": (
                                        "The hypothesis_index and its"
                                        " subject, e.g. 'Hypothesis 3:"
                                        " LILRB4 blockade' -- never the"
                                        " full hypothesis text."
                                    ),
                                },
                                "distinguishing_attribute": {"type": "string"},
                                "computational_scalability": {"type": "string"},
                                "supporting_evidence_basis": {"type": "string"},
                                "primary_novelty_parameter": {"type": "string"},
                            }
                        ),
                    },
                }
            ),
            "existing_solutions_comparison": obj(
                {
                    "summary": {
                        "type": "string",
                        "description": (
                            "How current standard-of-care approaches"
                            " compare to the candidate hypotheses as a"
                            " group."
                        ),
                    },
                    "rows": {
                        "type": "array",
                        "maxItems": _MAX_EXISTING_SOLUTIONS_ROWS,
                        "items": obj(
                            {
                                "method": {"type": "string"},
                                "approach": {"type": "string"},
                                "sensitivity_to_novelty": {"type": "string"},
                                "scalability": {"type": "string"},
                            }
                        ),
                    },
                }
            ),
        }
    ),
}

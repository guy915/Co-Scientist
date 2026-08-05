"""JSON schemas for the review and verification stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during single-hypothesis review, comparative
batch review, literature-grounded reflection, and deep verification.
"""

from typing import Any

from co_scientist.schemas.builders import obj, str_array

# The eight scored criteria: the paper's five default output criteria
# (SSR §1) -- relevance, plausibility, novelty, testability, safety --
# plus scientific_soundness, clarity, and potential_impact.
_SCORE_CRITERIA: tuple[str, ...] = (
    "scientific_soundness",
    "plausibility",
    "novelty",
    "relevance",
    "testability",
    "safety",
    "clarity",
    "potential_impact",
)

# Sub-schemas shared by REVIEW_SCHEMA and REVIEW_BATCH_SCHEMA, referenced
# by identity from both (nothing mutates schema dicts at runtime; sharing
# schema objects across registry entries is the established pattern -- see
# GENERATION_SCHEMA's reuse in schemas/registry.py).
_SCORES_SCHEMA: dict[str, Any] = obj(
    {name: {"type": "integer"} for name in _SCORE_CRITERIA}
)

_FEEDBACK_DESCRIPTIONS: dict[str, str] = {
    "scientific_soundness": (
        "Specific feedback on theoretical foundation and logical consistency"
    ),
    "novelty": ("Specific feedback on originality and unique contribution"),
    "relevance": "Specific feedback on alignment with research goal",
    "testability": "Specific feedback on feasibility of testing",
    "clarity": ("Specific feedback on precision and clarity of formulation"),
    "potential_impact": "Specific feedback on potential significance",
}

_DETAILED_FEEDBACK_SCHEMA: dict[str, Any] = obj(
    {
        name: {"type": "string", "description": description}
        for name, description in _FEEDBACK_DESCRIPTIONS.items()
    }
)

# Review schema
# Shapes the "review" prompt output, consumed by the single-hypothesis
# review path in agents/reflection/review.py. The scored criteria cover
# the paper's five default output criteria (SSR §1) -- relevance
# (alignment with the goal), plausibility, novelty, testability, and
# safety -- plus scientific_soundness,
# clarity, and potential_impact. Each scored criterion also appears as prose
# feedback under the matching key in detailed_feedback (safety additionally
# has the free-text safety_ethical_concerns field). overall_score is the
# average of the scores in "scores"; agents/reflection/review.py stores it
# as
# hypothesis.score, and it is later surfaced as prompt context for ranking,
# evolution, and meta-review (it does not feed the Elo rating math itself,
# which is driven solely by tournament win/loss outcomes).
REVIEW_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_review",
    "strict": False,
    "schema": obj(
        {
            "hypothesis_text": {
                "type": "string",
                "description": "The hypothesis being reviewed",
            },
            "review_summary": {
                "type": "string",
                "description": "Overall assessment (2-3 sentences)",
            },
            "scores": _SCORES_SCHEMA,
            "detailed_feedback": _DETAILED_FEEDBACK_SCHEMA,
            "constructive_feedback": {
                "type": "string",
                "description": (
                    "Specific, actionable suggestions for improvement"
                ),
            },
            "safety_ethical_concerns": {
                "type": "string",
                "description": "Any ethical or safety concerns",
            },
            "overall_score": {
                "type": "number",
                "description": "Calculated as average of criterion scores",
            },
        }
    ),
}
# Batch review schema - for reviewing multiple hypotheses together
# Shapes the "review_batch" prompt output, consumed by the comparative
# batch review path in agents/reflection/review.py. Per-item structure
# mirrors
# REVIEW_SCHEMA above (same shared scores/detailed_feedback sub-schemas)
# plus a comparative_notes field.
# Note: hypothesis_index is informational only;
# agents/reflection/review.py matches each response entry back to
# its source hypothesis by array position
# (reviews_data[i]), not by reading this field, so a wrong index value from
# the LLM does not break the mapping.
REVIEW_BATCH_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_batch_review",
    "strict": False,
    "schema": obj(
        {
            "reviews": {
                "type": "array",
                "description": "Array of reviews, one for each hypothesis",
                "items": obj(
                    {
                        "hypothesis_index": {
                            "type": "integer",
                            "description": (
                                "Index of the hypothesis being reviewed"
                                " (0-based)"
                            ),
                        },
                        "hypothesis_text": {
                            "type": "string",
                            "description": "The hypothesis being reviewed",
                        },
                        "review_summary": {
                            "type": "string",
                            "description": "Overall assessment (2-3 sentences)",
                        },
                        "scores": _SCORES_SCHEMA,
                        "detailed_feedback": _DETAILED_FEEDBACK_SCHEMA,
                        "constructive_feedback": {
                            "type": "string",
                            "description": (
                                "Specific, actionable suggestions for"
                                " improvement"
                            ),
                        },
                        "safety_ethical_concerns": {
                            "type": "string",
                            "description": "Any ethical or safety concerns",
                        },
                        "comparative_notes": {
                            "type": "string",
                            "description": (
                                "Brief note on how this hypothesis compares"
                                " to the others"
                            ),
                        },
                    },
                    optional=("comparative_notes",),
                ),
            }
        }
    ),
}
# Reflection schema
# Shapes the "reflection_observations" prompt output, consumed by
# agents/reflection/reflection.py, which checks each hypothesis
# against retrieved
# literature/knowledge-graph evidence. "classification" is a closed enum
# the rest of the pipeline treats as a categorical verdict (e.g. surfaced
# verbatim in reflection notes shown to ranking/evolution).
REFLECTION_SCHEMA: dict[str, Any] = {
    "name": "reflection_observations",
    "strict": False,
    "schema": obj(
        {
            "hypothesis_text": {
                "type": "string",
                "description": "The hypothesis being analyzed",
            },
            "reasoning": {
                "type": "string",
                "description": "Detailed reasoning for the classification",
            },
            "classification": {
                "type": "string",
                "enum": [
                    "already explained",
                    "other explanations more likely",
                    "missing piece",
                    "neutral",
                    "disproved",
                ],
                "description": (
                    "Classification of hypothesis based on literature"
                    " observations"
                ),
            },
        }
    ),
}
# Deep-verification schema
# Shapes the "deep_verification" prompt output, consumed by
# agents/reflection/deep_verification.py, which probes a hypothesis's
# fundamental
# assumptions with targeted questions. "verdict" is a closed enum
# ("holds"/"weakened"/"undermined") read back later by
# _format_deep_verification_context() in prompts.py to inject this
# hypothesis's probing history into subsequent ranking (tournament) prompts.
DEEP_VERIFICATION_SCHEMA: dict[str, Any] = {
    "name": "deep_verification",
    "schema": obj(
        {
            "probes": {
                "type": "array",
                "items": obj(
                    {
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                        "reasoning": {"type": "string"},
                        "assumption_is_fundamental": {"type": "boolean"},
                        # The question is prose, and the literature back end
                        # is a keyword index that ANDs every term, so the
                        # question itself retrieves nothing. This carries the
                        # few terms a relevant paper would actually contain,
                        # produced by the same call rather than a second one.
                        "search_query": {"type": "string"},
                    }
                ),
            },
            "verdict": {
                "type": "string",
                "enum": ["holds", "weakened", "undermined"],
            },
            "overall_assessment": {"type": "string"},
        }
    ),
}


# Full review (SSR §4): an in-depth correctness/quality/novelty review that
# also surfaces the hypothesis's key assumptions, distinct from the quick
# initial screen (REVIEW_SCHEMA).
FULL_REVIEW_SCHEMA: dict[str, Any] = {
    "name": "full_review",
    "schema": obj(
        {
            "correctness": {"type": "string"},
            "assumptions": {
                "type": "array",
                "items": obj(
                    {
                        "assumption": {"type": "string"},
                        "support": {
                            "type": "string",
                            "enum": ["supported", "uncertain", "likely_false"],
                        },
                    }
                ),
            },
            "quality_and_novelty": {"type": "string"},
            "literature_grounding": {"type": "string"},
            "verdict": {
                "type": "string",
                "enum": ["sound", "needs_revision", "rejected"],
            },
            "justification": {"type": "string"},
        }
    ),
}


# Simulation review (SSR §4): a step-through mental simulation of the proposed
# mechanism (or its test), surfacing the step where it would most likely fail.
# These properties must stay in step with what simulation_review.md asks for:
# the prompt requested a robustness assessment and the decisive step while the
# schema (closed, like every review schema here) declared neither, so the model
# answered with an undeclared `decisive_step`, validation rejected the whole
# response, and the node paid for a second full call to get the same content
# back under a name the schema accepted. Same for full_review.md above.
SIMULATION_REVIEW_SCHEMA: dict[str, Any] = {
    "name": "simulation_review",
    "schema": obj(
        {
            "model": {"type": "string"},
            "steps": {
                "type": "array",
                "items": obj(
                    {
                        "step": {"type": "string"},
                        "plausible": {"type": "boolean"},
                    }
                ),
            },
            "failure_points": str_array(),
            "robustness": {"type": "string"},
            "verdict": {
                "type": "string",
                "enum": ["holds", "partially_holds", "breaks_down"],
            },
            "decisive_step": {"type": "string"},
        }
    ),
}

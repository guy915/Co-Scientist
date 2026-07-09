"""JSON schemas for the review and verification stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during single-hypothesis review, comparative
batch review, literature-grounded reflection, and deep verification.
"""

from typing import Any

# Review schema
# Shapes the "review" prompt output, consumed by the single-hypothesis
# review path in nodes/review.py. Six fixed criteria (scientific_soundness,
# novelty, relevance, testability, clarity, potential_impact) appear twice,
# once as an integer score and once as prose feedback under the matching
# key in detailed_feedback. overall_score is expected to be the average of
# the six scores in "scores"; nodes/review.py stores it as
# hypothesis.score, and it is later surfaced as prompt context for ranking,
# evolution, and meta-review (it does not feed the Elo rating math itself,
# which is driven solely by tournament win/loss outcomes).
REVIEW_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_review",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "hypothesis_text": {
                "type": "string",
                "description": "The hypothesis being reviewed",
            },
            "review_summary": {
                "type": "string",
                "description": "Overall assessment (2-3 sentences)",
            },
            "scores": {
                "type": "object",
                "properties": {
                    "scientific_soundness": {
                        "type": "integer",
                    },
                    "novelty": {
                        "type": "integer",
                    },
                    "relevance": {
                        "type": "integer",
                    },
                    "testability": {
                        "type": "integer",
                    },
                    "clarity": {
                        "type": "integer",
                    },
                    "potential_impact": {
                        "type": "integer",
                    },
                },
                "required": [
                    "scientific_soundness",
                    "novelty",
                    "relevance",
                    "testability",
                    "clarity",
                    "potential_impact",
                ],
                "additionalProperties": False,
            },
            "detailed_feedback": {
                "type": "object",
                "properties": {
                    "scientific_soundness": {
                        "type": "string",
                        "description": (
                            "Specific feedback on theoretical foundation"
                            " and logical consistency"
                        ),
                    },
                    "novelty": {
                        "type": "string",
                        "description": (
                            "Specific feedback on originality and unique"
                            " contribution"
                        ),
                    },
                    "relevance": {
                        "type": "string",
                        "description": (
                            "Specific feedback on alignment with research goal"
                        ),
                    },
                    "testability": {
                        "type": "string",
                        "description": (
                            "Specific feedback on feasibility of testing"
                        ),
                    },
                    "clarity": {
                        "type": "string",
                        "description": (
                            "Specific feedback on precision and clarity"
                            " of formulation"
                        ),
                    },
                    "potential_impact": {
                        "type": "string",
                        "description": (
                            "Specific feedback on potential significance"
                        ),
                    },
                },
                "required": [
                    "scientific_soundness",
                    "novelty",
                    "relevance",
                    "testability",
                    "clarity",
                    "potential_impact",
                ],
                "additionalProperties": False,
            },
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
        },
        "required": [
            "hypothesis_text",
            "review_summary",
            "scores",
            "detailed_feedback",
            "constructive_feedback",
            "safety_ethical_concerns",
            "overall_score",
        ],
        "additionalProperties": False,
    },
}
# Batch review schema - for reviewing multiple hypotheses together
# Shapes the "review_batch" prompt output, consumed by the comparative
# batch review path in nodes/review.py. Per-item structure mirrors
# REVIEW_SCHEMA above (same six criteria) plus a comparative_notes field.
# Note: hypothesis_index is informational only; nodes/review.py matches
# each response entry back to its source hypothesis by array position
# (reviews_data[i]), not by reading this field, so a wrong index value from
# the LLM does not break the mapping.
REVIEW_BATCH_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_batch_review",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "reviews": {
                "type": "array",
                "description": "Array of reviews, one for each hypothesis",
                "items": {
                    "type": "object",
                    "properties": {
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
                        "scores": {
                            "type": "object",
                            "properties": {
                                "scientific_soundness": {
                                    "type": "integer",
                                },
                                "novelty": {
                                    "type": "integer",
                                },
                                "relevance": {
                                    "type": "integer",
                                },
                                "testability": {
                                    "type": "integer",
                                },
                                "clarity": {
                                    "type": "integer",
                                },
                                "potential_impact": {
                                    "type": "integer",
                                },
                            },
                            "required": [
                                "scientific_soundness",
                                "novelty",
                                "relevance",
                                "testability",
                                "clarity",
                                "potential_impact",
                            ],
                            "additionalProperties": False,
                        },
                        "detailed_feedback": {
                            "type": "object",
                            "properties": {
                                "scientific_soundness": {
                                    "type": "string",
                                    "description": (
                                        "Specific feedback on theoretical"
                                        " foundation and logical"
                                        " consistency"
                                    ),
                                },
                                "novelty": {
                                    "type": "string",
                                    "description": (
                                        "Specific feedback on originality"
                                        " and unique contribution"
                                    ),
                                },
                                "relevance": {
                                    "type": "string",
                                    "description": (
                                        "Specific feedback on alignment"
                                        " with research goal"
                                    ),
                                },
                                "testability": {
                                    "type": "string",
                                    "description": (
                                        "Specific feedback on feasibility"
                                        " of testing"
                                    ),
                                },
                                "clarity": {
                                    "type": "string",
                                    "description": (
                                        "Specific feedback on precision"
                                        " and clarity of formulation"
                                    ),
                                },
                                "potential_impact": {
                                    "type": "string",
                                    "description": (
                                        "Specific feedback on potential"
                                        " significance"
                                    ),
                                },
                            },
                            "required": [
                                "scientific_soundness",
                                "novelty",
                                "relevance",
                                "testability",
                                "clarity",
                                "potential_impact",
                            ],
                            "additionalProperties": False,
                        },
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
                    "required": [
                        "hypothesis_index",
                        "hypothesis_text",
                        "review_summary",
                        "scores",
                        "detailed_feedback",
                        "constructive_feedback",
                        "safety_ethical_concerns",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["reviews"],
        "additionalProperties": False,
    },
}
# Reflection schema
# Shapes the "reflection_observations" prompt output, consumed by
# nodes/reflection.py, which checks each hypothesis against retrieved
# literature/knowledge-graph evidence. "classification" is a closed enum
# the rest of the pipeline treats as a categorical verdict (e.g. surfaced
# verbatim in reflection notes shown to ranking/evolution).
REFLECTION_SCHEMA: dict[str, Any] = {
    "name": "reflection_observations",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
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
        },
        "required": ["hypothesis_text", "reasoning", "classification"],
        "additionalProperties": False,
    },
}
# Deep-verification schema
# Shapes the "deep_verification" prompt output, consumed by
# nodes/deep_verification.py, which probes a hypothesis's fundamental
# assumptions with targeted questions. "verdict" is a closed enum
# ("holds"/"weakened"/"undermined") read back later by
# _format_deep_verification_context() in prompts.py to inject this
# hypothesis's probing history into subsequent ranking (tournament) prompts.
DEEP_VERIFICATION_SCHEMA: dict[str, Any] = {
    "name": "deep_verification",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "probes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                        "reasoning": {"type": "string"},
                        "assumption_is_fundamental": {"type": "boolean"},
                    },
                    "required": [
                        "question",
                        "answer",
                        "reasoning",
                        "assumption_is_fundamental",
                    ],
                },
            },
            "verdict": {
                "type": "string",
                "enum": ["holds", "weakened", "undermined"],
            },
            "overall_assessment": {"type": "string"},
        },
        "required": ["probes", "verdict", "overall_assessment"],
    },
}

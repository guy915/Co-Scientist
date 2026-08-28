"""JSON schemas for the review and verification stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during single-hypothesis review, comparative
batch review, literature-grounded reflection, and deep verification.
"""

from typing import Any

from co_scientist.schemas.builders import obj, str_array

# The one vocabulary for "does the evidence back this assumption",
# shared by deep verification's sub_assumptions[].status and full
# review's assumptions[].support -- the same judgement asked twice, by
# two different reflection nodes. A single source keeps them from
# drifting into two enums that disagree again; change it here to change
# both schemas (and their prompt templates -- see
# test_prompts_schema_parity.py, which pins every enum value to be named
# in its own prompt's prose).
ASSUMPTION_SUPPORT_VALUES: tuple[str, ...] = (
    "supported",
    "uncertain",
    "likely_false",
)

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

# The review rubric's integer range, as both review prompts state it
# ("score 1-10 for each", bands 1-2 "not viable" through 9-10
# "outstanding"). Declared here so the schema bounds and the parse-time
# validation in agents/reflection/review_helpers.py share one source --
# the initial review gate's thresholds (constants.py) are calibrated
# against these same bands.
REVIEW_SCORE_MINIMUM: int = 1
REVIEW_SCORE_MAXIMUM: int = 10

# Sub-schemas shared by REVIEW_SCHEMA and REVIEW_BATCH_SCHEMA, referenced
# by identity from both (nothing mutates schema dicts at runtime; sharing
# schema objects across registry entries is the established pattern -- see
# GENERATION_SCHEMA's reuse in schemas/registry.py).
_SCORES_SCHEMA: dict[str, Any] = obj(
    {
        name: {
            "type": "integer",
            "minimum": REVIEW_SCORE_MINIMUM,
            "maximum": REVIEW_SCORE_MAXIMUM,
        }
        for name in _SCORE_CRITERIA
    }
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

# Bounds each novelty-review list (MO-3, model output). Google's published
# exemplar (docs/CORPUS-EXTRACTION.md, reviews/als-reflection-reviews.md --
# 106 lines, sha256 2f486c549886, Figure A.11) prints six already-explored
# entries and five novel-aspects entries for one hypothesis.
NOVELTY_REVIEW_MAX_ITEMS = 6

# The novelty review: two named lists distinguishing what the hypothesis
# overlaps with existing work from what it does not (MO-3). The published
# novelty review (see above) is exactly these two lists -- "Aspects already
# explored:" and "Novel Aspects:" -- and no field distinguished them before
# this; the "novelty" score/detailed_feedback pair above stays untouched,
# since it is a different judgment (a 1-10 rating, not an enumeration).
# Shared between REVIEW_SCHEMA and REVIEW_BATCH_SCHEMA by identity, the same
# pattern as _SCORES_SCHEMA/_DETAILED_FEEDBACK_SCHEMA above.
_NOVELTY_REVIEW_SCHEMA: dict[str, Any] = obj(
    {
        "already_explored": {
            **str_array(
                "Aspects of the hypothesis already covered by existing"
                " work known to you, each entry one sentence naming what"
                " is already explored. Leave empty if nothing overlaps."
            ),
            "maxItems": NOVELTY_REVIEW_MAX_ITEMS,
        },
        "novel_aspects": {
            **str_array(
                "Aspects of the hypothesis you have not seen explored"
                " before, each entry one sentence naming what is novel."
                " Leave empty if nothing is novel."
            ),
            "maxItems": NOVELTY_REVIEW_MAX_ITEMS,
        },
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
            "novelty_review": _NOVELTY_REVIEW_SCHEMA,
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
# mirrors REVIEW_SCHEMA above (same shared scores/detailed_feedback
# sub-schemas) plus a comparative_notes field.
#
# hypothesis_index identifies which hypothesis an entry belongs to: it is
# the number the prompt assigned (Hypothesis 1, Hypothesis 2, ...), and
# review_helpers._match_batch_entries_to_hypotheses reads it to map
# entries back to hypotheses (falling back to list order only for
# entries whose index is absent, invalid, or duplicated). The hypothesis
# text is deliberately NOT echoed back: echoing scaled the response with
# the batch and is forbidden by the schema contract (see the proximity
# schema's identical rationale).
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
                                "The number assigned to the hypothesis in"
                                " the prompt: 1 for Hypothesis 1, 2 for"
                                " Hypothesis 2, and so on"
                            ),
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
                        "novelty_review": _NOVELTY_REVIEW_SCHEMA,
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
# Bounds the confirmed-strengths list (audit K8). Model output, so it is
# bounded in the schema itself -- the same policy the deep-verification
# decomposition lists below apply.
REFLECTION_MAX_POSITIVE_OBSERVATIONS = 5

# Reflection schema
# Shapes the "reflection_observations" prompt output, consumed by
# agents/reflection/reflection.py, which checks each hypothesis
# against retrieved
# literature/knowledge-graph evidence. "classification" is a closed enum
# the rest of the pipeline treats as a categorical verdict (e.g. surfaced
# verbatim in reflection notes shown to ranking/evolution).
# "positive_observations" carries the review's confirmed strengths (audit
# K8): the observation review both critiques and confirms, and the paper
# appends positive observations to the hypothesis
# (agents/reflection/observation_feedback.py does the appending).
# Optional, because the review often completes without any important
# findings and a missing field must read as "none found", not as a
# failure.
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
            "positive_observations": {
                **str_array(
                    "Observations the hypothesis genuinely explains well:"
                    " confirmed strengths where it provides a superior or"
                    " mechanistically distinct explanation. Leave empty"
                    " when the review found none."
                ),
                "maxItems": REFLECTION_MAX_POSITIVE_OBSERVATIONS,
            },
        },
        optional=("positive_observations",),
    ),
}
# Deep-verification schema
# Shapes the "deep_verification" prompt output, consumed by
# agents/reflection/deep_verification.py. Beyond probing a hypothesis's
# fundamental assumptions with targeted questions, it carries the two
# other defining deep-verification behaviors (audit E4): the hypothesis
# decomposed into sub-assumptions with each one verified, and
# context-bound claims restated in general form (decontextualization).
# "verdict" is a closed enum ("holds"/"weakened"/"undermined") read back
# later by _format_deep_verification_context() in prompts.py to inject
# this hypothesis's verification into subsequent ranking (tournament)
# prompts. The code-side "unverified" verdict (a failed verification,
# audit E9) is never model output, so it is deliberately absent here.

# Bounds the decomposition lists. Both are model output, so they are
# bounded in the schema itself rather than by trimming the hypothesis the
# verifier is asked about.
DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS = 5
DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS = 3

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
            "sub_assumptions": {
                "type": "array",
                "maxItems": DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS,
                "items": obj(
                    {
                        "assumption": {"type": "string"},
                        "verification": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": list(ASSUMPTION_SUPPORT_VALUES),
                        },
                    }
                ),
            },
            "decontextualizations": {
                "type": "array",
                "maxItems": DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS,
                "items": obj(
                    {
                        "context_bound_claim": {"type": "string"},
                        "general_claim": {"type": "string"},
                        "assessment": {"type": "string"},
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
                        # MO-9: the published full review (e.g.
                        # docs/CORPUS-EXTRACTION.md,
                        # validated-outputs/kira6-detailed-output-validated.md
                        # -- 220 lines, sha256 b5a22b590874, "Reasoning about
                        # assumptions") prints a free-text paragraph beside
                        # every assumption; deep verification's
                        # sub_assumptions[].verification already carries this
                        # prose, but the full review previously carried only
                        # the closed enum below, so a hypothesis reviewed
                        # through full review alone lost the reasoning
                        # entirely.
                        "reasoning": {
                            "type": "string",
                            "description": (
                                "2-4 sentences of free-text reasoning for"
                                " why the evidence does or does not back"
                                " this assumption, referencing specific"
                                " evidence where available."
                            ),
                        },
                        "support": {
                            "type": "string",
                            "enum": list(ASSUMPTION_SUPPORT_VALUES),
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

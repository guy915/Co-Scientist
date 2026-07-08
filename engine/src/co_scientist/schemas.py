"""JSON schemas for LLM responses.

These schemas are used with response_format of type json_schema
to constrain LLM outputs to specific formats.
"""

from typing import Any

# Schemas below are grouped roughly by pipeline stage: generation, review,
# evolution, ranking, meta-review, deep verification, research overview,
# supervisor planning, and literature review. Most schemas share a name with
# a markdown prompt template in prompts/ and are wired to it through
# get_schema_for_prompt() at the bottom of this file (called from
# prompts.load_prompt_with_schema); a few (literature query generation,
# paper analysis, novelty analysis) are instead imported directly by the
# node modules that call the LLM, bypassing the name-based lookup.
#
# Generation schema
# Shapes the final-turn output of the debate-based generation node
# (nodes/generation/debate.py) for both the
# "generation_debate_and_literature" and "generation_after_debate" prompt
# templates. One hypothesis per array entry with its explanation, literature
# grounding, and proposed experiment.
GENERATION_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_generation",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hypothesis": {
                            "type":
                                "string",
                            "description":
                                ("Dense technical hypothesis following"
                                 " 'We want to develop [X] to enable [Y]'"
                                 " format (2-3 sentences maximum)"),
                        },
                        "explanation": {
                            "type":
                                "string",
                            "description":
                                ("Step-by-step layman explanation breaking"
                                 " down the technical hypothesis"
                                 " (4-6 sentences)"),
                        },
                        "literature_grounding": {
                            "type":
                                "string",
                            "description":
                                ("2-4 sentences grounding the hypothesis in"
                                 " the provided reference list. Use ONLY the"
                                 " bracketed [C*] citation keys supplied"
                                 " (e.g. [C1], [C2], [C3]) — do NOT invent"
                                 " author-year citations. If no reference"
                                 " list was provided, state that explicitly."),
                        },
                        "experiment": {
                            "type":
                                "string",
                            "description":
                                ("Concrete experiment design with models,"
                                 " datasets, metrics, and validation"
                                 " criteria (4-6 sentences)"),
                        },
                        "category": {
                            "type":
                                "string",
                            "description":
                                ("Short (2-4 word) classification label naming"
                                 " the mechanism family or research sub-area"
                                 " this hypothesis belongs to, e.g."
                                 " 'Metabolic reprogramming' or 'Epitope"
                                 " editing'. Used to group and label ideas."),
                        },
                    },
                    "required": [
                        "hypothesis", "explanation", "literature_grounding",
                        "experiment"
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["hypotheses"],
        "additionalProperties": False,
    },
}

# Generation draft schema (Phase 1: drafting without validation)
# Shapes the output of the "generation_draft_with_tools" prompt, consumed by
# the tool-using draft step in nodes/generation/literature_tools/draft.py.
# Each draft still needs a novelty-validation pass (see
# HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA below) before it becomes a final
# Hypothesis, so this schema omits literature_grounding/novelty_validation
# and instead requires gap_reasoning/literature_sources to justify the draft.
GENERATION_DRAFT_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_draft",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "drafts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hypothesis": {
                            "type":
                                "string",
                            "description":
                                ("Dense technical hypothesis following"
                                 " 'We want to develop [X] to enable [Y]'"
                                 " format (2-3 sentences maximum)"),
                        },
                        "explanation": {
                            "type":
                                "string",
                            "description":
                                ("Step-by-step layman explanation breaking"
                                 " down the technical hypothesis"
                                 " (4-6 sentences)"),
                        },
                        "experiment": {
                            "type":
                                "string",
                            "description":
                                ("Concrete experiment design with models,"
                                 " datasets, metrics, and validation"
                                 " criteria (4-6 sentences)"),
                        },
                        "gap_reasoning": {
                            "type":
                                "string",
                            "description":
                                ("Brief explanation of what gap in the"
                                 " literature this hypothesis addresses and"
                                 " why it seems promising"),
                        },
                        "literature_sources": {
                            "type":
                                "string",
                            "description":
                                ("Sources from the reference list that"
                                 " informed this gap. Use ONLY the bracketed"
                                 " [C*] keys provided (e.g. [C1], [C2],"
                                 " [C3]). Example: 'Gap identified via"
                                 " retinal imaging findings [C1] and tau"
                                 " isoform research [C2][C3].'"),
                        },
                    },
                    "required": [
                        "hypothesis",
                        "explanation",
                        "gap_reasoning",
                        "literature_sources",
                        "experiment",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["drafts"],
        "additionalProperties": False,
    },
}

# Hypothesis validation synthesis schema (Phase 2)
# Shapes the output of the "hypothesis_validation_synthesis" and
# "hypothesis_validation_synthesis_with_tools" prompts. The with-tools
# variant is the one actually invoked, by
# nodes/generation/literature_tools/validate.py (get_validation_synthesis_
# prompt_with_tools in prompts.py); the tool-less variant and its prompt
# getter (get_hypothesis_validation_synthesis_prompt) have no production
# caller and are only exercised directly by tests. novelty_validation.decision
# records whether the draft passed through unchanged ("approved"), was
# adjusted ("refined"), or was redirected to different territory ("pivoted").
HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_validation_synthesis",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hypothesis": {
                            "type":
                                "string",
                            "description":
                                ("Final dense technical hypothesis text,"
                                 " following 'We want to develop [X] to"
                                 " enable [Y]' format (2-3 sentences maximum)"
                                 " (approved/refined/pivoted)"),
                        },
                        "explanation": {
                            "type":
                                "string",
                            "description":
                                ("Step-by-step layman explanation breaking"
                                 " down the technical hypothesis"
                                 " (4-6 sentences)"),
                        },
                        "literature_grounding": {
                            "type":
                                "string",
                            "description":
                                ("2-4 sentences grounding the hypothesis in"
                                 " the provided reference list. Use ONLY the"
                                 " bracketed [C*] citation keys supplied"
                                 " (e.g. [C1], [C2], [C3]) — do NOT invent"
                                 " author-year citations. If no reference"
                                 " list was provided, state that explicitly."),
                        },
                        "experiment": {
                            "type":
                                "string",
                            "description":
                                ("Concrete experiment design with models,"
                                 " datasets, metrics, and validation"
                                 " criteria (4-6 sentences)"),
                        },
                        "category": {
                            "type":
                                "string",
                            "description":
                                ("Short (2-4 word) classification label naming"
                                 " the mechanism family or research sub-area"
                                 " this hypothesis belongs to."),
                        },
                        "novelty_validation": {
                            "type": "object",
                            "properties": {
                                "decision": {
                                    "type": "string",
                                    "description": "validation decision",
                                    "enum": ["approved", "refined", "pivoted"],
                                }
                            },
                            "required": ["decision"],
                            "additionalProperties": False,
                        },
                    },
                    "required": [
                        "hypothesis",
                        "explanation",
                        "literature_grounding",
                        "experiment",
                        "novelty_validation",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["hypotheses"],
        "additionalProperties": False,
    },
}

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
                "description": "The hypothesis being reviewed"
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
                        "type":
                            "string",
                        "description":
                            ("Specific feedback on theoretical foundation"
                             " and logical consistency"),
                    },
                    "novelty": {
                        "type":
                            "string",
                        "description":
                            ("Specific feedback on originality and unique"
                             " contribution"),
                    },
                    "relevance": {
                        "type":
                            "string",
                        "description": ("Specific feedback on alignment with"
                                        " research goal"),
                    },
                    "testability": {
                        "type":
                            "string",
                        "description": ("Specific feedback on feasibility of"
                                        " testing"),
                    },
                    "clarity": {
                        "type":
                            "string",
                        "description":
                            ("Specific feedback on precision and clarity"
                             " of formulation"),
                    },
                    "potential_impact": {
                        "type":
                            "string",
                        "description":
                            ("Specific feedback on potential significance"),
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
                "type":
                    "string",
                "description":
                    ("Specific, actionable suggestions for improvement"),
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
                            "type":
                                "integer",
                            "description":
                                ("Index of the hypothesis being reviewed"
                                 " (0-based)"),
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
                                    "type":
                                        "string",
                                    "description":
                                        ("Specific feedback on theoretical"
                                         " foundation and logical"
                                         " consistency"),
                                },
                                "novelty": {
                                    "type":
                                        "string",
                                    "description":
                                        ("Specific feedback on originality"
                                         " and unique contribution"),
                                },
                                "relevance": {
                                    "type":
                                        "string",
                                    "description":
                                        ("Specific feedback on alignment"
                                         " with research goal"),
                                },
                                "testability": {
                                    "type":
                                        "string",
                                    "description":
                                        ("Specific feedback on feasibility"
                                         " of testing"),
                                },
                                "clarity": {
                                    "type":
                                        "string",
                                    "description":
                                        ("Specific feedback on precision"
                                         " and clarity of formulation"),
                                },
                                "potential_impact": {
                                    "type":
                                        "string",
                                    "description":
                                        ("Specific feedback on potential"
                                         " significance"),
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
                            "type":
                                "string",
                            "description":
                                ("Specific, actionable suggestions for"
                                 " improvement"),
                        },
                        "safety_ethical_concerns": {
                            "type": "string",
                            "description": "Any ethical or safety concerns",
                        },
                        "comparative_notes": {
                            "type":
                                "string",
                            "description":
                                ("Brief note on how this hypothesis compares"
                                 " to the others"),
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

# Evolution schema
# Shapes the "evolution" prompt output, consumed by the
# hypothesis-refinement step in nodes/evolve.py. Represents a single refined
# hypothesis (evolution runs one hypothesis at a time); refinement_summary
# is a human-readable diff-style note, not used for further LLM prompting.
EVOLUTION_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_evolution",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "hypothesis": {
                "type":
                    "string",
                "description":
                    ("Refined dense technical hypothesis following"
                     " 'We want to develop [X] to enable [Y]' format."
                     " Similar sentence count to original hypothesis."),
            },
            "refinement_summary": {
                "type":
                    "string",
                "description":
                    ("Summary of changes and improvements made during"
                     " evolution."),
            },
            "explanation": {
                "type":
                    "string",
                "description":
                    ("Updated step-by-step layman explanation reflecting"
                     " any refinements made (4-6 sentences)"),
            },
            "experiment": {
                "type":
                    "string",
                "description":
                    ("Concrete experiment design with models, datasets,"
                     " metrics, and validation criteria (4-6 sentences)"),
            },
        },
        "required": [
            "hypothesis",
            "explanation",
            "experiment",
            "refinement_summary",
        ],
        "additionalProperties": False,
    },
}

# Meta-review schema
# Shapes the "meta_review" prompt output, consumed by
# nodes/meta_review.py after a full review pass across all hypotheses.
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
                        "theme": {
                            "type": "string"
                        },
                        "description": {
                            "type": "string"
                        },
                        "frequency": {
                            "type": "string"
                        },
                    },
                    "required": ["theme", "description", "frequency"],
                    "additionalProperties": False,
                },
            },
            "strengths": {
                "type": "array",
                "items": {
                    "type": "string"
                }
            },
            "weaknesses": {
                "type": "array",
                "items": {
                    "type": "string"
                }
            },
            "process_assessment": {
                "type": "object",
                "properties": {
                    "generation_process": {
                        "type": "string"
                    },
                    "review_process": {
                        "type": "string"
                    },
                    "evolution_process": {
                        "type": "string"
                    },
                },
                "required": [
                    "generation_process", "review_process", "evolution_process"
                ],
                "additionalProperties": False,
            },
            "strategic_recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "focus_area": {
                            "type": "string"
                        },
                        "recommendation": {
                            "type": "string"
                        },
                        "justification": {
                            "type": "string"
                        },
                    },
                    "required": [
                        "focus_area", "recommendation", "justification"
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
                            "items": {
                                "type": "string"
                            }
                        },
                        "connection_type": {
                            "type": "string"
                        },
                        "synthesis_opportunity": {
                            "type": "string"
                        },
                    },
                    "required": [
                        "related_hypotheses", "connection_type",
                        "synthesis_opportunity"
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
            "research_goal": {
                "type": "string"
            },
            "hypothesis_a": {
                "type": "string"
            },
            "hypothesis_b": {
                "type": "string"
            },
            "winner": {
                "type": "string",
                "enum": ["a", "b"],
                "description": "The winning hypothesis (a or b)",
            },
            "judgment_explanation": {
                "type": "object",
                "properties": {
                    "scientific_soundness_comparison": {
                        "type": "string"
                    },
                    "novelty_comparison": {
                        "type": "string"
                    },
                    "relevance_comparison": {
                        "type": "string"
                    },
                    "testability_comparison": {
                        "type": "string"
                    },
                    "clarity_comparison": {
                        "type": "string"
                    },
                    "impact_comparison": {
                        "type": "string"
                    },
                    "feasibility_comparison": {
                        "type": "string"
                    },
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
            "decision_summary": {
                "type": "string"
            },
            "confidence_level": {
                "type": "string",
                "enum": ["High", "Medium", "Low"]
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
                        "cluster_id": {
                            "type": "string"
                        },
                        "cluster_name": {
                            "type": "string"
                        },
                        "central_theme": {
                            "type": "string"
                        },
                        "similar_hypotheses": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {
                                        "type": "string"
                                    },
                                    "similarity_degree": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                    },
                                },
                                "required": ["text", "similarity_degree"],
                                "additionalProperties": False,
                            },
                        },
                        "synthesis_potential": {
                            "type": "string"
                        },
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
            "diversity_assessment": {
                "type": "string"
            },
            "redundancy_assessment": {
                "type": "string"
            },
        },
        "required": [
            "similarity_clusters", "diversity_assessment",
            "redundancy_assessment"
        ],
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
                "description": "The hypothesis being analyzed"
            },
            "reasoning": {
                "type": "string",
                "description": "Detailed reasoning for the classification",
            },
            "classification": {
                "type":
                    "string",
                "enum": [
                    "already explained",
                    "other explanations more likely",
                    "missing piece",
                    "neutral",
                    "disproved",
                ],
                "description":
                    ("Classification of hypothesis based on literature"
                     " observations"),
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
                    "type":
                        "object",
                    "additionalProperties":
                        False,
                    "properties": {
                        "question": {
                            "type": "string"
                        },
                        "answer": {
                            "type": "string"
                        },
                        "reasoning": {
                            "type": "string"
                        },
                        "assumption_is_fundamental": {
                            "type": "boolean"
                        },
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
            "overall_assessment": {
                "type": "string"
            },
        },
        "required": ["probes", "verdict", "overall_assessment"],
    },
}

# Research-overview schema
# Shapes the "research_overview" prompt output, consumed by
# nodes/research_overview.py at the end of a run to synthesize the
# top-ranked hypotheses into a narrative summary plus an NIH-style
# "Specific Aims" writeup (introduction / aims / impact), mirroring the
# structure NIH grant applications use for the Specific Aims page.
RESEARCH_OVERVIEW_SCHEMA: dict[str, Any] = {
    "name": "research_overview",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "overview": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {
                        "type": "string"
                    },
                    "research_directions": {
                        "type": "array",
                        "items": {
                            "type":
                                "object",
                            "additionalProperties":
                                False,
                            "properties": {
                                "title": {
                                    "type": "string"
                                },
                                "importance": {
                                    "type": "string"
                                },
                                "suggested_experiments": {
                                    "type": "array",
                                    "items": {
                                        "type": "string"
                                    },
                                },
                            },
                            "required": [
                                "title",
                                "importance",
                                "suggested_experiments",
                            ],
                        },
                    },
                },
                "required": ["summary", "research_directions"],
            },
            "nih_specific_aims": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "introduction": {
                        "type": "string"
                    },
                    "aims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "aim": {
                                    "type": "string"
                                },
                                "rationale": {
                                    "type": "string"
                                },
                                "approach": {
                                    "type": "string"
                                },
                            },
                            "required": ["aim", "rationale", "approach"],
                        },
                    },
                    "impact": {
                        "type": "string"
                    },
                },
                "required": ["introduction", "aims", "impact"],
            },
        },
        "required": ["overview", "nih_specific_aims"],
    },
}

# Supervisor schema
# Shapes the "supervisor" prompt output, consumed by nodes/supervisor.py at
# the start (and, for iterative runs, between rounds) of a run. This is the
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
                        "type":
                            "string",
                        "description":
                            "concise restatement of the research goal",
                    },
                    "key_areas": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    },
                    "constraints_identified": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    },
                    "success_criteria": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
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
            # Per-phase strategic guidance (generation/review/ranking/
            # evolution). generation_phase.focus_areas is read inline by
            # get_debate_generation_prompt; review_phase and
            # evolution_phase are read by _format_supervisor_guidance_for_
            # review/_meta_review in prompts.py. ranking_phase is captured
            # for completeness but has no reader today.
            "workflow_plan": {
                "type": "object",
                "properties": {
                    "generation_phase": {
                        "type": "object",
                        "properties": {
                            "focus_areas": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                }
                            },
                            "diversity_targets": {
                                "type":
                                    "string",
                                "description":
                                    ("description of diversity targets"
                                     " for hypotheses"),
                            },
                            "quantity_target": {
                                "type": "string",
                                "description": "target number of hypotheses",
                            },
                        },
                        "required": [
                            "focus_areas", "diversity_targets",
                            "quantity_target"
                        ],
                        "additionalProperties": False,
                    },
                    "review_phase": {
                        "type": "object",
                        "properties": {
                            "critical_criteria": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                }
                            },
                            "review_depth": {
                                "type": "string",
                                "description": "depth of review required",
                            },
                        },
                        "required": ["critical_criteria", "review_depth"],
                        "additionalProperties": False,
                    },
                    "ranking_phase": {
                        "type": "object",
                        "properties": {
                            "ranking_approach": {
                                "type":
                                    "string",
                                "description":
                                    "description of ranking approach",
                            },
                            "selection_criteria": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                }
                            },
                        },
                        "required": ["ranking_approach", "selection_criteria"],
                        "additionalProperties": False,
                    },
                    "evolution_phase": {
                        "type": "object",
                        "properties": {
                            "refinement_priorities": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                }
                            },
                            "iteration_strategy": {
                                "type":
                                    "string",
                                "description":
                                    "description of iteration strategy",
                            },
                        },
                        "required": [
                            "refinement_priorities", "iteration_strategy"
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "generation_phase",
                    "review_phase",
                    "ranking_phase",
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
                "description":
                    ("Normalized run configuration synthesized from the goal,"
                     " mirroring the reference product's Config. Keep the three"
                     " lists strictly separate."),
                "properties": {
                    "preferences": {
                        "type":
                            "array",
                        "items": {
                            "type": "string"
                        },
                        "description":
                            ("Hard scope constraints plus the soft 'what makes"
                             " a good idea' qualities. Used by BOTH generation"
                             " and review."),
                    },
                    "review_instructions": {
                        "type":
                            "array",
                        "items": {
                            "type": "string"
                        },
                        "description":
                            ("Comparative critique guidance for reviewers"
                             " ONLY: how to validate soundness and tell strong"
                             " ideas from weak ones. Do NOT restate the"
                             " preferences here."),
                    },
                    "attributes": {
                        "type": "array",
                        "description":
                            ("Up to 3 axes used to stratify and compare ideas,"
                             " each with a 1-5 scoring rubric."),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "short attribute name",
                                },
                                "rubric": {
                                    "type":
                                        "string",
                                    "description":
                                        ("how to score this attribute from 1"
                                         " (worst) to 5 (best)"),
                                },
                            },
                            "required": ["name", "rubric"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "preferences", "review_instructions", "attributes"
                ],
                "additionalProperties": False,
            },
            # performance_assessment, adjustment_recommendations, and
            # output_preparation below are stored on workflow state
            # (nodes/supervisor.py) for observability/debugging but are not
            # currently re-read by any prompt-formatting helper.
            "performance_assessment": {
                "type": "object",
                "properties": {
                    "current_status": {
                        "type": "string",
                        "description": "assessment of current workflow status",
                    },
                    "bottlenecks_identified": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    },
                    "agent_performance": {
                        "type": "object",
                        "properties": {
                            "generation_agent": {
                                "type":
                                    "string",
                                "description": ("assessment of generation agent"
                                                " performance"),
                            },
                            "reflection_agent": {
                                "type":
                                    "string",
                                "description": ("assessment of reflection agent"
                                                " performance"),
                            },
                            "ranking_agent": {
                                "type":
                                    "string",
                                "description": ("assessment of ranking agent"
                                                " performance"),
                            },
                            "evolution_agent": {
                                "type":
                                    "string",
                                "description": ("assessment of evolution agent"
                                                " performance"),
                            },
                            "proximity_agent": {
                                "type":
                                    "string",
                                "description": ("assessment of proximity agent"
                                                " performance"),
                            },
                            "meta_review_agent": {
                                "type":
                                    "string",
                                "description":
                                    ("assessment of meta-review agent"
                                     " performance"),
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
                    "current_status", "bottlenecks_identified",
                    "agent_performance"
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
                            "description": "aspect to adjust"
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
                        "type":
                            "string",
                        "description":
                            "strategy for selecting final hypotheses",
                    },
                    "presentation_format": {
                        "type":
                            "string",
                        "description":
                            "format for presenting results to scientist",
                    },
                    "key_insights_to_highlight": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
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

# Literature review query generation schema
# Imported directly (not via get_schema_for_prompt) by
# nodes/literature_review.py, which pairs it with whichever of the three
# query-generation prompt templates
# (literature_review_query_generation_pubmed/_indra/_generic) source-type
# detection selects; the schema itself is source-agnostic, it just wants a
# flat list of search-query strings.
LITERATURE_QUERY_SCHEMA: dict[str, Any] = {
    "name": "pubmed_query_generation",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "description": ("Natural language search queries for PubMed"
                                " literature search"),
                "items": {
                    "type":
                        "string",
                    "description":
                        ("A focused search phrase covering a specific"
                         " aspect of the research goal"),
                },
            }
        },
        "required": ["queries"],
        "additionalProperties": False,
    },
}

# Literature review paper analysis schema
# Imported directly (not via get_schema_for_prompt) by
# nodes/literature_review.py to structure the per-paper analysis produced
# for each fetched article (used later when synthesizing the literature
# review and, via get_literature_review_synthesis_prompt, when assembling
# the "Papers Analyzed" section of downstream generation prompts).
LITERATURE_PAPER_ANALYSIS_SCHEMA: dict[str, Any] = {
    "name": "paper_analysis",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "key_findings": {
                "type": "string",
                "description": "main contributions and results from this work",
            },
            "gaps_identified": {
                "type":
                    "string",
                "description":
                    "limitations or gaps explicitly mentioned by authors",
            },
            "future_work": {
                "type": "string",
                "description": "future research suggested by the authors",
            },
            "methodology_limitations": {
                "type": "string",
                "description": "constraints or limitations in their methods",
            },
            "unexplored_areas": {
                "type": "string",
                "description": "topics mentioned but not investigated",
            },
            "relevance": {
                "type": "string",
                "description": "how this paper relates to the research goal",
            },
        },
        "required": [
            "key_findings",
            "gaps_identified",
            "future_work",
            "methodology_limitations",
            "unexplored_areas",
            "relevance",
        ],
        "additionalProperties": False,
    },
}

# Hypothesis novelty analysis schema
# Imported directly (not via get_schema_for_prompt) by
# nodes/generation/literature_tools/validate.py, which pairs it with
# get_hypothesis_novelty_analysis_prompt to check one draft hypothesis
# against one paper at a time. novelty_assessment is a closed enum the
# validation-synthesis step reads back to judge whether a draft still
# stakes out new territory relative to the literature.
HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_novelty_analysis",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "methods_used": {
                "type": "string",
                "description": "what methods/techniques this paper employs",
            },
            "populations_studied": {
                "type": "string",
                "description": "what populations/contexts are covered",
            },
            "mechanisms_investigated": {
                "type": "string",
                "description": "what mechanisms/targets are studied",
            },
            "key_findings": {
                "type": "string",
                "description": "main findings relevant to the hypothesis",
            },
            "stated_limitations": {
                "type": "string",
                "description": "limitations or gaps the authors mention",
            },
            "future_work_suggested": {
                "type": "string",
                "description": "future directions the authors propose",
            },
            "novelty_assessment": {
                "type":
                    "string",
                "description":
                    "how hypothesis compares to this paper",
                "enum": [
                    "overlapping", "complementary", "orthogonal",
                    "addresses_gaps"
                ],
            },
            "overlap_explanation": {
                "type":
                    "string",
                "description":
                    ("detailed explanation of how hypothesis compares"
                     " to this paper"),
            },
        },
        "required": [
            "methods_used",
            "populations_studied",
            "mechanisms_investigated",
            "key_findings",
            "stated_limitations",
            "future_work_suggested",
            "novelty_assessment",
            "overlap_explanation",
        ],
        "additionalProperties": False,
    },
}


def get_schema_for_prompt(prompt_name: str) -> dict[str, Any] | None:
    """Get the JSON schema for a given prompt name.

    Args:
        prompt_name: Name of the prompt (e.g., "generation", "review")

    Returns:
        JSON schema dict or None if no schema is defined for this prompt
    """
    # Keys are the prompt template's filename stem (matching prompts/*.md,
    # without the extension), not the schema's own "name" field. Templates
    # with no entry here (e.g. the three query-generation variants, which
    # are conversational/plain-text) legitimately return None so
    # load_prompt_with_schema in prompts.py yields a schema-less call.
    schema_map = {
        "generation_draft_with_tools":
            GENERATION_DRAFT_SCHEMA,
        "generation_debate_and_literature":
            GENERATION_SCHEMA,
        "generation_after_debate":
            GENERATION_SCHEMA,
        "review":
            REVIEW_SCHEMA,
        "review_batch":
            REVIEW_BATCH_SCHEMA,
        "evolution":
            EVOLUTION_SCHEMA,
        "meta_review":
            META_REVIEW_SCHEMA,
        "ranking":
            RANKING_SCHEMA,
        "proximity":
            PROXIMITY_SCHEMA,
        "reflection_observations":
            REFLECTION_SCHEMA,
        "deep_verification":
            DEEP_VERIFICATION_SCHEMA,
        "research_overview":
            RESEARCH_OVERVIEW_SCHEMA,
        "supervisor":
            SUPERVISOR_SCHEMA,
        "literature_review_paper_analysis":
            LITERATURE_PAPER_ANALYSIS_SCHEMA,
        "hypothesis_novelty_analysis":
            HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
        "hypothesis_validation_synthesis":
            HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
        "hypothesis_validation_synthesis_with_tools":
            HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
    }

    return schema_map.get(prompt_name)

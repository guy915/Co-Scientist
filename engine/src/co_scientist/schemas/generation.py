"""JSON schemas for the hypothesis-generation stage.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during hypothesis drafting, debate-based
generation, novelty analysis, and validation synthesis.
"""

from typing import Any

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
                            "type": "string",
                            "description": (
                                "Mechanistic scientific hypothesis stated in"
                                " the natural language of the goal's"
                                " domain: name the entities, mechanism,"
                                " direction of effect, conditions, and"
                                " the specific testable prediction. Do"
                                " not use a fixed 'We want to develop'"
                                " phrasing or an artificial length cap"
                            ),
                        },
                        "explanation": {
                            "type": "string",
                            "description": (
                                "Step-by-step layman explanation breaking"
                                " down the technical hypothesis"
                                " (4-6 sentences)"
                            ),
                        },
                        "literature_grounding": {
                            "type": "string",
                            "description": (
                                "2-4 sentences grounding the hypothesis in"
                                " the provided reference list. Use ONLY the"
                                " bracketed [C*] citation keys supplied"
                                " (e.g. [C1], [C2], [C3]) — do NOT invent"
                                " author-year citations. If no reference"
                                " list was provided, state that explicitly."
                            ),
                        },
                        "experiment": {
                            "type": "string",
                            "description": (
                                "Concrete experiment design with models,"
                                " datasets, metrics, and validation"
                                " criteria (4-6 sentences)"
                            ),
                        },
                        "category": {
                            "type": "string",
                            "description": (
                                "Short (2-4 word) classification label naming"
                                " the mechanism family or research sub-area"
                                " this hypothesis belongs to, e.g."
                                " 'Metabolic reprogramming' or 'Epitope"
                                " editing'. Used to group and label ideas."
                            ),
                        },
                    },
                    "required": [
                        "hypothesis",
                        "explanation",
                        "literature_grounding",
                        "experiment",
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
                            "type": "string",
                            "description": (
                                "Mechanistic scientific hypothesis stated in"
                                " the natural language of the goal's"
                                " domain: name the entities, mechanism,"
                                " direction of effect, conditions, and"
                                " the specific testable prediction. Do"
                                " not use a fixed 'We want to develop'"
                                " phrasing or an artificial length cap"
                            ),
                        },
                        "explanation": {
                            "type": "string",
                            "description": (
                                "Step-by-step layman explanation breaking"
                                " down the technical hypothesis"
                                " (4-6 sentences)"
                            ),
                        },
                        "experiment": {
                            "type": "string",
                            "description": (
                                "Concrete experiment design with models,"
                                " datasets, metrics, and validation"
                                " criteria (4-6 sentences)"
                            ),
                        },
                        "gap_reasoning": {
                            "type": "string",
                            "description": (
                                "Brief explanation of what gap in the"
                                " literature this hypothesis addresses and"
                                " why it seems promising"
                            ),
                        },
                        "literature_sources": {
                            "type": "string",
                            "description": (
                                "Sources from the reference list that"
                                " informed this gap. Use ONLY the bracketed"
                                " [C*] keys provided (e.g. [C1], [C2],"
                                " [C3]). Example: 'Gap identified via"
                                " retinal imaging findings [C1] and tau"
                                " isoform research [C2][C3].'"
                            ),
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
                            "type": "string",
                            "description": (
                                "Final mechanistic scientific hypothesis"
                                " text in the goal's domain language, naming"
                                " entities, mechanism, direction of effect,"
                                " and the testable prediction, without a fixed"
                                " phrasing or length cap (approved/refined/"
                                "pivoted)"
                            ),
                        },
                        "explanation": {
                            "type": "string",
                            "description": (
                                "Step-by-step layman explanation breaking"
                                " down the technical hypothesis"
                                " (4-6 sentences)"
                            ),
                        },
                        "literature_grounding": {
                            "type": "string",
                            "description": (
                                "2-4 sentences grounding the hypothesis in"
                                " the provided reference list. Use ONLY the"
                                " bracketed [C*] citation keys supplied"
                                " (e.g. [C1], [C2], [C3]) — do NOT invent"
                                " author-year citations. If no reference"
                                " list was provided, state that explicitly."
                            ),
                        },
                        "experiment": {
                            "type": "string",
                            "description": (
                                "Concrete experiment design with models,"
                                " datasets, metrics, and validation"
                                " criteria (4-6 sentences)"
                            ),
                        },
                        "category": {
                            "type": "string",
                            "description": (
                                "Short (2-4 word) classification label naming"
                                " the mechanism family or research sub-area"
                                " this hypothesis belongs to."
                            ),
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
                "type": "string",
                "description": "how hypothesis compares to this paper",
                "enum": [
                    "overlapping",
                    "complementary",
                    "orthogonal",
                    "addresses_gaps",
                ],
            },
            "overlap_explanation": {
                "type": "string",
                "description": (
                    "detailed explanation of how hypothesis compares"
                    " to this paper"
                ),
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

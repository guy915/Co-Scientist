"""JSON schemas for the hypothesis-generation stage.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during hypothesis drafting, debate-based
generation, novelty analysis, and validation synthesis.
"""

from typing import Any

from co_scientist.schemas.builders import obj, str_array

# Field sub-schemas shared verbatim across the generation schemas below,
# referenced by identity (nothing mutates schema dicts at runtime; sharing
# schema objects is the established pattern -- see schemas/review.py). The
# validation-synthesis schema keeps its own "hypothesis" wording (it describes
# a *final* hypothesis), so that field is not shared.
_HYPOTHESIS_FIELD: dict[str, Any] = {
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
}

_EXPLANATION_FIELD: dict[str, Any] = {
    "type": "string",
    "description": (
        "Step-by-step layman explanation breaking"
        " down the technical hypothesis"
        " (4-6 sentences)"
    ),
}

_EXPERIMENT_FIELD: dict[str, Any] = {
    "type": "string",
    "description": (
        "Concrete experiment design with models,"
        " datasets, metrics, and validation"
        " criteria (4-6 sentences)"
    ),
}

_LITERATURE_GROUNDING_FIELD: dict[str, Any] = {
    "type": "string",
    "description": (
        "2-4 sentences grounding the hypothesis in"
        " the provided reference list. Use ONLY the"
        " bracketed [C*] citation keys supplied"
        " (e.g. [C1], [C2], [C3]) — do NOT invent"
        " author-year citations. If no reference"
        " list was provided, state that explicitly."
    ),
}

# Generation schema
# Shapes the final-turn output of the debate-based generation node
# (agents/generation/debate.py) for both the
# "generation_debate_and_literature" and "generation_after_debate" prompt
# templates. One hypothesis per array entry with its explanation, literature
# grounding, and proposed experiment.
GENERATION_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_generation",
    "strict": False,
    "schema": obj(
        {
            "hypotheses": {
                "type": "array",
                "items": obj(
                    {
                        "hypothesis": _HYPOTHESIS_FIELD,
                        "explanation": _EXPLANATION_FIELD,
                        "literature_grounding": _LITERATURE_GROUNDING_FIELD,
                        "experiment": _EXPERIMENT_FIELD,
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
                    optional=("category",),
                ),
            }
        }
    ),
}
# Generation draft schema (Phase 1: drafting without validation)
# Shapes the output of the "generation_draft_with_tools" prompt, consumed by
# the tool-using draft step in agents/generation/literature_tools/draft.py.
# Each draft still needs a novelty-validation pass (see
# HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA below) before it becomes a final
# Hypothesis, so this schema omits literature_grounding/novelty_validation
# and instead requires gap_reasoning/literature_sources to justify the draft.
GENERATION_DRAFT_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_draft",
    "strict": False,
    "schema": obj(
        {
            "drafts": {
                "type": "array",
                "items": obj(
                    {
                        "hypothesis": _HYPOTHESIS_FIELD,
                        "explanation": _EXPLANATION_FIELD,
                        "experiment": _EXPERIMENT_FIELD,
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
                ),
            }
        }
    ),
}
# Hypothesis validation synthesis schema (Phase 2)
# Shapes the output of the "hypothesis_validation_synthesis" and
# "hypothesis_validation_synthesis_with_tools" prompts. The with-tools
# variant is the one actually invoked, by
# agents/generation/literature_tools/validate.py (get_validation_synthesis_
# prompt_with_tools in prompts.py); the tool-less variant and its prompt
# getter (get_hypothesis_validation_synthesis_prompt) have no production
# caller and are only exercised directly by tests. novelty_validation.decision
# records whether the draft passed through unchanged ("approved"), was
# adjusted ("refined"), or was redirected to different territory ("pivoted").
HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_validation_synthesis",
    "strict": False,
    "schema": obj(
        {
            "hypotheses": {
                "type": "array",
                "items": obj(
                    {
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
                        "explanation": _EXPLANATION_FIELD,
                        "literature_grounding": _LITERATURE_GROUNDING_FIELD,
                        "experiment": _EXPERIMENT_FIELD,
                        "category": {
                            "type": "string",
                            "description": (
                                "Short (2-4 word) classification label naming"
                                " the mechanism family or research sub-area"
                                " this hypothesis belongs to."
                            ),
                        },
                        "novelty_validation": obj(
                            {
                                "decision": {
                                    "type": "string",
                                    "description": "validation decision",
                                    "enum": ["approved", "refined", "pivoted"],
                                }
                            }
                        ),
                    },
                    optional=("category",),
                ),
            }
        }
    ),
}
# Assumption-tree schemas (SSR §4, audit E12): the assumptions technique
# builds an iterative assumption/sub-assumption tree before generating
# hypotheses, in two bounded schema calls ahead of the final
# GENERATION_SCHEMA call. The top level lists the area's taken-for-granted
# assumptions and marks the load-bearing ones; the sub level decomposes
# selected parents, identified by their POSITIONAL INDEX in the prompt's
# numbered parent list -- never by echoing the parent's text back (an
# echoing schema would scale the output with the input and truncate on
# large trees, the way proximity's once did).
ASSUMPTION_TREE_SCHEMA: dict[str, Any] = {
    "name": "assumption_tree",
    "strict": False,
    "schema": obj(
        {
            "assumptions": {
                "type": "array",
                "description": ("The area's key taken-for-granted assumptions"),
                "items": obj(
                    {
                        "assumption": {
                            "type": "string",
                            "description": (
                                "One assumption currently taken for"
                                " granted in this research area"
                            ),
                        },
                        "load_bearing": {
                            "type": "boolean",
                            "description": (
                                "True if this assumption is load-bearing:"
                                " much of the area's reasoning depends on"
                                " it, so challenging it would open new"
                                " hypothesis space"
                            ),
                        },
                    }
                ),
            }
        }
    ),
}
ASSUMPTION_SUB_SCHEMA: dict[str, Any] = {
    "name": "assumption_sub_assumptions",
    "strict": False,
    "schema": obj(
        {
            "parents": {
                "type": "array",
                "description": (
                    "Sub-assumption decompositions, one entry per"
                    " expanded parent assumption"
                ),
                "items": obj(
                    {
                        "parent_index": {
                            "type": "integer",
                            "description": (
                                "The 0-based index of the parent"
                                " assumption in the numbered list the"
                                " prompt supplied"
                            ),
                        },
                        "sub_assumptions": str_array(
                            "The finer-grained sub-assumptions the parent"
                            " decomposes into"
                        ),
                    }
                ),
            }
        }
    ),
}
# Hypothesis novelty analysis schema
# Imported directly (not via get_schema_for_prompt) by
# agents/generation/literature_tools/validate.py, which pairs it with
# get_hypothesis_novelty_analysis_prompt to check one draft hypothesis
# against one paper at a time. novelty_assessment is a closed enum the
# validation-synthesis step reads back to judge whether a draft still
# stakes out new territory relative to the literature.
HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_novelty_analysis",
    "strict": False,
    "schema": obj(
        {
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
        }
    ),
}

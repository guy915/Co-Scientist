"""JSON schemas for the hypothesis-generation stage.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during hypothesis drafting, debate-based
generation, novelty analysis, and validation synthesis.
"""

from typing import Any, Final

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
        " down the technical hypothesis: trace"
        " each mechanistic step from intervention"
        " to outcome and say why each step is"
        " expected to hold. Depth over brevity;"
        " a full paragraph, not a summary"
    ),
}

# R14-20 (docs/CORPUS-EXTRACTION.md): Google's published test plan is a
# numbered pilot -- 2-5 steps, typically scripting/automation, then
# ground-truth calibration, then an outgroup/control comparison, then a
# concluding Go/No-Go Initial Experiment step -- closing on separately
# bolded **Go:**/**No-Go:** criteria that state the exact pass/fail
# threshold. Structured here (steps + go_criterion/no_go_criterion)
# rather than left as one free-text paragraph, so the threshold is its
# own field instead of prose a reader has to hunt through.
#
# This is the hypothesis's OWN proposed pilot threshold -- an experiment
# *design* detail -- not a review verdict. Never confuse it with
# go_no_go_recommendation on REVIEW_SCHEMA's full/recurrent review
# (R14-15, schemas/review.py), a reviewer's testing recommendation about
# the idea as a whole; the two live at different call sites and are
# never merged. Nothing in this codebase may read go_criterion/
# no_go_criterion to filter, rank, score, or disqualify a hypothesis --
# this repo has a recorded incident where a never-revisited review gate
# alone blocked 20 of 22 ideas and shrank the pool evolution bred from
# (root AGENTS.md Gotchas, "An early gate that never reverses decides
# the whole run"). test_experiment_plan.py::
# test_criteria_never_reach_a_structured_hypothesis_field pins the
# guarantee: format_experiment_plan collapses both criteria into prose
# before they ever reach Hypothesis, which has no go_criterion/
# no_go_criterion field for anything to gate on.
#
# MAX_EXPERIMENT_STEPS/_EXPERIMENT_*_CHARS bound the formatter in
# agents/generation/experiment_plan.py (imported from there, never the
# reverse, so this package keeps its no-runtime-imports convention) --
# named here, not there, so the cap this field's own description states
# can never drift from the cap actually enforced on the response.
MAX_EXPERIMENT_STEPS: Final = 5
_EXPERIMENT_STEP_CHARS: Final = 300
_EXPERIMENT_CRITERION_CHARS: Final = 300

_EXPERIMENT_STEP_FIELD: dict[str, Any] = {
    "type": "string",
    "description": (
        "One ordered step of the concrete pilot plan: what is done and"
        " what it establishes. 1-2 sentences."
    ),
}

_EXPERIMENT_FIELD: dict[str, Any] = obj(
    {
        "steps": {
            "type": "array",
            "items": _EXPERIMENT_STEP_FIELD,
            "description": (
                f"2-{MAX_EXPERIMENT_STEPS} ordered steps of the pilot"
                " test plan -- typically scripting/automation setup,"
                " then ground-truth calibration, then an"
                " outgroup/control comparison, ending with the Go/No-Go"
                " initial experiment step itself. State the pass/fail"
                " threshold in go_criterion/no_go_criterion below, not"
                " here."
            ),
        },
        "go_criterion": {
            "type": "string",
            "description": (
                "The exact quantitative pass threshold for the Go/No-Go"
                " initial experiment step: the specific result that"
                " would justify continuing to the next phase."
            ),
        },
        "no_go_criterion": {
            "type": "string",
            "description": (
                "The exact quantitative fail threshold for the Go/No-Go"
                " initial experiment step: the specific result that"
                " would justify abandoning or substantially revising"
                " the approach."
            ),
        },
    }
)

# Phase 1 draft sketch only: kept as free prose, unlike the structured
# pilot plan above, because nothing downstream ever reads a draft's
# `experiment` back out. prompts/generation_validation.py's
# _format_novelty_hypothesis_section (the only place a draft dict is
# read again) forwards just text/gap_reasoning/literature_sources into
# the Phase 2 synthesis prompt that produces the hypothesis's real,
# structured experiment field -- restructuring a field whose output is
# discarded would spend output tokens on nothing.
_EXPERIMENT_DRAFT_FIELD: dict[str, Any] = {
    "type": "string",
    "description": (
        "Complete experiment design: model system,"
        " groups and controls, quantitative"
        " readouts with expected effect sizes or"
        " thresholds, and validation criteria"
        " distinguishing support from falsification."
        " Depth over brevity; a full paragraph,"
        " not a sketch"
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

# MO-6: every published proposal opens with scene-setting -- an
# Introduction and a Recent findings and related research section -- before
# the mechanism (docs/CORPUS-EXTRACTION.md, hypotheses/als-generation-
# output.md -- 34 lines, sha256 025d46737463, and validated-outputs/kira6-
# detailed-output-validated.md -- 220 lines, sha256 b5a22b590874). No field
# carried this before, so a reader went from the title straight into the
# mechanism. Bounded to 2-4 sentences each (unlike the published exemplars'
# full paragraphs) since this is model output emitted per hypothesis in an
# array: an unbounded pair of new fields scales output tokens with pool
# size.
_INTRODUCTION_FIELD: dict[str, Any] = {
    "type": "string",
    "description": (
        "2-4 sentences of scene-setting background: the problem area"
        " this hypothesis addresses and why it matters, before any"
        " specific mechanism is proposed. Matches the published"
        " 'Introduction' section."
    ),
}

_RECENT_FINDINGS_FIELD: dict[str, Any] = {
    "type": "string",
    "description": (
        "2-4 sentences summarizing recent findings and related"
        " research this hypothesis builds on, extends, or departs"
        " from. Matches the published 'Recent findings and related"
        " research' section. Distinct from literature_grounding: this"
        " sets the scene, literature_grounding argues the specific"
        " hypothesis."
    ),
}

# MO-10: the published proposal itself carries a pharmacological safety and
# toxicity section (docs/CORPUS-EXTRACTION.md, validated-outputs/kira6-
# detailed-output-validated.md -- 220 lines, sha256 b5a22b590874). Distinct
# from the reviewer's safety_ethical_concerns (dual-use/ethics judgment,
# REVIEW_SCHEMA): this is the proposer's own pharmacological assessment of
# what it is proposing, and must never feed the safety gate (see
# agents/safety/) -- a proposer-authored field cannot be allowed to
# influence whether its own hypothesis passes screening. Bounded the same
# way as the scene-setting fields above.
_SAFETY_TOXICITY_FIELD: dict[str, Any] = {
    "type": "string",
    "description": (
        "2-4 sentences on the safety profile of what this hypothesis"
        " proposes: for a pharmacological intervention, known or"
        " expected toxicity and what preclinical safety work would be"
        " needed before advancing it; for other domains, the analogous"
        " operational or experimental safety considerations. This is"
        " your own assessment as the proposer, not a review."
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
                        "introduction": _INTRODUCTION_FIELD,
                        "recent_findings": _RECENT_FINDINGS_FIELD,
                        "hypothesis": _HYPOTHESIS_FIELD,
                        "explanation": _EXPLANATION_FIELD,
                        "literature_grounding": _LITERATURE_GROUNDING_FIELD,
                        "experiment": _EXPERIMENT_FIELD,
                        # Required (K7): categorization was inconsistent
                        # while the field was optional and absent from the
                        # prompt body; the templates now present the value
                        # contract alongside this schema.
                        "category": {
                            "type": "string",
                            "description": (
                                "Short (2-4 word) classification label naming"
                                " the mechanism family or research sub-area"
                                " this hypothesis belongs to, e.g."
                                " 'Metabolic reprogramming' or 'Epitope"
                                " editing'. Used to group and label ideas."
                                " Hypotheses from the same mechanism family"
                                " must carry the same label."
                            ),
                        },
                        "safety_and_toxicity": _SAFETY_TOXICITY_FIELD,
                    },
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
                        "experiment": _EXPERIMENT_DRAFT_FIELD,
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
                        "introduction": _INTRODUCTION_FIELD,
                        "recent_findings": _RECENT_FINDINGS_FIELD,
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
                        # Required (K7): the same contract as the generation
                        # schema's category, which this final hypothesis is
                        # published with.
                        "category": {
                            "type": "string",
                            "description": (
                                "Short (2-4 word) classification label naming"
                                " the mechanism family or research sub-area"
                                " this hypothesis belongs to. Hypotheses from"
                                " the same mechanism family must carry the"
                                " same label."
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
                        "safety_and_toxicity": _SAFETY_TOXICITY_FIELD,
                    },
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

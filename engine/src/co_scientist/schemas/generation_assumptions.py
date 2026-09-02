"""JSON schemas for the assumptions generation technique.

Split out of schemas/generation.py at the file-size cap (evaluations/tests/
test_file_length.py). Distinct concern from the debate-based generation
schemas that module keeps: these back the assumptions technique's own two
bounded schema calls (SSR §4, audit E12) ahead of the shared
GENERATION_SCHEMA call, plus the standalone novelty-analysis schema used by
the tool-based validation path. Re-exported from generation.py so every
existing `from co_scientist.schemas.generation import ...` import (registry.py,
schemas/__init__.py) keeps working unchanged.
"""

from typing import Any

from co_scientist.schemas.builders import obj, str_array

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

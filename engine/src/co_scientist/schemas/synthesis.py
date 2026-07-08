"""JSON schemas for the evolution and research-overview stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during hypothesis evolution (refinement) and
final research-overview synthesis.
"""

from typing import Any

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

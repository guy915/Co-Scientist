"""JSON schemas for the evolution and research-overview stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during hypothesis evolution (refinement) and
final research-overview synthesis.
"""

from typing import Any

from co_scientist.schemas.builders import obj, str_array

# Evolution's experiment field asks for exactly what generation's does, so
# it is the same object rather than a second copy of the wording (schema
# dicts are never mutated; sharing them by identity is this package's
# established pattern). The sibling explanation field legitimately differs
# -- it asks for the refinements -- so it is written out below.
from co_scientist.schemas.generation import _EXPERIMENT_FIELD

# Evolution schema
# Shapes the "evolution" prompt output, consumed by the
# hypothesis-refinement step in agents/evolution/evolve.py. Represents a
# single refined hypothesis (evolution runs one hypothesis at a time);
# refinement_summary
# is a human-readable diff-style note, not used for further LLM prompting.
#
# Multi-parent combination identifies the partners it merged by the
# positional index the prompt assigned them -- never by echoing their text,
# which would scale the response with the partners' length (the same trap
# proximity clustering hit; see proximity_dedup._match_cluster_member).
EVOLUTION_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_evolution",
    "strict": False,
    "schema": obj(
        {
            "hypothesis": {
                "type": "string",
                "description": (
                    "Refined mechanistic hypothesis in the domain's"
                    " natural language, naming entities, mechanism, and"
                    " the testable prediction (no fixed phrasing)."
                ),
            },
            "refinement_summary": {
                "type": "string",
                "description": (
                    "Summary of changes and improvements made during evolution."
                ),
            },
            "explanation": {
                "type": "string",
                "description": (
                    "Updated step-by-step layman explanation reflecting"
                    " any refinements made (4-6 sentences)"
                ),
            },
            "experiment": _EXPERIMENT_FIELD,
            "combined_partners": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "Combination operator only: the 1-based positional "
                    "indices of the partner hypotheses whose mechanisms "
                    "this refinement merges. Omit for every other operator "
                    "and never repeat a partner's text."
                ),
            },
        },
        # Identification only, and only for the combination operator; every
        # other operator omits it.
        optional=("combined_partners",),
    ),
}
# Research-overview schema
# Shapes the "research_overview" prompt output, consumed by
# agents/meta_review/research_overview.py at the end of a run to synthesize
# the
# top-ranked hypotheses into a narrative summary plus an NIH-style
# "Specific Aims" writeup (introduction / aims / impact), mirroring the
# structure NIH grant applications use for the Specific Aims page.
RESEARCH_OVERVIEW_SCHEMA: dict[str, Any] = {
    "name": "research_overview",
    "schema": obj(
        {
            "overview": obj(
                {
                    "summary": {"type": "string"},
                    "research_directions": {
                        "type": "array",
                        "items": obj(
                            {
                                "title": {"type": "string"},
                                "importance": {"type": "string"},
                                "suggested_experiments": str_array(),
                            }
                        ),
                    },
                }
            ),
            "nih_specific_aims": obj(
                {
                    "introduction": {"type": "string"},
                    "aims": {
                        "type": "array",
                        "items": obj(
                            {
                                "aim": {"type": "string"},
                                "rationale": {"type": "string"},
                                "approach": {"type": "string"},
                            }
                        ),
                    },
                    "impact": {"type": "string"},
                }
            ),
            "research_contacts": {
                "type": "array",
                "maxItems": 5,
                "items": obj(
                    {
                        "candidate_id": {"type": "string"},
                        "name": {"type": "string"},
                        "expertise": {"type": "string"},
                        "justification": {"type": "string"},
                    }
                ),
            },
            "knowledge_base": {
                "type": "array",
                "maxItems": 8,
                "items": obj(
                    {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "detail": {"type": "string"},
                        "uncertainty": {"type": "string"},
                        "evidence_ids": str_array(),
                    }
                ),
            },
        }
    ),
}
# Research-overview review schema
# Shapes the "research_overview_review" prompt output, consumed by
# agents/meta_review/research_overview_review.py. A verdict over the
# already-drafted overview above: accept it as-is, or list specific,
# located accuracy problems for the reviser to fix. Deliberately does not
# echo the drafted passage back -- a schema that echoes its input scales
# output with input and truncates identically on every retry (the same
# trap proximity clustering hit; see proximity_dedup._match_cluster_member).
# Each note instead names the section or claim it concerns.
RESEARCH_OVERVIEW_REVIEW_SCHEMA: dict[str, Any] = {
    "name": "research_overview_review",
    "schema": obj(
        {
            "accept": {
                "type": "boolean",
                "description": (
                    "True only when every claim in the drafted overview "
                    "is supported by the listed hypotheses and evidence, "
                    "with no contradiction and no overstated confidence. "
                    "False for a genuine accuracy problem -- never for "
                    "tone, style, or length."
                ),
            },
            "notes": {
                "type": "array",
                "maxItems": 6,
                "items": obj(
                    {
                        "location": {
                            "type": "string",
                            "description": (
                                "The section or claim this note concerns "
                                "(e.g. 'overview.summary', 'aims[2]', or "
                                "a knowledge-base topic's title) -- never "
                                "the passage text itself."
                            ),
                        },
                        "issue": {
                            "type": "string",
                            "description": (
                                "The specific accuracy problem: an "
                                "unsupported claim, a contradiction with "
                                "a listed hypothesis, overstated "
                                "confidence the material does not carry, "
                                "or a cited evidence_id that does not "
                                "support what it is cited for."
                            ),
                        },
                        "evidence_id": {
                            "type": "string",
                            "description": (
                                "The evidence_id involved, when the issue "
                                "concerns a citation."
                            ),
                        },
                    },
                    optional=("evidence_id",),
                ),
            },
        },
        optional=("notes",),
    ),
}

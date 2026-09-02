"""JSON schemas for the evolution and research-overview stages.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during hypothesis evolution (refinement) and
final research-overview synthesis.
"""

from typing import Any, Final

from co_scientist.schemas.builders import obj, str_array

# Evolution's experiment and title fields ask for exactly what generation's
# do, so they are the same objects rather than second copies of the wording
# (schema dicts are never mutated; sharing them by identity is this
# package's established pattern). _TITLE_FIELD's ask -- a compact authored
# noun phrase -- reads identically whether the hypothesis is new or refined
# (R14-12), so it needs no evolution-specific rewording the way explanation
# does below. The sibling explanation field legitimately differs -- it asks
# for the refinements -- so it is written out below.
from co_scientist.schemas.generation import _EXPERIMENT_FIELD, _TITLE_FIELD

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
            "title": _TITLE_FIELD,
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

# Bounds on the sub-topic layer below (MO-1). Google's published cf-PICI
# exemplar nests exactly 4 named sub-topics per direction, each with 4
# specific questions, consistently across all 6 directions -- these bounds
# mirror the exemplar rather than being picked arbitrarily. Kept small on
# purpose: this layer multiplies the response by (directions x sub-topics),
# and this schema has already been bitten by an unbounded nesting silently
# truncating a large run's output on every retry (see AGENTS.md). Enforced
# again defensively in research_overview_directions.py, since json_object
# mode (the production downgrade path) does not enforce maxItems
# server-side.
RESEARCH_OVERVIEW_MAX_SUB_TOPICS: Final = 4
RESEARCH_OVERVIEW_MAX_SUB_TOPIC_QUESTIONS: Final = 4

# R12-10: bounds on open_questions/clear_patterns/unexpected_patterns
# below, mirroring the published exemplar's "Top 10 Open Questions" list
# and its two shorter pattern lists. Capped for the same reason as the
# sub-topic bounds above -- this is the terminal synthesis call and its
# output must not scale unboundedly with what the run reviewed.
RESEARCH_OVERVIEW_MAX_OPEN_QUESTIONS: Final = 10
RESEARCH_OVERVIEW_MAX_PATTERNS: Final = 5

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
                                # MO-12: the "what is already known" slot
                                # the ALS exemplar names "Recent Findings"
                                # (cf-PICI's own equivalent is a bullet
                                # folded under "Why Research This Area?"
                                # rather than a separate section -- the
                                # two published exemplars disagree on
                                # vocabulary here; this adds ALS's slot
                                # onto the cf-PICI pair we already mirror,
                                # rather than switching vocabularies).
                                "recent_findings": {"type": "string"},
                                # MO-1: each direction's "What to Research
                                # in This Area?" (cf-PICI) / "Areas of
                                # Research" (ALS) is itself a list of
                                # named sub-topics, not a flat experiment
                                # list -- restored here one level below
                                # the direction. Identify sub-topics by
                                # their own content; there is no input
                                # pool to echo back by index here.
                                "sub_topics": {
                                    "type": "array",
                                    "maxItems": (
                                        RESEARCH_OVERVIEW_MAX_SUB_TOPICS
                                    ),
                                    "items": obj(
                                        {
                                            "title": {"type": "string"},
                                            "why": {"type": "string"},
                                            "what": {"type": "string"},
                                            "specific_questions": {
                                                **str_array(),
                                                "maxItems": (
                                                    RESEARCH_OVERVIEW_MAX_SUB_TOPIC_QUESTIONS
                                                ),
                                            },
                                        }
                                    ),
                                },
                            }
                        ),
                    },
                }
            ),
            # The page's sections are the ones Google's three published
            # Specific Aims exemplars actually print (paper §A.5.3), not a
            # generic grant outline: a Disease Description / Unmet Need /
            # Proposed Solution preamble, the numbered aims, and a closing
            # Pilot Evaluation. The earlier shape -- introduction / aims
            # (aim, rationale, approach) / impact -- was a richer page than
            # any exemplar shows, and dropped the per-aim hypothesis every
            # exemplar states. test_published_artifact_shapes.py pins this
            # against the exemplar files themselves.
            "nih_specific_aims": obj(
                {
                    "disease_description": {"type": "string"},
                    "unmet_need": {"type": "string"},
                    "proposed_solution": {"type": "string"},
                    "aims": {
                        "type": "array",
                        "items": obj(
                            {
                                "overarching_goal": {"type": "string"},
                                "hypothesis": {"type": "string"},
                                "reasoning": {"type": "string"},
                            }
                        ),
                    },
                    "pilot_evaluation": {"type": "string"},
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
                        # Ties the contact back to the direction from #2
                        # that surfaced them (MO-7) -- free text, not
                        # validated against the direction titles, since a
                        # direction label is not an invented fact the way
                        # a name or affiliation would be.
                        "research_direction": {"type": "string"},
                    }
                ),
            },
            # R14-6: the published exemplar groups research_contacts under
            # their research direction, each group carrying one shared
            # rationale paragraph and up to two example hypotheses --
            # richer than the flat per-contact research_direction tag
            # above (MO-7). A separate, additive array rather than
            # nesting contacts under it: the model already emits flat
            # contacts tagged with research_direction, and the renderer
            # (report_markdown_overview.py) matches a group to its
            # contacts by that same free-text tag, so an old report (or
            # one whose response never populates this field) still
            # renders MO-7's flat shape unchanged. Bounded to the same 5
            # as research_contacts, since there cannot usefully be more
            # groups than there are contacts to put in them.
            "research_contact_groups": {
                "type": "array",
                "maxItems": 5,
                "items": obj(
                    {
                        "research_direction": {
                            "type": "string",
                            "description": (
                                "Must exactly match one of the"
                                " research_direction values used in"
                                " research_contacts above -- this is"
                                " how a group's contacts are found."
                            ),
                        },
                        "rationale": {
                            "type": "string",
                            "description": (
                                "One shared paragraph explaining why"
                                " this group of contacts, together, is"
                                " well suited to lead work on this"
                                " research direction -- distinct from"
                                " each contact's own individual"
                                " justification."
                            ),
                        },
                        "example_hypothesis_indices": {
                            "type": "array",
                            "maxItems": 2,
                            "items": {"type": "integer"},
                            "description": (
                                "Up to two 1-based positions from the"
                                " numbered hypothesis list above whose"
                                " ideas exemplify this research"
                                " direction. Refer to hypotheses by"
                                " number only -- never invent or echo a"
                                " title."
                            ),
                        },
                    },
                    optional=("example_hypothesis_indices",),
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
            # R12-10: the published report's top-level "Open Questions"
            # list and its "Clear Patterns:"/"Unexpected Patterns:" pair.
            # Google's second exemplar (research-overview.md, R14-1)
            # lists "Open questions" beside the research-directions
            # summary in this same synthesis document, which is why
            # these land here rather than on meta_review.
            "open_questions": {
                **str_array(
                    "The most important unanswered questions this"
                    " synthesis leaves open, each a specific testable"
                    " question -- not a restatement of the research"
                    " goal."
                ),
                "maxItems": RESEARCH_OVERVIEW_MAX_OPEN_QUESTIONS,
            },
            "clear_patterns": {
                **str_array(
                    "Patterns that recur clearly across the synthesized"
                    " hypotheses and evidence."
                ),
                "maxItems": RESEARCH_OVERVIEW_MAX_PATTERNS,
            },
            "unexpected_patterns": {
                **str_array(
                    "Patterns or connections that were not anticipated"
                    " going in, surfaced only by synthesizing across the"
                    " hypotheses and evidence together."
                ),
                "maxItems": RESEARCH_OVERVIEW_MAX_PATTERNS,
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

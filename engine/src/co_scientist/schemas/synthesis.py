"""JSON schemas for the research-overview stage.

These schemas are used with response_format of type json_schema to
constrain LLM outputs during final research-overview synthesis. The
evolution schema moved to ``schemas/evolution.py`` at this module's size
cap and is re-exported here for existing importers.
"""

from typing import Any, Final

from co_scientist.schemas.builders import obj, str_array
from co_scientist.schemas.evolution import (
    EVOLUTION_SCHEMA as EVOLUTION_SCHEMA,
)

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

# How many main research directions the overview asks for, and the hard
# bound on how many it will keep. They are now the same number: the
# published cf-PICI overview enumerates six and the ask is six.
#
# Four, before, because the draft call had to write every direction's
# body itself and could not afford six. Production express run 6760ce63
# (2026-09-06) billed its research_overview node 26,263 completion
# tokens over two calls (draft + accuracy review), and the draft's
# surviving answer re-tokenizes to ~14.6k, ~15.9k billed once calibrated
# against a fully-rendered single-call node from the same run
# (meta_review: 5,071 billed against 4,654 reconstructed, a 1.09 ratio).
# At ~2.0k billed per direction, three directions were ~6.0k of that and
# everything else ~9.9k, so six directions plus their example_idea
# fields would need ~13.9k and a ~23.8k single call -- the whole 24000
# ceiling with nothing left for the chain of thought that shares it, and
# 643-881s of generation at this deployment's measured 27-37 tokens per
# second against a 600s per-call ceiling. The wall clock, not the budget,
# is what said no.
#
# So the ask is six and the body is written elsewhere: the draft names
# the six and argues each in a paragraph, and one call per direction
# develops it to the exemplar's depth
# (``agents/meta_review/research_overview_direction_calls``), exactly as
# the Knowledge Base is outlined once and written a theme at a time.
RESEARCH_OVERVIEW_TARGET_DIRECTIONS: Final = 6
RESEARCH_OVERVIEW_MAX_DIRECTIONS: Final = 6

# R12-10: bounds on open_questions/clear_patterns/unexpected_patterns
# below, mirroring the published exemplar's "Top 10 Open Questions" list
# and its two shorter pattern lists. Capped for the same reason as the
# sub-topic bounds above -- this is the terminal synthesis call and its
# output must not scale unboundedly with what the run reviewed.
RESEARCH_OVERVIEW_MAX_OPEN_QUESTIONS: Final = 10
RESEARCH_OVERVIEW_MAX_PATTERNS: Final = 5

# Task B: bound on unexpected_research_directions below, mirroring the
# published MASH exemplar's own "Unexpected Research Directions" block
# (docs/CORPUS-EXTRACTION.md, .../mash-liver-fibrosis-reversal-
# therapeutic-hypothesis.md:418) -- three named bullets. Capped for the
# same reason as RESEARCH_OVERVIEW_MAX_PATTERNS above: this is the
# terminal synthesis call, and RESEARCH_OVERVIEW_MAX_TOKENS already sits
# at the escalation ladder's own ceiling (see AGENTS.md), so a new field
# here must not scale the response further.
RESEARCH_OVERVIEW_MAX_UNEXPECTED_DIRECTIONS: Final = 3

# F8: bounds on the deep knowledge-base synthesis in this package's
# sibling module, taken from the published MASH exemplar's own shape -- 43 named
# subject headings under 8 themes. 8 x 8 is the smallest product that
# covers it without inviting more themes than one call each can be
# written for (KNOWLEDGE_BASE_THEME_MAX_TOKENS). These are ceilings, not the
# target: the word bands and the 40-50 section total the prompt actually
# asks for live in ``schemas.knowledge_base``, sized from the exemplar's
# own measured distribution, and land near 9,900 words -- the product
# here only has to leave room above that, not describe it.
KNOWLEDGE_BASE_MAX_THEMES: Final = 8
KNOWLEDGE_BASE_MAX_SECTIONS: Final = 8

_RESEARCH_DIRECTION_BODY: Final[dict[str, Any]] = {
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
        "maxItems": (RESEARCH_OVERVIEW_MAX_SUB_TOPICS),
        "items": obj(
            {
                "title": {"type": "string"},
                "why": {"type": "string"},
                "what": {"type": "string"},
                # F7: the exemplar's own third
                # block, between "Why research
                # this topic?" and its
                # "Specific questions" list.
                # Distinct from "what": that
                # states the topic, this works
                # one concrete way to attack
                # it. Authored from the
                # sub-topic's own content --
                # never a hypothesis quoted
                # back, which would scale the
                # response with the pool.
                "example_idea": {
                    "type": "string",
                    "description": (
                        "One concrete worked"
                        " example of how this"
                        " sub-topic would"
                        " actually be"
                        " investigated:"
                        " the approach, what"
                        " it measures, and"
                        " what the result"
                        " would show."
                    ),
                },
                "specific_questions": {
                    **str_array(),
                    "maxItems": (RESEARCH_OVERVIEW_MAX_SUB_TOPIC_QUESTIONS),
                },
            }
        ),
    },
}
"""Everything a direction carries below its own title.

Named once and shared by the two schemas that need it: the overview
draft's ``research_directions`` items below, and
``RESEARCH_OVERVIEW_DIRECTION_SCHEMA``, the one-direction schema the
writing wave answers in. The draft names the directions and the wave
develops them (see ``agents/meta_review/research_overview_direction_calls``
for why it is two calls), so the two schemas describe the same object
from opposite ends and must not drift apart.
"""

RESEARCH_OVERVIEW_DIRECTION_SCHEMA: dict[str, Any] = {
    "name": "research_overview_direction",
    "schema": obj(dict(_RESEARCH_DIRECTION_BODY)),
}
"""One drafted direction, developed to the published exemplar's depth.

Carries no ``title``: the draft already chose it, and re-emitting it
would let a writing call rename a direction the overview's own contacts
and groups cross-reference by title.
"""

RESEARCH_OVERVIEW_SCHEMA: dict[str, Any] = {
    "name": "research_overview",
    "schema": obj(
        {
            "overview": obj(
                {
                    "summary": {"type": "string"},
                    "research_directions": {
                        "type": "array",
                        # F5: bounded at the published exemplar's own six.
                        # Unbounded before, which is how a prompt naming
                        # no count settled on three -- the ask now names
                        # RESEARCH_OVERVIEW_TARGET_DIRECTIONS and this
                        # caps what an over-producing response can cost.
                        # Enforced again in
                        # research_overview_directions.py, since
                        # json_object mode does not apply maxItems
                        # server-side.
                        "maxItems": RESEARCH_OVERVIEW_MAX_DIRECTIONS,
                        "items": obj(
                            {
                                "title": {"type": "string"},
                                **_RESEARCH_DIRECTION_BODY,
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
            # (report/markdown/overview.py) matches a group to its
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
            # Task B: the published MASH exemplar's own "Unexpected
            # Research Directions" block -- genuinely novel strategic
            # directions worth pursuing, surfaced by synthesis. Distinct
            # from research_directions above (the main directions,
            # expected and expanded) and from unexpected_patterns above
            # (a pattern observed across the ideas, not a direction worth
            # pursuing) -- both kept, neither merged nor repurposed.
            "unexpected_research_directions": {
                "type": "array",
                "maxItems": RESEARCH_OVERVIEW_MAX_UNEXPECTED_DIRECTIONS,
                "description": (
                    "Up to 3 genuinely novel research directions worth"
                    " pursuing that were not anticipated going in and are"
                    " not among the main research_directions above --"
                    " surfaced only by synthesizing across the hypotheses"
                    " and evidence together. Return an empty list rather"
                    " than restating a main direction or stretching an"
                    " expected one to sound unexpected."
                ),
                "items": obj(
                    {
                        "title": {
                            "type": "string",
                            "description": (
                                "short name for the novel direction"
                            ),
                        },
                        "description": {
                            "type": "string",
                            "description": (
                                "one prose paragraph explaining the"
                                " direction and why it is worth pursuing"
                            ),
                        },
                    }
                ),
            },
        }
    ),
}

# What an interim (non-terminal) firing asks for. FIX-6: the periodic
# branch writes only the block ``interim_overview.build_interim_overview``
# renders into the next generate cycle's prompt context -- direction
# titles and open questions -- and discards the rest, so the schema names
# exactly those two fields rather than the terminal document's ten. The
# bounds match ``build_interim_overview``'s own render caps exactly: this
# firing is never asked to write a title or question the next cycle will
# not see.
RESEARCH_OVERVIEW_INTERIM_MAX_DIRECTIONS: Final = 4
RESEARCH_OVERVIEW_INTERIM_MAX_QUESTIONS: Final = 5

RESEARCH_OVERVIEW_INTERIM_SCHEMA: dict[str, Any] = {
    "name": "research_overview_interim",
    "schema": obj(
        {
            "overview": obj(
                {
                    "research_directions": {
                        "type": "array",
                        "maxItems": RESEARCH_OVERVIEW_INTERIM_MAX_DIRECTIONS,
                        "items": obj({"title": {"type": "string"}}),
                    },
                }
            ),
            "open_questions": {
                **str_array(
                    "The most important unanswered questions this run's"
                    " progress so far leaves open, each a specific"
                    " testable question -- not a restatement of the"
                    " research goal."
                ),
                "maxItems": RESEARCH_OVERVIEW_INTERIM_MAX_QUESTIONS,
            },
        }
    ),
}
"""Nested the same way ``RESEARCH_OVERVIEW_SCHEMA`` is (``overview.
research_directions``, top-level ``open_questions``) so
``build_interim_overview`` parses either response identically -- an
interim firing is just a response with everything else stripped out of
the ask.
"""

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

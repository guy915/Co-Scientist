"""JSON schemas for the deep knowledge-base synthesis calls (F8).

Two schemas, not one, because the section is outlined once and then
written a theme at a time: a single call asking for the whole ~20,000-token
span cannot be served inside the 600s per-call ceiling, whatever budget it
carries (see ``constants.tokens.KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS`` for the
measurement). The word bands below are shared by both -- the outline reads
them to size its section count, the theme writer to write against them.

Split from ``synthesis.py`` on that module's size cap; the bounds it
shares with the research-overview schema stay there and are imported
here, so the two halves of one node's output cannot be sized apart.
"""

from typing import Any, Final

from co_scientist.schemas.builders import obj, str_array
from co_scientist.schemas.synthesis import (
    KNOWLEDGE_BASE_MAX_SECTIONS,
    KNOWLEDGE_BASE_MAX_THEMES,
)

# Measured targets, stated here so the prompt template and the schema
# description cannot drift apart -- under the json_object downgrade both
# ride with the same request, and a band written in one and not the other
# is two instructions disagreeing.
#
# Section-by-section measurement of the published exemplar (2026-09-07):
# its 43 subject sections average 218 words, median 196, with eleven above
# 250 and a 505-word top. Production run d1273490 wrote 38 sections
# averaging 164, median 162, and *none* above 213 -- the entire
# distribution pinned inside the "150-250" the prompt then named, hugging
# its floor. A stated band is a floor rather than a target, so the floor
# is now the exemplar's own mean and the right tail is asked for
# explicitly instead of being left to the model's own sense of emphasis.
KNOWLEDGE_BASE_SECTION_WORDS: Final = (200, 300)
"""Word band for an ordinary subsection."""

KNOWLEDGE_BASE_PRINCIPAL_SECTION_WORDS: Final = (350, 500)
"""Word band for a theme's two or three principal subjects.

The exemplar's own right tail: without naming it, every section comes
back the same length, which is the flat distribution measured above.
"""

KNOWLEDGE_BASE_TARGET_SECTIONS: Final = (40, 50)
"""Subject sections the finished Knowledge Base aims for, in total.

The exemplar carries 43. Expressed as a range the evidence has to
support rather than a hard floor: a thin corpus padded out to a count
is worth less than fewer subjects written properly, and ``minItems``
would turn a short theme into a validation failure that drops the whole
call to the flat topics.
"""

_ORDINARY: Final = "{}-{}".format(*KNOWLEDGE_BASE_SECTION_WORDS)
_PRINCIPAL: Final = "{}-{}".format(*KNOWLEDGE_BASE_PRINCIPAL_SECTION_WORDS)

_EVIDENCE_IDS = (
    "The evidence_ids this subsection is synthesized from. Listed ids"
    " only; a subsection citing none is dropped."
)

_HEADING = "Name of this subsection's specific subject."

_THEME_TITLE = (
    "Name of the subject area, as a heading (e.g. 'Extracellular Matrix"
    " Architecture And Biomechanical Barriers')."
)

# Knowledge-base outline schema
# Shapes the "research_overview_knowledge_base_outline" prompt output: the
# whole Knowledge Base's structure -- themes, the subsections under each,
# and the evidence every subsection is drawn from -- and none of its prose.
#
# The structure is decided once, here, because the prose is then written by
# several independent calls that must not overlap or renumber each other
# (agents/meta_review/research_overview_knowledge_base_calls). This answer
# is small by construction: eight themes of eight headings is under 2,000
# tokens however large the corpus offered to the prompt, since nothing here
# echoes the corpus back -- a section names its sources by the opaque
# evidence_id the prompt assigned them, the trap proximity clustering hit
# (see proximity_dedup._match_cluster_member).
KNOWLEDGE_BASE_OUTLINE_SCHEMA: dict[str, Any] = {
    "name": "knowledge_base_outline",
    "schema": obj(
        {
            "themes": {
                "type": "array",
                "maxItems": KNOWLEDGE_BASE_MAX_THEMES,
                "description": (
                    "The subject areas this run's evidence covers, in"
                    " reading order, each holding its own named"
                    " subsections."
                ),
                "items": obj(
                    {
                        "title": {
                            "type": "string",
                            "description": _THEME_TITLE,
                        },
                        "sections": {
                            "type": "array",
                            "maxItems": KNOWLEDGE_BASE_MAX_SECTIONS,
                            "items": obj(
                                {
                                    "heading": {
                                        "type": "string",
                                        "description": _HEADING,
                                    },
                                    "evidence_ids": str_array(_EVIDENCE_IDS),
                                }
                            ),
                        },
                    }
                ),
            }
        }
    ),
}

# Knowledge-base theme schema
# Shapes the "research_overview_knowledge_base_theme" prompt output: the
# dense prose for the subsections one theme of the outline above names.
#
# One theme per call, because the whole Knowledge Base cannot be written in
# one: the published span is ~20,000 tokens and the 600s per-call ceiling
# buys 16,000-22,000 generated tokens at the throughput production measured
# (see KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS). "detail" carries no maxLength for
# the same reason it never did: the shim that trims an over-long string
# under the json_object downgrade cuts at a word boundary, and dense prose
# is the one field where that trim would be visible to a reader.
KNOWLEDGE_BASE_THEME_SCHEMA: dict[str, Any] = {
    "name": "knowledge_base_theme",
    "schema": obj(
        {
            "sections": {
                "type": "array",
                "maxItems": KNOWLEDGE_BASE_MAX_SECTIONS,
                "description": (
                    "This theme's subsections, in the order the outline"
                    " lists them."
                ),
                "items": obj(
                    {
                        "heading": {
                            "type": "string",
                            "description": _HEADING,
                        },
                        "detail": {
                            "type": "string",
                            "description": (
                                "Dense encyclopedic prose:"
                                f" {_ORDINARY} words, or"
                                f" {_PRINCIPAL} for a theme's two or"
                                " three principal subjects."
                                " Name every entity the evidence gives"
                                " for this subject and every parameter,"
                                " effect size, threshold and unit it"
                                " states. No citation markers and no"
                                " bullet lists."
                            ),
                        },
                        "evidence_ids": str_array(_EVIDENCE_IDS),
                    }
                ),
            }
        }
    ),
}

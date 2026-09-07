"""JSON schema for the deep knowledge-base synthesis call (F8).

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

# Knowledge-base synthesis schema
# Shapes the "research_overview_knowledge_base" prompt output, consumed by
# agents/meta_review/research_overview_knowledge_base.py. A second, deeper
# pass over the same evidence corpus the overview call already saw: the
# published Knowledge Base is 9,702 words of themed encyclopedic prose (43
# named subject headings under 8 themes), which does not fit beside an
# overview draft already spending ~15.9k of its own 24000-token ceiling.
#
# Nothing here echoes the corpus back. A section names its sources by the
# opaque evidence_id the prompt assigned them, exactly as the overview's own
# knowledge_base field does, so response length scales with the depth asked
# for and not with the size of the pool offered (the trap proximity
# clustering hit; see proximity_dedup._match_cluster_member). For the same
# reason "detail" carries no maxLength: the shim that trims an over-long
# string under the json_object downgrade cuts at a word boundary, and dense
# prose is the one field where that trim would be visible to a reader.
KNOWLEDGE_BASE_SCHEMA: dict[str, Any] = {
    "name": "knowledge_base_synthesis",
    "schema": obj(
        {
            "themes": {
                "type": "array",
                "maxItems": KNOWLEDGE_BASE_MAX_THEMES,
                "description": (
                    "The subject areas this run's evidence covers, each"
                    " holding its own named subsections."
                ),
                "items": obj(
                    {
                        "title": {
                            "type": "string",
                            "description": (
                                "Name of the subject area, as a heading"
                                " (e.g. 'Extracellular Matrix"
                                " Architecture And Biomechanical"
                                " Barriers')."
                            ),
                        },
                        "sections": {
                            "type": "array",
                            "maxItems": KNOWLEDGE_BASE_MAX_SECTIONS,
                            "items": obj(
                                {
                                    "heading": {
                                        "type": "string",
                                        "description": (
                                            "Name of this subsection's"
                                            " specific subject."
                                        ),
                                    },
                                    "detail": {
                                        "type": "string",
                                        "description": (
                                            "Dense encyclopedic prose:"
                                            f" {_ORDINARY} words, or"
                                            f" {_PRINCIPAL} for a"
                                            " theme's two or three"
                                            " principal subjects."
                                            " Name every entity the"
                                            " evidence gives for this"
                                            " subject and every"
                                            " parameter, effect size,"
                                            " threshold and unit it"
                                            " states. No citation"
                                            " markers and no bullet"
                                            " lists."
                                        ),
                                    },
                                    "evidence_ids": str_array(
                                        "The evidence_ids this subsection"
                                        " is synthesized from. Listed"
                                        " ids only; a subsection citing"
                                        " none is dropped."
                                    ),
                                }
                            ),
                        },
                    }
                ),
            }
        }
    ),
}

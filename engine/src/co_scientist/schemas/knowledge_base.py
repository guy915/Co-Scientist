"""JSON schema for the deep knowledge-base synthesis call (F8).

Split from ``synthesis.py`` on that module's size cap; the bounds it
shares with the research-overview schema stay there and are imported
here, so the two halves of one node's output cannot be sized apart.
"""

from typing import Any

from co_scientist.schemas.builders import obj, str_array
from co_scientist.schemas.synthesis import (
    KNOWLEDGE_BASE_MAX_SECTIONS,
    KNOWLEDGE_BASE_MAX_THEMES,
)

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
                                            " 2-4 paragraphs, 150-250"
                                            " words, naming entities,"
                                            " mechanisms, parameters and"
                                            " effect sizes. No citation"
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

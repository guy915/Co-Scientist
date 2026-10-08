from typing import Any

from co_scientist.core.json_schema import obj, str_array
from co_scientist.science.schemas.review import (
    FULL_REVIEW_SCHEMA,
    REFLECTION_SCHEMA,
    SIMULATION_REVIEW_SCHEMA,
)

FINALIST_REVIEW_MAX_QUERIES = 4

# Nested bodies are the standalone review schemas unchanged, so each part is
# stored under the key and shape its gates and renderers already read.
_OBSERVATION_BODY: dict[str, Any] = obj(
    {
        name: spec
        for name, spec in REFLECTION_SCHEMA["schema"]["properties"].items()
        if name != "hypothesis_text"
    },
    optional=("positive_observations",),
)

FINALIST_REVIEW_SCHEMA: dict[str, Any] = {
    "name": "finalist_review",
    "schema": obj(
        {
            "observation": _OBSERVATION_BODY,
            "full_review": FULL_REVIEW_SCHEMA["schema"],
            "simulation": SIMULATION_REVIEW_SCHEMA["schema"],
            "verification_queries": {
                **str_array(
                    "Keyword search queries, 3-8 established terms each and no"
                    " numbers, for the papers that would confirm or refute the"
                    " assumptions this review found least certain."
                ),
                "maxItems": FINALIST_REVIEW_MAX_QUERIES,
            },
        },
        optional=("observation",),
    ),
}

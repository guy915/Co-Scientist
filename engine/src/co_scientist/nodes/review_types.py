"""The six Reflection review types and their prompt/schema registry (SSR §4).

Google's Reflection agent applies six kinds of review. This module names them
as a single enum and maps each to the prompt template and structured-output
schema that implement it, so the set is explicit and dispatchable rather than
implied by scattered nodes:

- ``INITIAL`` -- a quick, tool-free screen (``review`` / ``review_batch``).
- ``FULL`` -- an in-depth correctness/quality/novelty + assumptions review
  (``full_review``).
- ``DEEP_VERIFICATION`` -- decompose into assumptions and probe them
  (``deep_verification``).
- ``OBSERVATION`` -- does the hypothesis explain literature observations
  (``reflection_observations``).
- ``SIMULATION`` -- step-through mental simulation of the mechanism
  (``simulation_review``).
- ``RECURRENT`` -- synthesis of recurring cross-review patterns fed back into
  later reviews (``meta_review``).
"""

from __future__ import annotations

import enum
from typing import Any

from co_scientist.schemas import get_schema_for_prompt


class ReviewType(str, enum.Enum):
    """The six review types the Reflection agent can apply (SSR §4)."""

    INITIAL = "initial"
    FULL = "full"
    DEEP_VERIFICATION = "deep_verification"
    OBSERVATION = "observation"
    SIMULATION = "simulation"
    RECURRENT = "recurrent"


# Prompt-template stem backing each review type (get_schema_for_prompt resolves
# each stem to its structured-output schema).
_PROMPT_BY_TYPE: dict[ReviewType, str] = {
    ReviewType.INITIAL: "review",
    ReviewType.FULL: "full_review",
    ReviewType.DEEP_VERIFICATION: "deep_verification",
    ReviewType.OBSERVATION: "reflection_observations",
    ReviewType.SIMULATION: "simulation_review",
    ReviewType.RECURRENT: "meta_review",
}


def prompt_name_for(review_type: ReviewType) -> str:
    """Return the prompt-template stem implementing a review type."""
    return _PROMPT_BY_TYPE[review_type]


def schema_for(review_type: ReviewType) -> dict[str, Any] | None:
    """Return the structured-output schema for a review type, if any."""
    return get_schema_for_prompt(_PROMPT_BY_TYPE[review_type])

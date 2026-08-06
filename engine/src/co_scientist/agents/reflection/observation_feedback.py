"""Hypothesis feedback seam for the observation review (audit K8).

The paper's observation review both critiques and confirms: "positive
observations are summarized and appended to the hypothesis" (SSR
Section 3.3.2). This module is the one place that folds an
observation-review result back onto its hypothesis -- the critique and
the confirmed strengths into ``reflection_notes`` (the accumulated-
feedback field the ranking prompts read), ahead of the parseable
"Classification:" suffix, plus the structured verdict under
``enrichments["observation"]``. The hypothesis text itself is never
rewritten.
"""

from typing import Any

from co_scientist.models import Hypothesis
from co_scientist.schemas.review import (
    REFLECTION_MAX_POSITIVE_OBSERVATIONS,
)

_STRENGTHS_HEADER = "Confirmed strengths (positive observations):"


def clean_positive_observations(raw: Any) -> list[str]:
    """Normalize a review's positive observations, bounded and deduped.

    Args:
        raw: The raw ``positive_observations`` value from a review
            payload (may be absent, malformed, or hold blank entries).

    Returns:
        Cleaned strengths, at most REFLECTION_MAX_POSITIVE_OBSERVATIONS.
    """
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:REFLECTION_MAX_POSITIVE_OBSERVATIONS]


def _format_confirmed_strengths(positives: list[str]) -> str:
    """Render confirmed strengths as a bulleted note block."""
    if not positives:
        return ""
    lines = [_STRENGTHS_HEADER]
    lines.extend(f"- {item}" for item in positives)
    return "\n".join(lines)


def apply_observation_result(
    hypothesis: Hypothesis, result: dict[str, Any] | None
) -> None:
    """Fold one observation-review result onto its hypothesis.

    Sets reflection_notes to the reasoning, then the confirmed strengths
    the review recorded (K8), then the "Classification: <value>" suffix
    agents/ranking/ranking_prompt.py parses back out of the notes;
    stores the structured verdict under enrichments["observation"],
    which carries the strengths only when there are any, keeping
    no-finding records byte-identical to the pre-K8 shape.

    Args:
        hypothesis: Hypothesis the observation review judged (mutated).
        result: Observation-review payload, or None when the analysis
            failed; the failure note keeps the classification suffix the
            ranking parser relies on.
    """
    if result is None:
        hypothesis.reflection_notes = (
            "Analysis failed\n\nClassification: neutral"
        )
        return

    classification = str(result.get("classification", "neutral"))
    reasoning = str(result.get("reasoning", ""))
    positives = clean_positive_observations(result.get("positive_observations"))

    notes = reasoning
    strengths = _format_confirmed_strengths(positives)
    if strengths:
        notes = f"{notes}\n\n{strengths}" if notes else strengths
    hypothesis.reflection_notes = f"{notes}\n\nClassification: {classification}"

    observation: dict[str, Any] = {
        "classification": classification,
        "reasoning": reasoning,
    }
    if positives:
        observation["positive_observations"] = positives
    hypothesis.enrichments["observation"] = observation


def store_indra_enrichment(
    hypothesis: Hypothesis, result: dict[str, Any]
) -> None:
    """Merge INDRA evidence items from an observation result, if any.

    Knowledge-graph evidence rides in enrichments["indra_evidence"]
    (yaml-driven, only present for biomedical configs), separate from
    the observation verdict itself.
    """
    enrichment_items = result.get("indra_enrichment_items", [])
    if enrichment_items:
        hypothesis.enrichments["indra_evidence"] = enrichment_items

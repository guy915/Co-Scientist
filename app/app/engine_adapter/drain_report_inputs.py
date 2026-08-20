"""What the drain hands the report about how the run went.

Three of the report's fields are not results but conditions: the sections
the engine could not write, the retrieval it never got to attempt, and
the tallies from the safety and grounding gates. They share a property
that keeps them together here -- each one explains something a reader
would otherwise mis-read as ordinary. A blank section reads as missing
data, an idea with no citation reads as an idea nobody bothered to check,
and a run that reached no source at all reads as a run that never needed
one.

Split out of ``drain.py`` for the file-length ceiling, and the seam is a
real one: nothing here touches the store, and the drain's own job is
writing rows.
"""

from __future__ import annotations

from typing import Any


def degraded_sections(final_state: dict[str, Any]) -> list[str]:
    """Return the engine nodes whose output degraded to a fallback.

    The engine records every enhancement node served a placeholder
    fallback instead of parseable LLM output
    (``co_scientist.progress.record_schema_degradation``); the report
    carries the list so a section left blank by a degradation can say so
    instead of showing silence.
    """
    return [str(name) for name in final_state.get("degraded_nodes") or []]


def retrieval_degradation(
    final_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Return what the run could not search, when it could not search.

    A different fact from ``degraded_sections``: that one explains a
    section left blank by output the model could not produce, while this
    one names retrieval the run never attempted. Nothing in the report's
    prose can reveal it, which is exactly why it has to be carried.
    """
    degradation = final_state.get("retrieval_degradation")
    return degradation if isinstance(degradation, dict) else None


def grounding_counts(
    grounding_result: Any, grounding_candidates: list[dict[str, Any]]
) -> dict[str, int]:
    """Tally the pre-ranking evidence gate's outcome for the report.

    "assessed", not "grounded": ``reason_by_id`` carries a gate reason for
    every hypothesis put through the gate, blocked ones included, so
    publishing it as "grounded" made a run where both candidates were
    blocked read "grounded=2 blocked=2" -- four hypotheses' worth of
    outcome for two hypotheses, with the blocked ones counted twice.
    """
    assessed = len(grounding_result.reason_by_id)
    return {
        "assessed": assessed,
        "grounded": assessed - grounding_result.blocked_count,
        "blocked": grounding_result.blocked_count,
        "eligible": (
            len(grounding_candidates) - grounding_result.blocked_count
        ),
    }


def safety_counts(screening_result: Any) -> dict[str, int]:
    """Tally the per-hypothesis safety screen's outcome for the report."""
    return {
        "screened": screening_result.screened_count,
        "blocked": screening_result.blocked_count,
        "eligible": (
            screening_result.screened_count - screening_result.blocked_count
        ),
    }

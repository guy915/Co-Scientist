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


def skills_used(final_state: dict[str, Any]) -> dict[str, int]:
    """Return the science skills the run invoked, by name and count.

    Carried because the skills query third-party databases whose terms
    are separate from the bundle's licence, and most of those sources
    require that the user be notified of them. The harness writes that
    notice into the workspace the skill runs in, which is deleted; the
    report is the only surface that reaches a person, and it can only
    name the sources the run actually used if the run counted them.
    Empty on every run that invoked no skill, which is every run without
    ``COSCIENTIST_SKILLS_DIR``.
    """
    metrics = final_state.get("metrics")
    used = getattr(metrics, "skills_used", None)
    if used is None and isinstance(metrics, dict):
        used = metrics.get("skills_used")
    if not isinstance(used, dict):
        return {}
    return {str(name): int(count) for name, count in used.items()}


def stratification_attributes(
    final_state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the Supervisor's synthesized 1-5 stratification attributes.

    A read of guidance the Supervisor already synthesizes and
    ``drain_supervisor_plan.py`` already persists into the
    ``supervisor_plan`` table (``supervisor_guidance.config_synthesis.
    attributes``, up to three ``{name, rubric}`` axes) and
    ``prompts/review.py`` already injects into every reviewer prompt --
    not a new computation, just handing an existing one to the report
    (R12-17). Display only: the report never uses this to gate, filter,
    rank, or disqualify a hypothesis. Degrades to an empty list, never an
    error, on an old checkpoint predating this field or a malformed one.
    """
    guidance = final_state.get("supervisor_guidance")
    config = (
        guidance.get("config_synthesis") if isinstance(guidance, dict) else None
    )
    attributes = config.get("attributes") if isinstance(config, dict) else None
    if not isinstance(attributes, list):
        return []
    return [attr for attr in attributes if isinstance(attr, dict)]


def critical_criteria(final_state: dict[str, Any]) -> list[Any]:
    """Return the Supervisor's synthesized per-goal evaluation criteria.

    A read of guidance the Supervisor already synthesizes
    (``supervisor_guidance.workflow_plan.review_phase.critical_criteria``)
    and ``prompts/review.py`` already injects into every reviewer prompt
    as "Critical Criteria to Emphasize" -- not a new computation, just
    handing an existing one to the report (R12-18). Display only: the
    report never uses this to gate, filter, rank, or disqualify a
    hypothesis.

    Two shapes pass through unfiltered (R12-23): the legacy bare
    criterion-name string, and the richer ``{name, questions}`` object
    the Supervisor now synthesizes to mirror the published Review
    Summary's rubric (docs/CORPUS-EXTRACTION.md, line 2929) -- the report
    renderers (``report_markdown_supervisor.py``) handle both. Degrades
    to an empty list, never an error, on an old checkpoint predating this
    field or a malformed one; a list entry that is neither a string nor a
    dict is dropped rather than passed through.
    """
    guidance = final_state.get("supervisor_guidance")
    plan = guidance.get("workflow_plan") if isinstance(guidance, dict) else None
    review_phase = plan.get("review_phase") if isinstance(plan, dict) else None
    criteria = (
        review_phase.get("critical_criteria")
        if isinstance(review_phase, dict)
        else None
    )
    if not isinstance(criteria, list):
        return []
    return [item for item in criteria if isinstance(item, (str, dict))]


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

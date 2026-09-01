"""Renders the Supervisor's synthesized guidance sections.

Two fields the Supervisor already synthesizes per run and ``prompts/
review.py`` already injects into every reviewer prompt, but that nothing
rendered to the reader until R12-17 (stratification attributes) and
R12-18 (evaluation criteria). Kept together, in their own module, because
they share the same trap: each reuses an English word Google's published
documents also use for a *different*, user-authored field --
``config_synthesis.attributes`` vs. the run's plain-string setup
attributes, and ``workflow_plan.review_phase.critical_criteria`` vs. the
run's plain-string setup criteria (both rendered under "Research Goal
Details" in ``report_markdown_header.py``). Reusing either heading here
would present the model's synthesis as the user's own setup, so both
renderers below pick a heading distinct from its user-authored namesake.

Split out of ``report_markdown`` to keep that module within the size cap;
both names are re-exported so its namespace keeps resolving.

Display only, in both cases: never used to gate, filter, rank, or
disqualify a hypothesis.
"""

from __future__ import annotations

from typing import Any


def _render_stratification_attributes_markdown(
    attributes: list[dict[str, Any]] | None,
) -> list[str]:
    """Render the Supervisor's synthesized 1-5 stratification attributes.

    R12-17: the Supervisor already synthesizes up to three named rating
    scales (``config_synthesis.attributes``, each a ``{name, rubric}``
    pair) and ``prompts/review.py`` already injects them into every
    reviewer prompt as "Stratification attributes (score each 1-5)" --
    this only displays what was already computed.

    Deliberately not titled "Attributes" -- that heading already names the
    run's user-authored, plain-string setup attributes rendered under
    "Research Goal Details" (``report_markdown_header.py``). Google's own
    published documents use the same word for both a bare list and a
    name-plus-rubric section; reusing it here would conflate the two.
    """
    items = [
        attr
        for attr in attributes or []
        if isinstance(attr, dict) and str(attr.get("name") or "").strip()
    ]
    if not items:
        return []
    lines = ["## Stratification Attributes\n"]
    for attr in items:
        name = str(attr["name"]).strip()
        rubric = str(attr.get("rubric") or "").strip()
        lines.append(f"- **{name}:** {rubric}" if rubric else f"- **{name}**")
    lines.append("")
    return lines


def _render_evaluation_criteria_markdown(
    critical_criteria: list[str] | None,
) -> list[str]:
    """Render the Supervisor's synthesized per-goal evaluation criteria.

    R12-18: the Supervisor already synthesizes goal-specific criteria
    reviewers should emphasize (``workflow_plan.review_phase.
    critical_criteria``, a list of names like "Kinetic Feasibility and
    Experimental Readouts") and ``prompts/review.py`` already injects
    them into every reviewer prompt as "Critical Criteria to Emphasize"
    -- this only displays what was already computed; the review schema's
    fixed score scale is untouched.

    Titled to match Google's own published section name ("Evaluation
    Criteria"), and deliberately not "Criteria" -- that heading already
    names the run's user-authored, plain-string criteria rendered under
    "Research Goal Details" (``report_markdown_header.py``).
    """
    items = [item.strip() for item in critical_criteria or [] if item.strip()]
    if not items:
        return []
    lines = ["## Evaluation Criteria\n"]
    lines.extend(f"- {item}" for item in items)
    lines.append("")
    return lines

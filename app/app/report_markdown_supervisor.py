"""Renders the Supervisor's synthesized guidance sections.

Fields the Supervisor already synthesizes per run and ``prompts/
review.py`` already injects into every reviewer prompt, but that nothing
rendered to the reader until R12-17 (stratification attributes), R12-18
(evaluation criteria), and R12-23 (the review rubric itself). Kept
together, in their own module, because they share the same trap: each
reuses an English word Google's published documents also use for a
*different*, user-authored field -- ``config_synthesis.attributes`` vs.
the run's plain-string setup attributes, and ``workflow_plan.review_phase.
critical_criteria`` vs. the run's plain-string setup criteria (both
rendered under "Research Goal Details" in ``report_markdown_header.py``).
Reusing either heading here would present the model's synthesis as the
user's own setup, so every renderer below picks a heading distinct from
its user-authored namesake.

``critical_criteria`` backs two sections here, both R12-18's "Evaluation
Criteria" (a flat name list, matching the published plan's own section 2)
and R12-23's "Review Summary" (the numbered rubric with each criterion's
named reviewer questions, matching the published document's later,
separate section of that name) -- two genuinely different published
sections that happen to derive from the same synthesized field. As of
R12-23 that field's entries carry two shapes: the legacy bare criterion-
name string (a run persisted before this change) and the richer
``{name, questions}`` object the Supervisor now synthesizes. Production's
json_object mode does not enforce the schema, so a live run can answer
with either shape too -- every renderer below handles both, and degrades
a malformed field (not a list, or an unnamed entry) to rendering nothing.

Split out of ``report_markdown`` to keep that module within the size cap;
every name is re-exported so its namespace keeps resolving.

Display only, in every case: never used to gate, filter, rank, or
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


def _critical_criterion_name(criterion: Any) -> str:
    """Extract a critical criterion's display name, or "" when unusable.

    Shared by both critical_criteria renderers below: a run's entries are
    either the legacy bare name string (pre-R12-23) or the richer
    ``{name, questions}`` object the Supervisor now synthesizes. Anything
    else -- an unnamed dict, or a non-str/non-dict entry from a malformed
    field -- resolves to "" so the caller can filter it out.
    """
    if isinstance(criterion, str):
        return criterion.strip()
    if isinstance(criterion, dict):
        return str(criterion.get("name") or "").strip()
    return ""


def _render_evaluation_criteria_markdown(
    critical_criteria: list[Any] | None,
) -> list[str]:
    """Render the Supervisor's synthesized per-goal evaluation criteria.

    R12-18: the Supervisor already synthesizes goal-specific criteria
    reviewers should emphasize (``workflow_plan.review_phase.
    critical_criteria``, names like "Kinetic Feasibility and Experimental
    Readouts") and ``prompts/review.py`` already injects them into every
    reviewer prompt as "Critical Criteria to Emphasize" -- this only
    displays what was already computed; the review schema's fixed score
    scale is untouched.

    Titled to match Google's own published section name ("Evaluation
    Criteria"), and deliberately not "Criteria" -- that heading already
    names the run's user-authored, plain-string criteria rendered under
    "Research Goal Details" (``report_markdown_header.py``).

    A flat name list regardless of which shape each entry carries -- the
    elaborated per-criterion questions R12-23 added render separately, in
    ``_render_review_summary_markdown`` below.
    """
    if not isinstance(critical_criteria, list):
        return []
    names = [_critical_criterion_name(item) for item in critical_criteria]
    names = [name for name in names if name]
    if not names:
        return []
    lines = ["## Evaluation Criteria\n"]
    lines.extend(f"- {name}" for name in names)
    lines.append("")
    return lines


def _render_review_summary_question(question: Any) -> str:
    """Render one reviewer question bullet, or "" when unusable.

    Mirrors the published Review Summary's bolded-name-plus-question
    format (docs/CORPUS-EXTRACTION.md, line 2929): ``{name, question}``,
    the name bolded when present. A malformed question entry (missing
    text, or not an object -- ``questions`` has no legacy bare-string
    shape to fall back to, unlike the criteria themselves) renders "".
    """
    if not isinstance(question, dict):
        return ""
    name = str(question.get("name") or "").strip()
    text = str(question.get("question") or "").strip()
    if not text:
        return ""
    return f"- **{name}:** {text}" if name else f"- {text}"


def _render_review_summary_criterion(
    index: int, criterion: Any, name: str
) -> list[str]:
    """Render one numbered criterion heading plus its question bullets.

    A legacy bare-name entry (``criterion`` is a str, not a dict) carries
    no ``questions`` to look up, so it numbers in with no bullets beneath
    it -- degraded, not dropped.
    """
    lines = [f"### {index}. {name}\n"]
    raw_questions = (
        criterion.get("questions") if isinstance(criterion, dict) else None
    )
    questions = raw_questions if isinstance(raw_questions, list) else []
    for question in questions:
        line = _render_review_summary_question(question)
        if line:
            lines.append(line)
    lines.append("")
    return lines


def _render_review_summary_markdown(
    critical_criteria: list[Any] | None,
) -> list[str]:
    """Render the Supervisor's synthesized review rubric as its own section.

    R12-23: the published "Review summary" is the rubric reviewers were
    given, not a verdict -- numbered criteria (matching the run's
    synthesized ``workflow_plan.review_phase.critical_criteria`` names),
    each with its own named yes/no reviewer questions
    (docs/CORPUS-EXTRACTION.md, line 2929). ``prompts/review.py`` already
    injects this same data into every reviewer prompt; this only displays
    what was already computed, and never gates, filters, ranks, or
    disqualifies a hypothesis.

    A malformed field (not a list) or an entry with no usable name
    renders nothing -- see ``_render_review_summary_criterion`` for the
    legacy bare-name degradation.
    """
    if not isinstance(critical_criteria, list):
        return []
    named = [
        (criterion, name)
        for criterion in critical_criteria
        for name in [_critical_criterion_name(criterion)]
        if name
    ]
    if not named:
        return []
    lines = ["## Review Summary\n"]
    for index, (criterion, name) in enumerate(named, start=1):
        lines.extend(_render_review_summary_criterion(index, criterion, name))
    return lines

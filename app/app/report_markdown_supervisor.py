"""Renders the Supervisor's synthesized guidance sections.

Fields the Supervisor already synthesizes per run and ``prompts/
review.py`` already injects into every reviewer prompt, but that nothing
rendered to the reader until R12-17 (stratification attributes), R12-18
(evaluation criteria), and R12-23 (the review rubric itself). Kept
together, in their own module, because they share the same trap: each
reuses an English word Google's published documents also use for a
*different*, user-authored field -- ``config_synthesis.attributes`` vs.
the run's user-authored setup attributes, and ``workflow_plan.review_phase.
critical_criteria`` vs. the run's user-authored setup criteria (both
rendered under "Research Goal Details" in ``report_markdown_header.py``).
Reusing either heading here would present the model's synthesis as the
user's own setup, so every renderer below picks a heading distinct from
its user-authored namesake.

``critical_criteria`` backs three sections here: R12-18's "Evaluation
Criteria" (bolded-name-plus-prose per criterion, matching MASH's own
combined report -- the Research Overview document's analogue), R14-9's
same criteria rendered instead as a Criterion/Importance table (matching
the *protein-assemblies* ranking report's own analogue -- the Top
Ranking Hypotheses document -- rather than MASH's; the two published
exemplars disagree by document, not by product, and each of ours mirrors
its own document's exemplar), and R12-23's "Review Summary" (the
numbered rubric with each criterion's named reviewer questions, matching
the published document's later, separate section of that name) --
three genuinely different published sections that happen to derive from
the same synthesized field. The table's "Importance" column is the same
``description`` prose the bolded-name form already renders, under the
published column label -- not a second synthesized value; R14-9
originally read the *absence* of a distinct importance value as this
format's blocker, which does not survive a read of the schema this field
already carries. That field's entries carry three shapes across two
migrations: the legacy bare criterion-name string (a run persisted
before R12-23), the R12-23 ``{name, questions}`` object, and the richer
R12-23b ``{name, description, questions}`` object the Supervisor now
synthesizes -- ``description`` is this module's prose paragraph and is
never sent to a reviewer (see ``prompts/review.py``'s
``_format_critical_criterion`` for why). Production's json_object mode
does not enforce the schema, so a live run can answer with any of the
three shapes, or a malformed one -- every renderer below handles all of
them, degrading a missing description to the older bare-name bullet (or,
for the table, an empty second cell) and a malformed field (not a list,
or an unnamed entry) to rendering nothing.

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
    run's user-authored setup attributes rendered under
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


def _critical_criterion_description(criterion: Any) -> str:
    """Extract a critical criterion's prose description, or "".

    R12-23b: only the richer ``{name, description, questions}`` shape
    carries this. A legacy bare-name string has none, and neither does a
    dict predating this change or one whose description came back blank
    under production's json_object downgrade (which enforces no schema).
    ``_render_evaluation_criteria_markdown`` falls back to a bare
    ``- {name}`` bullet in every such case.
    """
    if not isinstance(criterion, dict):
        return ""
    return str(criterion.get("description") or "").strip()


def _critical_criteria_entries(
    critical_criteria: list[Any] | None,
) -> list[tuple[str, str]]:
    """Extract (name, description) pairs, skipping unusable entries.

    Shared by both critical_criteria renderers below (the prose form and
    the R14-9 table): both need the same filtered list before choosing how
    to lay it out, and both treat a non-list field identically -- [].
    """
    if not isinstance(critical_criteria, list):
        return []
    return [
        (name, _critical_criterion_description(item))
        for item in critical_criteria
        for name in [_critical_criterion_name(item)]
        if name
    ]


def _render_evaluation_criterion(name: str, description: str) -> list[str]:
    """Render one Evaluation Criteria entry.

    Google's own shape when there is prose to show (docs/CORPUS-
    EXTRACTION.md, line 2558): a bolded name, a colon, then the
    paragraph, followed by a blank line so consecutive criteria stay
    separate markdown paragraphs rather than merging into one. Falls
    back to the pre-R12-23b bare ``- {name}`` bullet when there is no
    usable description -- degrade, never drop.
    """
    if description:
        return [f"**{name}:** {description}", ""]
    return [f"- {name}"]


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
    names the run's user-authored setup criteria rendered under
    "Research Goal Details" (``report_markdown_header.py``).

    R12-23b: Google's published section is not a flat name list -- each
    criterion is a bolded name plus a prose paragraph stating what it
    demands (docs/CORPUS-EXTRACTION.md, line 2558). ``critical_criteria``
    now carries that prose as each entry's ``description``; this renders
    it in that shape via ``_render_evaluation_criterion`` and degrades to
    the old bare-name bullet wherever an entry has none. The elaborated
    per-criterion reviewer questions render separately, in
    ``_render_review_summary_markdown`` below.
    """
    entries = _critical_criteria_entries(critical_criteria)
    if not entries:
        return []
    lines = ["## Evaluation Criteria\n"]
    for name, description in entries:
        lines.extend(_render_evaluation_criterion(name, description))
    if lines[-1] != "":
        lines.append("")
    return lines


def _escape_table_cell(text: str) -> str:
    """Escape a literal ``|`` so it cannot be misread as a column delimiter."""
    return text.replace("|", "\\|")


def _render_evaluation_criteria_table_markdown(
    critical_criteria: list[Any] | None,
) -> list[str]:
    """Render the Supervisor's synthesized criteria as a two-column table.

    R14-9: the published *protein-assemblies* ranking report renders this
    same ``critical_criteria`` data as a GitHub-flavored Criterion/
    Importance table
    (``.../ai-guided-discovery-of-atypical-protein-assemblies/reports/
    top-ranking-hypotheses.md:9-22``), distinct from
    ``_render_evaluation_criteria_markdown``'s bolded-name-plus-prose form
    above, which mirrors MASH's combined report instead -- two published
    exemplars disagreeing by *document*, not by product, each mirrored on
    its own document (this renders on the Top Ranking Hypotheses document
    only; see ``report_markdown_documents.py``). "Importance" is that same
    entry's ``description`` under the published column label, not a
    second synthesized value.

    Same degrade-never-drop contract as the prose form: an entry with a
    name but no description still gets a row (empty second cell), and
    ``[]`` when nothing is usable -- no bare heading over an empty table.
    """
    entries = _critical_criteria_entries(critical_criteria)
    if not entries:
        return []
    lines = [
        "## Evaluation Criteria\n",
        "| Criterion | Importance |",
        "|---|---|",
    ]
    for name, description in entries:
        cell_name = _escape_table_cell(name)
        cell_description = _escape_table_cell(description)
        lines.append(f"| {cell_name} | {cell_description} |")
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

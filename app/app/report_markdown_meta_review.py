"""Report section rendering the meta-review's cross-hypothesis synthesis.

Split out of ``report_markdown`` to keep that module within the size cap.
Renders the "## Meta-review insights" heading on each of the two documents
R14-11 splits the report into: ``_render_meta_review_overview_markdown``
(Research Overview document) covers common strengths and weaknesses as
plain bullets, recurring themes (theme + description + frequency, the
taxonomy MO-2 stopped discarding before it reached this module -- see
``_render_theme``) falling back to a bare-name bullet list when only the
flattened ``emerging_themes`` shape is present, and unexpected connections
(R12-7); ``_render_meta_review_ranking_markdown`` (Top Ranking Hypotheses
document) covers the candidate/existing-solutions comparisons and the
strategic recommendation roadmap.

R12-7's published exemplar tags each connection with four fixed fields --
Claims/Reasoning/Novelty/Relevance -- that our schema does not compute:
``agents/meta_review/meta_review.py`` produces ``related_hypotheses``
(short subject labels the prompt assigns, e.g. "Fluspirilene (Hypothesis
1)", never full hypothesis text -- see ``prompts/_common.py``'s
``_format_connection``), ``connection_type``, and
``synthesis_opportunity``. Borrowing the published labels would fabricate
a novelty or relevance verdict this system never judges, so
``_render_connection`` renders our own real fields under the published
section name instead.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from app.report_markdown_overview import _render_optional_paragraph


class _RecommendationFields(NamedTuple):
    """One roadmap step, normalized from either published entry shape.

    ``strategic_recommendations`` entries are either a structured dict or
    (from before this schema existed) a bare string -- normalizing both
    into one shape here keeps ``_render_recommendation`` a plain
    formatter instead of a second isinstance branch.
    """

    body: str
    justification: str
    time_estimate: str
    phase_label: str
    recommended_idea: str


def _normalize_recommendation(
    rec: dict[str, Any] | str,
) -> _RecommendationFields:
    """Normalize one recommendation entry, dict or legacy bare string."""
    if not isinstance(rec, dict):
        return _RecommendationFields(str(rec), "", "", "", "")
    area = rec.get("focus_area", "")
    recommendation = rec.get("recommendation", "")
    body = f"**{area}**: {recommendation}" if area else str(recommendation)
    return _RecommendationFields(
        body=body,
        justification=str(rec.get("justification") or ""),
        # R14-8: the published roadmap's richer step shape -- a time
        # estimate, an optional lettered sub-phase, and which reviewed
        # idea a step selects (by hypothesis_index, never by echoing its
        # text -- see schemas/planning.py). Absent on a report persisted
        # before these fields existed, or an entry that carries none.
        time_estimate=str(rec.get("time_estimate") or "").strip(),
        phase_label=str(rec.get("phase_label") or "").strip(),
        recommended_idea=str(rec.get("recommended_idea") or "").strip(),
    )


def _render_recommendation(
    rec: dict[str, Any] | str, *, index: int | None = None
) -> list[str]:
    """Render one recommendation entry, as the primary lead or a roadmap step.

    ``index=None`` renders the lead line, labelled "Primary recommendation";
    an integer ``index`` renders it as that numbered roadmap step instead.
    """
    fields = _normalize_recommendation(rec)
    prefix = f"{fields.phase_label}: " if fields.phase_label else ""
    suffix = f" ({fields.time_estimate})" if fields.time_estimate else ""
    label = "**Primary recommendation:**" if index is None else f"{index}."
    lines = [f"{label} {prefix}{fields.body}{suffix}"]
    if fields.justification:
        lines.append(f"  *{fields.justification}*")
    if fields.recommended_idea:
        lines.append(f"  Recommended idea: {fields.recommended_idea}")
    return lines


def _render_bullet_list(heading: str, items: list[Any]) -> list[str]:
    """Render a heading and its bullet items, or nothing when empty."""
    if not items:
        return []
    return [f"\n{heading}\n"] + [f"- {item}" for item in items]


_META_REVIEW_BULLET_SECTIONS = (
    ("common_strengths", "### Common strengths"),
    ("common_weaknesses", "### Common weaknesses"),
)


def _render_theme(theme: dict[str, Any]) -> list[str]:
    """Render one recurring-theme entry with its description and frequency."""
    name = str(theme.get("theme") or "")
    if not name:
        return []
    description = theme.get("description") or ""
    lines = [f"**{name}**: {description}" if description else f"- {name}"]
    frequency = theme.get("frequency") or ""
    if frequency:
        lines.append(f"  *Frequency: {frequency}*")
    return lines


def _render_emerging_themes(meta_review: dict[str, Any]) -> list[str]:
    """Render 'Emerging themes' from the structured taxonomy or its fallback.

    Prefers ``recurring_themes`` (theme + description + frequency, the
    full taxonomy the model computed and MO-2 stopped discarding); falls
    back to the flattened ``emerging_themes`` bare-name list when
    structured data is absent -- a demo/seed report, or one persisted
    before this field existed.
    """
    themes = meta_review.get("recurring_themes")
    if not themes:
        return _render_bullet_list(
            "### Emerging themes", meta_review.get("emerging_themes") or []
        )
    lines: list[str] = []
    for theme in themes:
        if isinstance(theme, dict):
            lines.extend(_render_theme(theme))
        else:
            lines.append(f"- {theme}")
    if not lines:
        return []
    return ["\n### Emerging themes\n", *lines]


# Legacy fixed field set: what a run's meta-review carried before the
# comparison axes became domain-aware. A report persisted (or, for an
# in-flight run, a checkpoint written) under the old schema still has this
# shape, not `axes`/`values`, so the renderers below accept either.
_IDEA_COMPARISON_FIELDS = (
    ("distinguishing_attribute", "Distinguishing attribute"),
    ("computational_scalability", "Computational scalability"),
    ("supporting_evidence_basis", "Supporting evidence basis"),
    ("primary_novelty_parameter", "Primary novelty parameter"),
)

_EXISTING_SOLUTION_FIELDS = (
    ("approach", "Approach"),
    ("sensitivity_to_novelty", "Sensitivity to novelty"),
    ("scalability", "Scalability"),
)


def _render_legacy_comparison_fields(
    entry: dict[str, Any], fields: tuple[tuple[str, str], ...]
) -> list[str]:
    """Render bullet lines for the pre-axes fixed field set."""
    lines = []
    for key, heading in fields:
        value = str(entry.get(key) or "").strip()
        if value:
            lines.append(f"  - **{heading}:** {value}")
    return lines


def _render_axis_values(axes: list[Any], values: Any) -> list[str]:
    """Render bullet lines pairing each axis with its positional value.

    ``values[i]`` rates the row on ``axes[i]`` (schemas/meta_review_schema.py's
    convention); a shorter list on either side simply pairs up to its own
    length rather than rendering an unlabeled value or raising.
    """
    if not isinstance(values, list):
        return []
    lines = []
    for axis, value in zip(axes, values, strict=False):
        axis_label = str(axis).strip()
        value_text = str(value).strip()
        if axis_label and value_text:
            lines.append(f"  - **{axis_label}:** {value_text}")
    return lines


def _render_idea_comparison(idea: Any, axes: list[Any]) -> list[str]:
    """Render one candidate-idea comparison row, or nothing when unlabeled.

    Prefers the domain-aware ``values`` shape, paired positionally against
    the table's own ``axes``; falls back to the older fixed field set
    (``_IDEA_COMPARISON_FIELDS``) for a run whose meta-review predates that.
    """
    if not isinstance(idea, dict):
        return []
    label = str(idea.get("idea") or "").strip()
    if not label:
        return []
    lines = [f"- **{label}**"]
    if axes and isinstance(idea.get("values"), list):
        lines += _render_axis_values(axes, idea["values"])
    else:
        lines += _render_legacy_comparison_fields(idea, _IDEA_COMPARISON_FIELDS)
    return lines


def _render_candidate_comparison(comparison: Any) -> list[str]:
    """Render 'Comparison of candidate ideas', or nothing when empty.

    Google's published report carries this comparison twice under the
    same title (R12-9): a thematic prose comparison (section 5) and a
    structured per-idea table (section 6). The table's columns follow the
    run's own subject matter (``axes``, chosen per run rather than fixed --
    a wet-lab biology idea has no use for "computational scalability"),
    rendered as a thematic summary paragraph plus one bullet block per
    idea, in the bold-label style every other section here uses (see
    ``_render_connection``) rather than a markdown table, which nothing in
    this renderer emits elsewhere.
    """
    if not isinstance(comparison, dict):
        return []
    summary = str(comparison.get("thematic_summary") or "").strip()
    axes = comparison.get("axes") or []
    idea_lines: list[str] = []
    for idea in comparison.get("ideas") or []:
        idea_lines += _render_idea_comparison(idea, axes)
    if not (summary or idea_lines):
        return []
    lines = ["\n### Comparison of candidate ideas\n"]
    if summary:
        lines += [summary, ""]
    lines += idea_lines
    return lines


def _render_existing_solution_row(row: Any, axes: list[Any]) -> list[str]:
    """Render one existing-solutions comparison row, or nothing when unnamed.

    Same axes/values-or-legacy-fields choice as ``_render_idea_comparison``.
    """
    if not isinstance(row, dict):
        return []
    label = str(row.get("method") or "").strip()
    if not label:
        return []
    lines = [f"- **{label}**"]
    if axes and isinstance(row.get("values"), list):
        lines += _render_axis_values(axes, row["values"])
    else:
        lines += _render_legacy_comparison_fields(
            row, _EXISTING_SOLUTION_FIELDS
        )
    return lines


def _render_existing_solutions_comparison(comparison: Any) -> list[str]:
    """Render 'Comparison to existing solutions', or nothing when empty.

    Empty (not just absent) is a real, expected case here: the prompt
    tells the model to leave this whole comparison out when the goal has
    no standard-of-care landscape to compare against (e.g. a basic
    mechanism question), rather than inventing one.
    """
    if not isinstance(comparison, dict):
        return []
    summary = str(comparison.get("summary") or "").strip()
    axes = comparison.get("axes") or []
    row_lines: list[str] = []
    for row in comparison.get("rows") or []:
        row_lines += _render_existing_solution_row(row, axes)
    if not (summary or row_lines):
        return []
    lines = ["\n### Comparison to existing solutions\n"]
    if summary:
        lines += [summary, ""]
    lines += row_lines
    return lines


def _render_strategic_recommendations(recs: list[Any]) -> list[str]:
    """Render 'Recommendation and strategic roadmap', or nothing when empty.

    Google's published section 9 (R12-11) sequences a named primary
    recommendation through four named phases, each with concrete next
    steps. Our ``strategic_recommendations`` carries no phase name,
    dependency, or ordering field beyond list position -- it is a flat
    ``{focus_area, recommendation, justification}`` list -- so named
    phases with assays would be invented content the schema cannot
    support. This distinguishes the first entry as the primary
    recommendation and numbers the rest as roadmap steps, the
    presentation the data actually carries.
    """
    if not recs:
        return []
    lines = ["\n### Recommendation and strategic roadmap\n"]
    lines += _render_recommendation(recs[0])
    for i, rec in enumerate(recs[1:], start=1):
        lines += _render_recommendation(rec, index=i)
    return lines


def _render_related_hypotheses(related: list[str]) -> list[str]:
    """Render the 'Related hypotheses' bullet block for one connection."""
    if not related:
        return ["- **Related hypotheses:** (unspecified)"]
    return ["- **Related hypotheses:**"] + [f"  - {h}" for h in related]


def _render_connection(connection: Any) -> list[str]:
    """Render one potential-connection entry, or nothing when malformed."""
    if not isinstance(connection, dict):
        return []
    related = [str(h) for h in connection.get("related_hypotheses") or []]
    kind = str(connection.get("connection_type") or "")
    opportunity = str(connection.get("synthesis_opportunity") or "")
    if not (related or kind or opportunity):
        return []
    lines = _render_related_hypotheses(related)
    if kind:
        lines.append(f"  - **Connection type:** {kind}")
    if opportunity:
        lines.append(f"  - **Synthesis opportunity:** {opportunity}")
    return lines


def _render_unexpected_connections(connections: list[Any]) -> list[str]:
    """Render 'Unexpected connections', or nothing when empty."""
    lines: list[str] = []
    for connection in connections:
        lines += _render_connection(connection)
    if not lines:
        return []
    return ["\n### Unexpected connections\n", *lines]


def _render_main_research_directions_markdown(
    meta_review: dict[str, Any],
) -> list[str]:
    """Render the ranking document's "Main Research Directions" (R14-27).

    Google's published ranking report carries its own narrative synthesis
    here -- two flowing prose paragraphs weaving the run's directions
    together (``top-ranking-hypotheses.md:24-28``), distinct from the
    itemized per-direction array the Research Overview document renders
    (``report_markdown_overview.py::_render_directions_list``). The
    ``meta_review.main_research_directions`` string already carries any
    internal paragraph break the model wrote (schemas/meta_review_schema.py
    asks for two, separated by a blank line), so this renders it verbatim
    rather than re-splitting it.

    Skips cleanly -- no bare heading -- when the field is absent or blank:
    a legacy run persisted before this field existed, or a provider
    response that omits it under json_object mode.
    """
    text = str(meta_review.get("main_research_directions") or "").strip()
    if not text:
        return []
    return ["## Main Research Directions\n", text, ""]


def _render_meta_review_overview_markdown(
    meta_review: dict[str, Any],
) -> list[str]:
    """Render the Research Overview document's meta-review insights.

    R14-11: cross-run synthesis -- common strengths/weaknesses, recurring
    themes, and unexpected connections -- belongs on ``research-overview.md``
    ("meta-review-style synthesis"), which names "Unexpected connections"
    directly as one of its own six sections. The tournament-facing half of
    this same payload (candidate comparison, existing-solutions comparison,
    the recommendation roadmap) renders separately, on the ranking document
    -- see ``_render_meta_review_ranking_markdown``.
    """
    if not meta_review:
        return []
    lines = ["\n## Meta-review insights\n"]
    lines += _render_optional_paragraph(meta_review.get("summary"))
    for section_key, heading in _META_REVIEW_BULLET_SECTIONS:
        lines += _render_bullet_list(
            heading, meta_review.get(section_key) or []
        )
    lines += _render_emerging_themes(meta_review)
    lines += _render_unexpected_connections(
        meta_review.get("potential_connections") or []
    )
    return lines


def _render_meta_review_ranking_markdown(
    meta_review: dict[str, Any],
) -> list[str]:
    """Render the Top Ranking Hypotheses document's meta-review insights.

    R14-11: the tournament/ranking comparison content -- candidate
    comparison ("Idea Comparison Table"), the existing-solutions comparison,
    and the recommendation roadmap ("Recommendation") -- are three of that
    document's own named sections. Kept under the same "Meta-review
    insights" heading the overview half uses (see
    ``_render_meta_review_overview_markdown``) rather than promoting each
    ``###`` to a top-level ``##``: both halves are equally "insights the
    meta-review agent produced", just addressed to a different document now
    that there are two, and splitting the heading text as well as the
    content would be a second, unattested change.
    """
    if not meta_review:
        return []
    lines = ["\n## Meta-review insights\n"]
    lines += _render_candidate_comparison(
        meta_review.get("candidate_comparison")
    )
    lines += _render_existing_solutions_comparison(
        meta_review.get("existing_solutions_comparison")
    )
    lines += _render_strategic_recommendations(
        meta_review.get("strategic_recommendations") or []
    )
    return lines

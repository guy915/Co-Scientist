"""Report section rendering the meta-review's cross-hypothesis synthesis.

Split out of ``report_markdown`` to keep that module within the size cap.
Renders the "## Meta-review insights" heading: common strengths and
weaknesses as plain bullets, recurring themes (theme + description +
frequency, the taxonomy MO-2 stopped discarding before it reached this
module -- see ``_render_theme``) falling back to a bare-name bullet list
when only the flattened ``emerging_themes`` shape is present, strategic
recommendations with their justification, and unexpected connections
(R12-7).

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

from typing import Any

from app.report_markdown_overview import _render_optional_paragraph


def _render_recommendation(
    rec: dict[str, Any] | str, *, index: int | None = None
) -> list[str]:
    """Render one recommendation entry, as the primary lead or a roadmap step.

    ``index=None`` renders the lead line, labelled "Primary recommendation";
    an integer ``index`` renders it as that numbered roadmap step instead.
    Structured (dict) recommendations render with a rationale; a bare string
    falls back to its text alone.
    """
    if isinstance(rec, dict):
        area = rec.get("focus_area", "")
        recommendation = rec.get("recommendation", "")
        body = f"**{area}**: {recommendation}" if area else str(recommendation)
        justification = rec.get("justification", "")
    else:
        body, justification = str(rec), ""
    label = "**Primary recommendation:**" if index is None else f"{index}."
    lines = [f"{label} {body}"]
    if justification:
        lines.append(f"  *{justification}*")
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


def _render_meta_review_markdown(meta_review: dict[str, Any]) -> list[str]:
    """Render the meta-review insights section, or nothing when absent."""
    if not meta_review:
        return []
    lines = ["\n## Meta-review insights\n"]
    lines += _render_optional_paragraph(meta_review.get("summary"))
    for section_key, heading in _META_REVIEW_BULLET_SECTIONS:
        lines += _render_bullet_list(
            heading, meta_review.get(section_key) or []
        )
    lines += _render_emerging_themes(meta_review)
    lines += _render_strategic_recommendations(
        meta_review.get("strategic_recommendations") or []
    )
    lines += _render_unexpected_connections(
        meta_review.get("potential_connections") or []
    )
    return lines

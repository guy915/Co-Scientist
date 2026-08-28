"""Report section rendering the meta-review's cross-hypothesis synthesis.

Split out of ``report_markdown`` to keep that module within the size cap.
Renders the "## Meta-review insights" heading: common strengths and
weaknesses as plain bullets, recurring themes (theme + description +
frequency, the taxonomy MO-2 stopped discarding before it reached this
module -- see ``_render_theme``) falling back to a bare-name bullet list
when only the flattened ``emerging_themes`` shape is present, and
strategic recommendations with their justification.
"""

from __future__ import annotations

from typing import Any

from app.report_markdown_overview import _render_optional_paragraph


def _render_recommendation(rec: dict[str, Any] | str) -> list[str]:
    """Render one strategic recommendation entry.

    Structured (dict) recommendations render with a rationale; a bare string
    falls back to a plain bullet.
    """
    if isinstance(rec, dict):
        area = rec.get("focus_area", "")
        recommendation = rec.get("recommendation", "")
        lines = [f"**{area}**: {recommendation}"]
        justification = rec.get("justification", "")
        if justification:
            lines.append(f"  *{justification}*")
        return lines
    return [f"- {rec}"]


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
    """Render the 'Strategic recommendations' section, or nothing when empty."""
    if not recs:
        return []
    lines = ["\n### Strategic recommendations\n"]
    for rec in recs:
        lines += _render_recommendation(rec)
    return lines


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
    return lines

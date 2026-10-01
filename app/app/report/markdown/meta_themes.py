"""Report rendering of the meta-review's recurring-critique taxonomy (MO-2).

Split out of ``report.markdown.meta_review`` when the taxonomy regained its
nesting: that module was at 436 of the 500-line ceiling, and the "Emerging
themes" section is the one part of it with no shared state.

Google's published meta-review critique
(``references/core/.../meta-review-critiques/als-meta-review-critique.md``)
organizes the recurring critiques three levels deep -- a Roman-numbered
theme, the named critique points under it, and the guidance sub-points
under several of those -- so this renders three levels of real markdown
hierarchy: an ``####`` heading per theme, a bullet per critique point, an
indented sub-bullet per guidance point. Flattening them into one bullet
list is what this replaced, and is what made a 5-theme taxonomy read as
five unrelated sentences.

Three shapes reach here and all three must render. The nested one is what
``engine`` produces now; the flat ``{theme, description, frequency}`` is
what a run checkpointed before ``sub_themes`` existed still carries, since
``meta_review`` is durable state that outlives a schema change; and a bare
string is what a ``json_object``-mode model returns when it ignores the
schema entirely. Every field is therefore read with a default rather than
by indexing.
"""

from __future__ import annotations

from typing import Any


def _render_points(points: Any) -> list[str]:
    """Render a critique point's guidance sub-points as indented bullets."""
    if not isinstance(points, list):
        return []
    return [f"  - {point}" for point in points if str(point).strip()]


def _sub_theme_headline(name: str, description: str) -> str:
    """Render a critique point's own bullet line.

    Named and described is the published shape ("Primary Driver vs.
    Consequence: A very common critique ..."); either alone still gets a
    bullet rather than an empty label.
    """
    if name and description:
        return f"- **{name}**: {description}"
    return f"- {name or description}"


def _render_sub_theme(sub_theme: Any) -> list[str]:
    """Render one critique point and its guidance sub-points."""
    if not isinstance(sub_theme, dict):
        text = str(sub_theme).strip()
        return [f"- {text}"] if text else []
    name = str(sub_theme.get("theme") or "").strip()
    description = str(sub_theme.get("description") or "").strip()
    if not name and not description:
        return []
    return [
        _sub_theme_headline(name, description),
        *_render_points(sub_theme.get("points")),
    ]


def _render_sub_themes(sub_themes: Any) -> list[str]:
    """Render a theme's critique points, tolerating a non-list value."""
    if not isinstance(sub_themes, list):
        return []
    lines: list[str] = []
    for sub_theme in sub_themes:
        lines.extend(_render_sub_theme(sub_theme))
    return lines


def _render_theme(theme: dict[str, Any]) -> list[str]:
    """Render one top-level theme: heading, prose, frequency, sub-themes.

    An entry with no name renders nothing at all -- an empty name used to
    reach the bolded-label formatter and print a doubled-asterisk ``****:``
    over orphaned text.

    The blank line before the sub-theme bullets is load-bearing: without
    it the theme's own prose and the first bullet are adjacent lines, and
    whether that starts a list or continues the paragraph is a renderer's
    choice rather than ours.
    """
    name = str(theme.get("theme") or "").strip()
    if not name:
        return []
    lines = [f"\n#### {name}\n"]
    description = str(theme.get("description") or "").strip()
    if description:
        lines.append(description)
    frequency = str(theme.get("frequency") or "").strip()
    if frequency:
        lines.append(f"*Frequency: {frequency}*")
    sub_themes = _render_sub_themes(theme.get("sub_themes"))
    if sub_themes:
        # Only when prose precedes them: the heading line already carries
        # its own trailing newline, so an unconditional separator would
        # print two blank lines under a theme that has no prose.
        lines.extend(["", *sub_themes] if len(lines) > 1 else sub_themes)
    return lines


def _render_theme_entry(theme: Any) -> list[str]:
    """Render one ``recurring_themes`` entry, dict or bare string."""
    if isinstance(theme, dict):
        return _render_theme(theme)
    text = str(theme).strip()
    return [f"\n#### {text}\n"] if text else []


def render_emerging_themes(meta_review: dict[str, Any]) -> list[str]:
    """Render 'Emerging themes' from the taxonomy, or from its fallback.

    Prefers ``recurring_themes`` (the full nested taxonomy); falls back to
    the flattened ``emerging_themes`` bare-name list when structured data
    is absent -- a demo/seed report, or one persisted before that field
    existed. The fallback stays a plain bullet list: bare names carry no
    hierarchy to show.

    Args:
        meta_review: The run's meta-review state dict.

    Returns:
        Markdown lines for the section, or an empty list when there is
        nothing to render.
    """
    themes = meta_review.get("recurring_themes")
    if not themes:
        return _render_bare_theme_names(meta_review.get("emerging_themes"))
    lines: list[str] = []
    for theme in themes:
        lines.extend(_render_theme_entry(theme))
    if not lines:
        return []
    return ["\n### Emerging themes\n", *lines]


def _render_bare_theme_names(emerging_themes: Any) -> list[str]:
    """Render the flattened name-only fallback as a plain bullet list."""
    if not isinstance(emerging_themes, list) or not emerging_themes:
        return []
    return ["\n### Emerging themes\n"] + [
        f"- {name}" for name in emerging_themes
    ]

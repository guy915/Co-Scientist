"""Font-size/weight/case heading ranking, the last resort in the cascade.

Used only for lines that carry neither a bookmark match nor a recognizable
numbering marker. Two responsibilities live here: reading per-line style
out of a real PDF page (:func:`collect_line_styles`, which drives pypdf's
``visitor_text`` callback) and ranking plain style records into heading
levels (:func:`rank_heading_styles`, pure data in and out so it can be
tested without a PDF parser at all).

Font size is measured from the character's own ``Tf`` value scaled by the
text matrix, not from a rendered glyph's bounding box, so it does not
suffer the "descenders measure taller" noise a cell-height measurement
would -- but floating-point cm/tm composition and mixed runs on one line
still produce a few hundredths of a point of jitter between two headings
that are visually identical, so near-equal sizes are still merged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.pdf.heading_levels import compress_to_levels

# Sizes within this relative tolerance of each other collapse into one
# cluster, so measurement jitter cannot manufacture a spurious heading
# level between two lines set in the same nominal size.
_SIZE_TOLERANCE = 0.08

# A heading candidate line must be short: a long line at a bigger size is
# more likely a pull quote or a table cell than a section title.
MAX_HEADING_CHARS = 120


@dataclass(frozen=True)
class LineStyle:
    """The visual style of one candidate heading line."""

    size: float
    bold: bool
    all_caps: bool


def _is_all_caps(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    return len(letters) >= 4 and all(char.isupper() for char in letters)


def _is_bold(font_dict: Any) -> bool:
    """Guess boldness from the font's own name (no embedded-font parsing).

    Standard and subsetted PDF fonts alike carry their weight in the
    ``/BaseFont`` name (``Helvetica-Bold``, ``ABCDEF+Arial-BoldMT``), so a
    substring check covers both without needing the font's descriptor.
    """
    if not isinstance(font_dict, dict):
        return False
    base_font = str(font_dict.get("/BaseFont", ""))
    lowered = base_font.lower()
    return "bold" in lowered or "black" in lowered or "heavy" in lowered


def _effective_size(font_size: float, tm_matrix: list[float]) -> float:
    """Font size actually rendered, after the text matrix's own scaling.

    A generator that sets ``Tf 1`` and scales through ``Tm`` instead would
    report every run at size 1.0 if the raw ``Tf`` value were trusted, so
    the vertical scale of the text matrix is folded in.
    """
    scale = math.hypot(tm_matrix[1], tm_matrix[3])
    return font_size * (scale or 1.0)


class _LineCollector:
    r"""Groups pypdf's per-run visitor callbacks into per-line style votes.

    A run boundary (font change, positioning op) does not by itself end a
    line -- only an embedded ``"\n"`` does, which pypdf appends to the run
    text that precedes a detected line break.
    """

    def __init__(self) -> None:
        self.lines: list[tuple[str, float, bool]] = []
        self._text = ""
        self._max_size = 0.0
        self._bold_chars = 0
        self._plain_chars = 0

    def _flush_line(self) -> None:
        if self._text.strip():
            bold = self._bold_chars >= self._plain_chars
            self.lines.append((self._text, self._max_size, bold))
        self._text = ""
        self._max_size = 0.0
        self._bold_chars = 0
        self._plain_chars = 0

    def __call__(
        self,
        text: str,
        _cm_matrix: list[float],
        tm_matrix: list[float],
        font_dict: Any,
        font_size: float,
    ) -> None:
        size = _effective_size(font_size, tm_matrix)
        bold = _is_bold(font_dict)
        segments = text.split("\n")
        for index, segment in enumerate(segments):
            if segment:
                self._text += segment
                self._max_size = max(self._max_size, size)
                if bold:
                    self._bold_chars += len(segment)
                else:
                    self._plain_chars += len(segment)
            if index < len(segments) - 1:
                self._flush_line()


def collect_line_styles(page: Any) -> dict[str, LineStyle]:
    """Map each short candidate line's own text to its rendered style.

    Runs a second, ``visitor_text``-driven extraction pass over the page
    (the layout-mode pass used for the page's actual output text ignores
    ``visitor_text`` entirely). Keyed by the line's stripped text rather
    than position, since the two passes reconstruct lines independently
    and are matched back together by content in :mod:`app.pdf.headings`.
    """
    collector = _LineCollector()
    page.extract_text(visitor_text=collector)
    collector._flush_line()
    styles: dict[str, LineStyle] = {}
    for text, size, bold in collector.lines:
        stripped = text.strip()
        if not stripped or len(stripped) > MAX_HEADING_CHARS:
            continue
        styles.setdefault(
            stripped,
            LineStyle(size=size, bold=bold, all_caps=_is_all_caps(stripped)),
        )
    return styles


def _cluster_sizes(sizes: set[float]) -> dict[float, int]:
    """Group sizes into clusters, largest first; map size -> cluster index."""
    clusters: dict[float, int] = {}
    index = 0
    previous: float | None = None
    for size in sorted(sizes, reverse=True):
        gap = previous - size if previous is not None else 0.0
        if previous is not None and gap > _SIZE_TOLERANCE * previous:
            index += 1
        clusters[size] = index
        previous = size
    return clusters


def rank_heading_styles(
    styles: dict[int, LineStyle], body_size: float
) -> dict[int, int]:
    """Rank lines strictly larger than the body size into heading levels.

    Order: font size first (with near-equal sizes merged), then weight
    (bold above regular), then case (all-caps above mixed) as the
    tie-break within a shared size cluster. A line at or below the body
    size is not a heading candidate at all -- it is caption- or
    footnote-scaled, not emphasized -- and is left out of the result.
    """
    candidates = {
        index: style
        for index, style in styles.items()
        if style.size > body_size
    }
    if not candidates:
        return {}

    clusters = _cluster_sizes({style.size for style in candidates.values()})
    keys = {
        index: (clusters[style.size], not style.bold, not style.all_caps)
        for index, style in candidates.items()
    }
    return compress_to_levels(keys)

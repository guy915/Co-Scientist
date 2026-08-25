"""Cascade orchestration: bookmarks, then numbering, then font style.

Combines the three signals in :mod:`app.pdf_heading_bookmarks`,
:mod:`app.pdf_numbering`, and :mod:`app.pdf_heading_style` into one set of
heading levels for a whole PDF, and rewrites each page's extracted text
with ATX (``#``/``##``/``###``) markers at the inferred positions.

Every signal is computed once across the *whole* document rather than
per page, so a level means the same thing wherever it appears -- a
bookmark depth compressed one page at a time could give two genuinely
different-depth chapters the same level just because each was the only
match on its own page. Bookmark *matching* is still page-scoped (a
title is only compared against the page its destination points to), but
the raw depths it finds are pooled and compressed once at the end.

Precedence is bookmark > numbering > style, applied by ``setdefault``:
once a line has a level from a higher signal, a lower one cannot
override it. A line no signal reaches keeps its original text exactly,
which is what makes heading inference fail soft -- a document with no
outline, no numbering, and a uniform font produces output identical to
plain extraction.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.pdf_heading_bookmarks import raw_bookmark_matches
from app.pdf_heading_levels import compress_to_levels
from app.pdf_heading_style import (
    MAX_HEADING_CHARS,
    LineStyle,
    collect_line_styles,
    rank_heading_styles,
)
from app.pdf_numbering import infer_numbering_levels

# ATX only goes to h3 here: a fourth inferred level is rare enough in a
# scientist's attached paper that flattening it into h3 costs less than
# the added complexity of a deeper cascade would.
_MAX_LEVEL = 3


def _walk_outline(
    reader: Any, items: Any, depth: int, out: list[tuple[str, int, int]]
) -> None:
    """Depth-first walk of pypdf's nested-list outline structure."""
    for item in items:
        if isinstance(item, list):
            _walk_outline(reader, item, depth + 1, out)
            continue
        title = getattr(item, "title", None)
        if not title:
            continue
        try:
            page_index = reader.get_destination_page_number(item)
        except Exception:  # a dangling /Dest reference costs one bookmark
            continue
        out.append((str(title), depth, page_index))


def flatten_outline(reader: Any) -> list[tuple[str, int, int]]:
    """Flatten ``reader.outline`` into (title, nesting depth, page index).

    Raises whatever ``reader.outline`` itself raises (including on a
    reader that carries no such attribute at all) -- the caller is
    responsible for the fail-soft boundary around the whole cascade.
    """
    outline = reader.outline
    if not outline:
        return []
    out: list[tuple[str, int, int]] = []
    _walk_outline(reader, outline, 1, out)
    return out


def _bookmarks_on_page(
    outline: list[tuple[str, int, int]], page_index: int
) -> list[tuple[str, int]]:
    return [(title, depth) for title, depth, pg in outline if pg == page_index]


def _pool_bookmark_levels(
    outline: list[tuple[str, int, int]], lines_per_page: list[list[str]]
) -> dict[tuple[int, int], int]:
    """Match bookmarks per page, then compress raw depths once, globally."""
    raw: dict[tuple[int, int], int] = {}
    for page_index, lines in enumerate(lines_per_page):
        page_outline = _bookmarks_on_page(outline, page_index)
        if not page_outline:
            continue
        matches = raw_bookmark_matches(page_outline, lines)
        for line_index, depth in matches.items():
            raw[(page_index, line_index)] = depth
    return compress_to_levels(raw)


def _numbering_candidate_positions(
    lines_per_page: list[list[str]],
) -> list[tuple[int, int, str]]:
    """Every short, non-blank line.

    The pool ``infer_numbering_levels`` picks its actual marker-bearing
    candidates out of.
    """
    positions: list[tuple[int, int, str]] = []
    for page_index, lines in enumerate(lines_per_page):
        for line_index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or len(stripped) > MAX_HEADING_CHARS:
                continue
            positions.append((page_index, line_index, stripped))
    return positions


def _pool_numbering_levels(
    lines_per_page: list[list[str]],
) -> dict[tuple[int, int], int]:
    positions = _numbering_candidate_positions(lines_per_page)
    levels = infer_numbering_levels([text for *_, text in positions])
    return {
        (positions[i][0], positions[i][1]): level for i, level in levels.items()
    }


def _modal_size(sizes: list[float]) -> float:
    """The most common font size, rounded to absorb sub-point jitter."""
    counts = Counter(round(size, 1) for size in sizes)
    return counts.most_common(1)[0][0]


def _flatten_style_candidates(
    lines_per_page: list[list[str]],
    per_page_styles: list[dict[str, LineStyle]],
) -> tuple[list[tuple[int, int]], dict[int, LineStyle]]:
    ordered_keys: list[tuple[int, int]] = []
    flat_styles: dict[int, LineStyle] = {}
    for page_index, lines in enumerate(lines_per_page):
        text_to_style = per_page_styles[page_index]
        for line_index, line in enumerate(lines):
            style = text_to_style.get(line.strip())
            if style is None:
                continue
            flat_styles[len(ordered_keys)] = style
            ordered_keys.append((page_index, line_index))
    return ordered_keys, flat_styles


def _pool_style_levels(
    pages: list[Any], lines_per_page: list[list[str]]
) -> dict[tuple[int, int], int]:
    per_page_styles = [collect_line_styles(page) for page in pages]
    all_sizes: list[float] = []
    for styles in per_page_styles:
        all_sizes.extend(style.size for style in styles.values())
    if not all_sizes:
        return {}
    body_size = _modal_size(all_sizes)
    ordered_keys, flat_styles = _flatten_style_candidates(
        lines_per_page, per_page_styles
    )
    ranked = rank_heading_styles(flat_styles, body_size)
    return {ordered_keys[i]: level for i, level in ranked.items()}


def _combine_levels(
    bookmark: dict[tuple[int, int], int],
    numbering: dict[tuple[int, int], int],
    style: dict[tuple[int, int], int],
) -> dict[tuple[int, int], int]:
    combined = dict(bookmark)
    for key, level in numbering.items():
        combined.setdefault(key, level)
    for key, level in style.items():
        combined.setdefault(key, level)
    return {
        key: max(1, min(level, _MAX_LEVEL)) for key, level in combined.items()
    }


def _rewrite_lines(
    lines_per_page: list[list[str]], levels: dict[tuple[int, int], int]
) -> list[str]:
    pages_out = []
    for page_index, lines in enumerate(lines_per_page):
        rewritten = list(lines)
        for line_index, line in enumerate(lines):
            level = levels.get((page_index, line_index))
            if level is not None:
                rewritten[line_index] = "#" * level + " " + line.strip()
        pages_out.append("\n".join(rewritten))
    return pages_out


def apply_heading_markup(
    reader: Any, pages: list[Any], pages_text: list[str]
) -> list[str]:
    """Weave inferred ATX heading markers into per-page extracted text.

    ``pages_text`` is the page text produced by plain extraction, one
    entry per page in ``pages``/``reader.pages`` order. Returns a same-
    length list; a line no signal reaches is copied through unchanged.
    """
    lines_per_page = [text.split("\n") for text in pages_text]
    outline = flatten_outline(reader)
    bookmark_levels = _pool_bookmark_levels(outline, lines_per_page)
    numbering_levels = _pool_numbering_levels(lines_per_page)
    style_levels = _pool_style_levels(pages, lines_per_page)
    levels = _combine_levels(bookmark_levels, numbering_levels, style_levels)
    return _rewrite_lines(lines_per_page, levels)

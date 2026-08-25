"""PDF outline (bookmark) matching, the most authoritative heading signal.

A bookmark's title is fuzzily matched against a page's candidate lines --
exact PDF bookmarks are frequently truncated or drop their own leading
numbering marker -- and a confidently matched line takes the bookmark's
declared depth. The line comparison here works on plain strings; walking
a real ``PdfReader.outline`` into ``(title, depth, page_index)`` tuples is
:func:`app.pdf_headings.flatten_outline`, kept apart so this module's
matching logic is testable without a PDF parser at all.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.pdf_heading_levels import compress_to_levels

# A confident match must clear this similarity ratio (0..1). Below it, a
# coincidentally similar line is worse than leaving the bookmark unmatched.
_MATCH_THRESHOLD = 0.72

# A leading numbering marker, stripped before comparison so a bookmark
# titled "Background" still matches an on-page "1.1 Background".
_LEADING_MARKER = re.compile(
    r"^\s*(?:\(?[0-9]+(?:\.[0-9]+)*[).]?|\(?[A-Za-z]{1,2}[).])[\s.:)\-]*"
)


def _norm(text: str) -> str:
    """Lower-case, collapse whitespace, and trim outer punctuation."""
    collapsed = re.sub(r"\s+", " ", text.lower()).strip()
    return re.sub(r"^[\W_]+|[\W_]+$", "", collapsed)


def _match_score(line: str, title: str) -> float:
    """Similarity in 0..1, comparing both strings with and without a marker."""
    variants_a = {_norm(line), _norm(_LEADING_MARKER.sub("", line))} - {""}
    variants_b = {_norm(title), _norm(_LEADING_MARKER.sub("", title))} - {""}
    best = 0.0
    for a in variants_a:
        for b in variants_b:
            best = max(best, SequenceMatcher(None, a, b).ratio())
            if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
                best = max(best, 0.92)
    return best


def _best_match(title: str, lines: list[str], claimed: set[int]) -> int | None:
    best_index: int | None = None
    best_score = _MATCH_THRESHOLD
    for index, line in enumerate(lines):
        if index in claimed:
            continue
        score = _match_score(line, title)
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def raw_bookmark_matches(
    outline: list[tuple[str, int]], lines: list[str]
) -> dict[int, int]:
    """Match each bookmark to at most one line; depths are not yet compressed.

    Each line is claimed by at most one bookmark (first confident match
    wins, in outline order), so two similarly-titled bookmarks cannot both
    land on the same line.
    """
    claimed: set[int] = set()
    matches: dict[int, int] = {}
    for title, depth in outline:
        if not title.strip():
            continue
        index = _best_match(title, lines, claimed)
        if index is not None:
            claimed.add(index)
            matches[index] = depth
    return matches


def match_bookmark_levels(
    outline: list[tuple[str, int]], lines: list[str]
) -> dict[int, int]:
    """Match bookmarks to lines and compress their depths to 1-based levels."""
    return compress_to_levels(raw_bookmark_matches(outline, lines))

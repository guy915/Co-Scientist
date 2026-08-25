"""Bookmark-to-heading fuzzy matching, on plain strings.

No pypdf import -- ``match_bookmark_levels`` takes plain ``(title,
level)`` outline entries and plain candidate lines. The real ``PdfReader``
outline walk is exercised only through a real PDF, in
``test_document_ingest_pdf.py``.
"""

from app.pdf_heading_bookmarks import match_bookmark_levels


def test_exact_title_match_takes_the_bookmark_depth() -> None:
    outline = [("Introduction", 1), ("Background", 2), ("Methods", 1)]
    lines = ["Introduction", "Some prose.", "Background", "Methods"]

    levels = match_bookmark_levels(outline, lines)

    assert levels[0] == levels[3]
    assert levels[0] < levels[2]


def test_numbering_marker_on_the_page_is_ignored_when_matching() -> None:
    """A bookmark titled "Background" still matches "1.1 Background"."""
    outline = [("Background", 1)]
    lines = ["1.1 Background"]

    levels = match_bookmark_levels(outline, lines)

    assert levels == {0: 1}


def test_unmatched_bookmark_contributes_nothing() -> None:
    outline = [("Nonexistent Section", 1)]
    lines = ["Introduction", "Methods"]

    levels = match_bookmark_levels(outline, lines)

    assert levels == {}


def test_raw_bookmark_depths_compress_to_contiguous_levels() -> None:
    """A document whose shallowest bookmark is depth 2 still starts at 1."""
    outline = [("Chapter One", 2), ("Overview", 3)]
    lines = ["Chapter One", "Overview"]

    levels = match_bookmark_levels(outline, lines)

    assert levels == {0: 1, 1: 2}

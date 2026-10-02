"""Font-size/weight/case heading ranking, on plain style records.

No pypdf import here -- ``rank_heading_styles`` takes plain ``LineStyle``
records, kept separate from the pypdf-driven visitor pass that produces
them from a real page (see ``test_document_ingest_pdf.py``).
"""

from app.pdf import LineStyle, rank_heading_styles


def test_larger_size_ranks_above_smaller_size() -> None:
    styles = {
        0: LineStyle(size=24.0, bold=False, all_caps=False),
        1: LineStyle(size=14.0, bold=False, all_caps=False),
        2: LineStyle(size=18.0, bold=False, all_caps=False),
    }
    body_size = 10.0

    levels = rank_heading_styles(styles, body_size)

    assert levels[0] < levels[2] < levels[1]


def test_near_equal_sizes_merge_into_one_cluster() -> None:
    """A couple of points of glyph-measurement noise must not invent levels.

    18.0 and 17.6 are the same nominal heading size measured on two lines
    with different descenders; they must land at the same level, while
    12.0 (clearly the body-adjacent tier) stays distinct.
    """
    styles = {
        0: LineStyle(size=18.0, bold=False, all_caps=False),
        1: LineStyle(size=17.6, bold=False, all_caps=False),
        2: LineStyle(size=12.0, bold=False, all_caps=False),
    }
    body_size = 10.0

    levels = rank_heading_styles(styles, body_size)

    assert levels[0] == levels[1]
    assert levels[0] < levels[2]


def test_bold_ranks_above_regular_at_the_same_size() -> None:
    styles = {
        0: LineStyle(size=14.0, bold=True, all_caps=False),
        1: LineStyle(size=14.0, bold=False, all_caps=False),
    }

    levels = rank_heading_styles(styles, body_size=10.0)

    assert levels[0] < levels[1]


def test_all_caps_ranks_above_mixed_case_at_the_same_size_and_weight() -> None:
    styles = {
        0: LineStyle(size=14.0, bold=False, all_caps=True),
        1: LineStyle(size=14.0, bold=False, all_caps=False),
    }

    levels = rank_heading_styles(styles, body_size=10.0)

    assert levels[0] < levels[1]


def test_a_line_at_or_below_body_size_is_not_a_heading_candidate() -> None:
    """Style detection only fires strictly above the body's own size.

    A shorter line at body size or smaller (a caption, a footnote) is not
    a heading just because it happens to be short.
    """
    styles = {
        0: LineStyle(size=18.0, bold=False, all_caps=False),
        1: LineStyle(size=10.0, bold=False, all_caps=False),
        2: LineStyle(size=8.0, bold=False, all_caps=False),
    }

    levels = rank_heading_styles(styles, body_size=10.0)

    assert set(levels) == {0}

"""PDF heading recovery from font styles, numbering and bookmark matches."""

from app.pdf import (
    LineStyle,
    _pool_bookmark_levels,
    infer_numbering_levels,
    rank_heading_styles,
    raw_bookmark_matches,
)


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


def test_exact_title_match_takes_the_bookmark_depth() -> None:
    outline = [("Introduction", 1), ("Background", 2), ("Methods", 1)]
    lines = ["Introduction", "Some prose.", "Background", "Methods"]

    levels = raw_bookmark_matches(outline, lines)

    assert levels[0] == levels[3]
    assert levels[0] < levels[2]


def test_numbering_marker_on_the_page_is_ignored_when_matching() -> None:
    """A bookmark titled "Background" still matches "1.1 Background"."""
    outline = [("Background", 1)]
    lines = ["1.1 Background"]

    levels = raw_bookmark_matches(outline, lines)

    assert levels == {0: 1}


def test_unmatched_bookmark_contributes_nothing() -> None:
    outline = [("Nonexistent Section", 1)]
    lines = ["Introduction", "Methods"]

    levels = raw_bookmark_matches(outline, lines)

    assert levels == {}


def test_raw_bookmark_depths_compress_to_contiguous_levels() -> None:
    """A document whose shallowest bookmark is depth 2 still starts at 1."""
    outline = [("Chapter One", 2), ("Overview", 3)]
    lines = ["Chapter One", "Overview"]

    levels = _pool_bookmark_levels(
        [(title, depth, 0) for title, depth in outline], [lines]
    )

    assert levels == {(0, 0): 1, (0, 1): 2}


def test_dotted_decimal_depth_maps_directly_to_level() -> None:
    """1. / 1.1 / 1.1.1 form three nested levels, in that order."""
    lines = ["1. Introduction", "1.1 Background", "1.1.1 Prior work"]

    levels = infer_numbering_levels(lines)

    assert levels == {0: 1, 1: 2, 2: 3}


def test_part_keyword_outranks_arabic_numbering() -> None:
    """PART I sits above a plain arabic section in the family order."""
    lines = ["PART I", "1. Scope", "PART II", "2. Definitions"]

    levels = infer_numbering_levels(lines)

    assert levels[0] == levels[2] == 1
    assert levels[1] == levels[3] == 2


def test_alpha_and_roman_parenthetical_markers_rank_below_arabic() -> None:
    """(a) and (i) sit deeper than a leading arabic section marker.

    A second Roman marker ("(ii)") is unambiguous, which is what tips the
    single-letter "(i)" into the Roman family rather than the alpha one
    "(a)" already established -- ambiguity resolution reads the whole
    document's markers, not just one line at a time.
    """
    lines = [
        "1. Scope",
        "(a) First clause",
        "(i) Sub-clause",
        "(ii) Another sub-clause",
    ]

    levels = infer_numbering_levels(lines)

    assert levels[0] < levels[1] < levels[2] == levels[3]


def test_ambiguous_single_letter_resolves_by_document_context() -> None:
    """A lone 'II.' reads as Roman when unambiguous Roman siblings exist."""
    lines = ["I. First part", "II. Second part", "III. Third part"]

    levels = infer_numbering_levels(lines)

    # All three are the same family/depth, so they compress to one level.
    assert levels == {0: 1, 1: 1, 2: 1}


def test_lines_without_a_recognizable_marker_are_absent() -> None:
    """A plain sentence carries no numbering signal at all."""
    lines = ["1. Introduction", "This is ordinary prose, not a heading."]

    levels = infer_numbering_levels(lines)

    assert levels == {0: 1}


def test_empty_and_blank_lines_are_ignored() -> None:
    assert infer_numbering_levels(["", "   ", "1. Scope"]) == {2: 1}

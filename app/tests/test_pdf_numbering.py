"""Outline/legal numbering marker parsing, on plain strings only.

No pypdf import anywhere in this module or the one under test -- these
cases must never be able to touch the stub-``pypdf`` trap that the other
PDF tests rely on (see ``test_document_upload.py``).
"""

from app.pdf import infer_numbering_levels


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

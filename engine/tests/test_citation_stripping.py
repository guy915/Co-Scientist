"""Tests for stripping a retrieved paper's own inline citation markers.

Retrieved abstracts/fulltext carry the source paper's citation markers
("(Smith et al. 2019)", "[12]") inline. Left in, a drafting model can
copy one into its own prose -- a real-looking reference attached to a
claim the cited source never made. ``strip_citation_markers`` removes
those shapes before text enters a prompt; it must never touch storage,
and it must never eat our own ``[C<n>]`` reference keys.

Author-year cases mirror paper-qa's ``strip_citations`` unit tests
verbatim (Apache-2.0, see engine/AGENTS.md), including the leftover
double spaces its regex leaves behind.
"""

from co_scientist.constants import strip_citation_markers


def test_author_et_al_year_stripped() -> None:
    text = "Recent studies (Smith et al. 1999) show that this is true."
    assert (
        strip_citation_markers(text)
        == "Recent studies  show that this is true."
    )


def test_author_and_author_year_stripped() -> None:
    text = "The method was adopted by (Smith, 1999, 2001; Johnson, 2002)."
    assert strip_citation_markers(text) == "The method was adopted by ."


def test_bare_author_et_al_year_stripped() -> None:
    """The name-outside-parens shape, e.g. 'Smith et al. (2019)'.

    This is the first regex alternative (paper-qa's own); every other
    author-year test here exercises the second (parenthesized) one, so
    this is the only test that would notice the first alternative going
    missing.
    """
    text = "Smith et al. (2019) first proposed this mechanism."
    assert strip_citation_markers(text) == " first proposed this mechanism."


def test_and_joined_authors_year_stripped() -> None:
    text = "This was shown by (Smith and Jones, 2021)."
    assert strip_citation_markers(text) == "This was shown by ."


def test_numeric_bracket_single_stripped() -> None:
    text = "This mechanism was shown previously [12]."
    assert (
        strip_citation_markers(text) == "This mechanism was shown previously ."
    )


def test_numeric_bracket_list_stripped() -> None:
    text = "Multiple groups reported this [3,4]."
    assert strip_citation_markers(text) == "Multiple groups reported this ."


def test_our_own_reference_key_not_stripped() -> None:
    text = "This is supported by prior work [C1] and [C12]."
    assert strip_citation_markers(text) == text


def test_parenthetical_without_year_not_stripped() -> None:
    text = "Full protocol details are provided (see Methods)."
    assert strip_citation_markers(text) == text


def test_no_citations_unchanged() -> None:
    text = "There are no references in this text."
    assert strip_citation_markers(text) == text

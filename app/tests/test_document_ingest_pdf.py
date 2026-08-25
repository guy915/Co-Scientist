"""Heading inference driven through the real pypdf parser, end to end.

``test_document_upload.py`` fakes ``pypdf`` wholesale for its own tests,
which would let a heading-inference suite pass identically whether or not
the feature works on a real file. These tests build small real PDFs from
raw PDF syntax (see ``_pdf_fixtures.py``) and drive them through
``document_ingest._extract_pdf`` unpatched, so the cascade is proven wired
to something, not just internally consistent.
"""

from app.document_ingest import _extract_pdf
from tests._pdf_fixtures import build_pdf


def test_bookmark_outline_sets_heading_levels() -> None:
    """A top-level and a nested bookmark produce h1 and h2 respectively.

    Both lines are also plain, unstyled body-size text with no numbering
    marker, so a passing result proves the bookmark signal fired on its
    own rather than piggybacking on numbering or size.
    """
    pdf = build_pdf(
        [
            [
                ("Overview", "F1", 10, 50, 450),
                ("Some introductory prose.", "F1", 10, 50, 430),
                ("Scope", "F1", 10, 50, 410),
                ("More prose about the scope.", "F1", 10, 50, 390),
            ]
        ],
        outline=[("Overview", 0), ("Scope", 0)],
    )

    text = _extract_pdf(pdf)

    assert "# Overview" in text
    assert "# Scope" in text
    assert "## " not in text  # both bookmarks sit at the same, top depth


def test_numbering_without_an_outline_sets_nested_heading_levels() -> None:
    """1. / 1.1 numbering alone infers a two-level hierarchy."""
    pdf = build_pdf(
        [
            [
                ("1. Introduction", "F1", 10, 50, 450),
                ("Prose under the top section.", "F1", 10, 50, 430),
                ("1.1 Background", "F1", 10, 50, 410),
                ("Prose under the sub-section.", "F1", 10, 50, 390),
            ]
        ]
    )

    text = _extract_pdf(pdf)

    assert "# 1. Introduction" in text
    assert "## 1.1 Background" in text


def test_larger_font_infers_a_heading_with_no_outline_or_numbering() -> None:
    """A visually larger, bold line stands out from uniform body text.

    Several same-size body lines are included so the body-size estimate
    (the font size most lines share) is unambiguous -- a single heading
    against a single body line would tie, which no real document does.
    """
    pdf = build_pdf(
        [
            [
                ("Results", "F2", 20, 50, 460),
                ("The assay showed a clear effect.", "F1", 10, 50, 430),
                ("A second sentence of the same paragraph.", "F1", 10, 50, 410),
                ("A third sentence, still body text.", "F1", 10, 50, 390),
            ]
        ]
    )

    text = _extract_pdf(pdf)

    assert "# Results" in text
    assert "The assay showed a clear effect." in text


def test_uniform_font_with_no_signal_extracts_exactly_as_before() -> None:
    """No outline, no numbering, one font size: byte-identical output.

    This is the fail-soft floor -- heading inference must never change a
    document that gives it nothing to infer from.
    """
    lines: list[tuple[str, str, float, float, float]] = [
        ("A plain narrative paragraph about the assay.", "F1", 10, 50, 450),
        ("A second plain paragraph, same size.", "F1", 10, 50, 430),
    ]
    pdf = build_pdf([lines])

    text = _extract_pdf(pdf)

    assert "#" not in text
    assert "A plain narrative paragraph about the assay." in text
    assert "A second plain paragraph, same size." in text

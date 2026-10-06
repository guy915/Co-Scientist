from __future__ import annotations

import io

import pytest
from pypdf import PdfReader, PdfWriter

from app.document_ingest import _extract_pdf
from app.pdf import (
    LineStyle,
    infer_numbering_levels,
    rank_heading_styles,
)

Line = tuple[str, str, float, float, float]


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[Line]) -> bytes:
    ops = [
        f"BT /{font} {size} Tf {x} {y} Td ({_escape(text)}) Tj ET"
        for text, font, size, x, y in lines
    ]
    return "\n".join(ops).encode("latin-1")


def _page_object(content_num: int, font_nums: dict[str, int]) -> bytes:
    fonts = " ".join(f"/{name} {num} 0 R" for name, num in font_nums.items())
    return (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 500] "
        f"/Resources << /Font << {fonts} >> >> "
        f"/Contents {content_num} 0 R >>"
    ).encode("latin-1")


def _build_objects(
    pages_lines: list[list[Line]],
) -> tuple[dict[int, bytes], list[int]]:
    font_nums = {"F1": 100, "F2": 101}
    objects: dict[int, bytes] = {
        100: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        101: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    }
    page_nums: list[int] = []
    next_num = 10
    for lines in pages_lines:
        page_num, content_num = next_num, next_num + 1
        next_num += 2
        page_nums.append(page_num)
        stream = _content_stream(lines)
        objects[content_num] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            + stream
            + b"\nendstream"
        )
        objects[page_num] = _page_object(content_num, font_nums)
    kids = " ".join(f"{n} 0 R" for n in page_nums)
    objects[2] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>"
    ).encode("latin-1")
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    return objects, page_nums


def _serialize(objects: dict[int, bytes]) -> bytes:
    # Compute PDF offsets from real bytes; hand-counted offsets are fragile.
    all_nums = sorted(objects)
    max_num = max(all_nums)
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in all_nums:
        offsets[num] = buf.tell()
        buf.write(f"{num} 0 obj\n".encode("latin-1"))
        buf.write(objects[num])
        buf.write(b"\nendobj\n")
    xref_offset = buf.tell()
    buf.write(f"xref\n0 {max_num + 1}\n".encode("latin-1"))
    buf.write(b"0000000000 65535 f \n")
    for num in range(1, max_num + 1):
        buf.write(f"{offsets.get(num, 0):010d} 00000 n \n".encode("latin-1"))
    buf.write(
        (
            f"trailer\n<< /Size {max_num + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("latin-1")
    )
    return buf.getvalue()


def build_pdf(
    pages_lines: list[list[Line]],
    outline: list[tuple[str, int]] | None = None,
) -> bytes:
    objects, _ = _build_objects(pages_lines)
    raw = _serialize(objects)
    if not outline:
        return raw

    reader = PdfReader(io.BytesIO(raw))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    for title, page_index in outline:
        writer.add_outline_item(title, page_index)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# Use the real PDF parser so a fake cannot hide missing wiring.


def test_bookmark_outline_sets_heading_levels() -> None:
    # Use uniform unnumbered body text to isolate bookmark headings.
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
    assert "## " not in text


def test_numbering_without_an_outline_sets_nested_heading_levels() -> None:
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
    # Uniform body lines disambiguate body-size estimation from headings.
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
    # PDF ingestion must leave output unchanged when no heading signals exist.
    lines: list[tuple[str, str, float, float, float]] = [
        ("A plain narrative paragraph about the assay.", "F1", 10, 50, 450),
        ("A second plain paragraph, same size.", "F1", 10, 50, 430),
    ]
    pdf = build_pdf([lines])

    text = _extract_pdf(pdf)

    assert "#" not in text
    assert "A plain narrative paragraph about the assay." in text
    assert "A second plain paragraph, same size." in text


def _styles(*specs: tuple[float, bool, bool]) -> dict[int, LineStyle]:
    return {
        index: LineStyle(size=size, bold=bold, all_caps=caps)
        for index, (size, bold, caps) in enumerate(specs)
    }


@pytest.mark.parametrize(
    ("styles", "levels"),
    [
        (
            _styles((24, False, False), (14, False, False), (18, False, False)),
            {0: 1, 1: 3, 2: 2},
        ),
        # Glyph measurement noise must not split one heading level.
        (
            _styles(
                (18, False, False), (17.6, False, False), (12, False, False)
            ),
            {0: 1, 1: 1, 2: 2},
        ),
        # Small captions and footnotes are not headings.
        (
            _styles((18, False, False), (10, False, False), (8, False, False)),
            {0: 1},
        ),
    ],
    ids=["size", "near-equal-sizes", "at-or-below-body"],
)
def test_heading_styles_rank_by_size_weight_and_case(
    styles: dict[int, LineStyle], levels: dict[int, int]
) -> None:
    assert rank_heading_styles(styles, body_size=10.0) == levels


@pytest.mark.parametrize(
    ("lines", "levels"),
    [
        (
            ["1. Introduction", "1.1 Background", "1.1.1 Prior work"],
            {0: 1, 1: 2, 2: 3},
        ),
        (
            ["PART I", "1. Scope", "PART II", "2. Definitions"],
            {0: 1, 1: 2, 2: 1, 3: 2},
        ),
        # A second Roman numeral disambiguates the first marker from alphabetic
        # numbering.
        (
            [
                "1. Scope",
                "(a) First clause",
                "(i) Sub-clause",
                "(ii) Another sub-clause",
            ],
            {0: 1, 1: 2, 2: 3, 3: 3},
        ),
        (
            ["I. First part", "II. Second part", "III. Third part"],
            {0: 1, 1: 1, 2: 1},
        ),
        (["1. Introduction", "Ordinary prose, not a heading."], {0: 1}),
        (["", "   ", "1. Scope"], {2: 1}),
    ],
    ids=[
        "dotted-decimal",
        "part-keyword",
        "alpha-and-roman",
        "ambiguous-single-letter",
        "prose-absent",
        "blank-lines",
    ],
)
def test_numbering_markers_infer_heading_levels(
    lines: list[str], levels: dict[int, int]
) -> None:
    assert infer_numbering_levels(lines) == levels

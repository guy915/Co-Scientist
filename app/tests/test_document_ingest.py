from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter

from app.document_ingest import _extract_pdf
from app.pdf import (
    LineStyle,
    _pool_bookmark_levels,
    infer_numbering_levels,
    rank_heading_styles,
    raw_bookmark_matches,
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
    # Glyph measurement noise must not split one heading level.
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
    # Small captions and footnotes are not headings.
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
    outline = [("Chapter One", 2), ("Overview", 3)]
    lines = ["Chapter One", "Overview"]

    levels = _pool_bookmark_levels(
        [(title, depth, 0) for title, depth in outline], [lines]
    )

    assert levels == {(0, 0): 1, (0, 1): 2}


def test_dotted_decimal_depth_maps_directly_to_level() -> None:
    lines = ["1. Introduction", "1.1 Background", "1.1.1 Prior work"]

    levels = infer_numbering_levels(lines)

    assert levels == {0: 1, 1: 2, 2: 3}


def test_part_keyword_outranks_arabic_numbering() -> None:
    lines = ["PART I", "1. Scope", "PART II", "2. Definitions"]

    levels = infer_numbering_levels(lines)

    assert levels[0] == levels[2] == 1
    assert levels[1] == levels[3] == 2


def test_alpha_and_roman_parenthetical_markers_rank_below_arabic() -> None:
    # A second Roman numeral disambiguates the first marker from alphabetic
    # numbering.
    lines = [
        "1. Scope",
        "(a) First clause",
        "(i) Sub-clause",
        "(ii) Another sub-clause",
    ]

    levels = infer_numbering_levels(lines)

    assert levels[0] < levels[1] < levels[2] == levels[3]


def test_ambiguous_single_letter_resolves_by_document_context() -> None:
    lines = ["I. First part", "II. Second part", "III. Third part"]

    levels = infer_numbering_levels(lines)

    assert levels == {0: 1, 1: 1, 2: 1}


def test_lines_without_a_recognizable_marker_are_absent() -> None:
    lines = ["1. Introduction", "This is ordinary prose, not a heading."]

    levels = infer_numbering_levels(lines)

    assert levels == {0: 1}


def test_empty_and_blank_lines_are_ignored() -> None:
    assert infer_numbering_levels(["", "   ", "1. Scope"]) == {2: 1}

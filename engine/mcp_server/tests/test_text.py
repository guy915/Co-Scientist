"""Tests for plain-text metadata and PMC fulltext rendering."""

from typing import Any

import pytest
from mcp_server.text_extraction import extract_text_from_pmc_html
from mcp_server.tools.text import clean_markup


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Both encodings of the same real Europe PMC title.
        (
            "Colistin resistance in <i>Klebsiella pneumoniae</i>",
            "Colistin resistance in Klebsiella pneumoniae",
        ),
        (
            "Sphingosine against &lt;i&gt;Pseudomonas aeruginosa&lt;/i&gt;",
            "Sphingosine against Pseudomonas aeruginosa",
        ),
        # A structured abstract's section headers are block-level: dropping
        # them without a space would run "Aims" into the sentence after it.
        ("<h4>Aims</h4>The convergence of", "Aims The convergence of"),
        # An inline tag closes up: bla<sub>NDM</sub> is one gene name.
        ("bla<sub>NDM-1</sub> carriage", "blaNDM-1 carriage"),
        ("Trials &amp; results", "Trials & results"),
        # Europe PMC pads abbreviated species names with zero-width spaces.
        ("(<i>K. pneumoniae</i>\u200b\u200b)", "(K. pneumoniae)"),
        ("line one\n\n  line two", "line one line two"),
        # Entities that are not markup decode to the character they name.
        ("growth at p &lt; 0.05 in group A", "growth at p < 0.05 in group A"),
        (None, ""),
        ("", ""),
        (123, ""),
    ],
)
def test_clean_markup(raw: Any, expected: str) -> None:
    assert clean_markup(raw) == expected


def test_clean_markup_leaves_a_comparison_shaped_like_a_tag_intact() -> None:
    """A decoded comparison whose operands spell a tag name is still text.

    "p &lt;b and q&gt; r" decodes to "p <b and q> r", which reads as an
    opening tag with attributes to anything matching loosely. Deleting it
    would take the clause with it, so only bare tags are stripped.
    """
    raw = "holds for p &lt;b and q&gt; r"

    assert clean_markup(raw) == "holds for p <b and q> r"


def test_clean_markup_leaves_comparisons_intact() -> None:
    """A decoded "<" is text, not a tag, so a comparison survives.

    Stripping anything between angle brackets would eat the span between a
    "less than" and the next ">" -- in an abstract that silently deletes a
    clause. Only the formatting tags publishers actually send are removed.
    """
    raw = "significant at p&lt;0.05 while A&gt;B held"

    assert clean_markup(raw) == "significant at p<0.05 while A>B held"


def test_pmc_rendering_keeps_abstract_and_section_paragraphs() -> None:
    xml = """<article>
      <abstract><p>First <i>abstract</i>.</p><p>Second.</p></abstract>
      <body>
        <sec><title>Methods</title>
          <boxed-text><p>Boxed.</p></boxed-text><p>Direct.</p>
          <fig><p>Figure caption.</p></fig>
          <sec><title>Subsection</title><p>Nested.</p></sec>
        </sec>
        <sec><p>Unlabelled.</p></sec>
        <sec><title>Empty</title><sec><p>Nested only.</p></sec></sec>
      </body>
      <back><ref-list><p>References.</p></ref-list></back>
    </article>"""
    assert extract_text_from_pmc_html(xml) == (
        "# abstract\n\nFirstabstract.\n\nSecond.\n\n"
        "## Methods\n\nDirect.\n\nBoxed.\n\n## section\n\nUnlabelled."
    )


@pytest.mark.parametrize(
    "xml,expected",
    [
        ("<article/>", ""),
        (
            "<abstract>Plain abstract.</abstract>",
            "# abstract\n\nPlain abstract.",
        ),
        ("<abstract><p/></abstract>", ""),
    ],
)
def test_pmc_rendering_handles_sparse_articles(xml: str, expected: str) -> None:
    assert extract_text_from_pmc_html(xml) == expected


@pytest.mark.parametrize("max_chars", [0, 25, 200_000])
def test_pmc_sections_preserve_the_corpus_format(max_chars: int) -> None:
    """PMC keeps abstracts, sections, and boxed paragraphs without clutter."""
    article = """<article>
        <abstract><p>Abstract one.</p><p>Abstract two.</p></abstract>
        <body><sec><title>Methods</title>
            <p>First.</p><boxed-text><p>Boxed.</p></boxed-text><p>Second.</p>
            <sec><title>Nested</title><p>Subsection.</p></sec>
            <fig><p>Figure caption.</p></fig>
            <table-wrap><p>Table caption.</p></table-wrap>
        </sec><sec><label>Conclusion</label><p>Done.</p></sec></body>
        <back><p>References.</p></back>
    </article>"""
    expected = (
        "# abstract\n\nAbstract one.\n\nAbstract two.\n\n"
        "## Methods\n\nFirst.\n\nSecond.\n\nBoxed.\n\n"
        "## Conclusion\n\nDone."
    )
    if len(expected) > max_chars:
        expected = expected[:max_chars] + "\n\n[... truncated for length ...]"
    assert extract_text_from_pmc_html(article, max_chars) == expected

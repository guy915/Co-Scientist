"""Tests for the shared markup cleaner used by the literature sources.

Publishers send formatting inside titles and abstracts -- Europe PMC and
PubMed both italicize species and gene names -- and Europe PMC sends some
of it escaped, so the same title can arrive as `<i>` or as `&lt;i&gt;`.
Whatever the encoding, an agent reading a record must see plain text.
"""

from typing import Any

import pytest
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

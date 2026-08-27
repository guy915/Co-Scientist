"""Plain-text normalization for text that arrives carrying markup.

Publishers format inside their metadata: Europe PMC and PubMed both send
titles and abstracts containing `<i>` around species and gene names, `<b>`
and `<h4>` around a structured abstract's section headers, `<sup>`/`<sub>`
inside gene symbols. Europe PMC additionally sends some records with that
markup escaped, so the same field can arrive as `<i>` or as `&lt;i&gt;`.
An agent quoting a title reads it as text, so it has to be text.

Only the tags publishers actually send are removed, rather than everything
between angle brackets. Entities are decoded first, which turns `&lt;` in
"p &lt; 0.05" into a bare "<" -- a generic strip would then delete from
there to the next ">", silently removing a clause from an abstract.
"""

import html
import re
from typing import Any

# Block-level markup becomes a space: "<h4>Aims</h4>The convergence" must
# not close up into "AimsThe".
_BLOCK_TAG_RE = re.compile(r"</?(?:p|br|div|h[1-6])\b[^>]*>", re.IGNORECASE)

# Inline markup closes up instead: bla<sub>NDM-1</sub> is one gene name,
# and splitting it would break the string a citation is matched on.
_INLINE_TAG_RE = re.compile(
    r"</?(?:i|b|em|strong|u|sup|sub|sc|italic|bold|underline)\b[^>]*>",
    re.IGNORECASE,
)

# Zero-width characters survive a whitespace collapse (they are not
# whitespace) and reach the model as invisible tokens inside a term; Europe
# PMC sends runs of them around abbreviated species names. Deleted rather
# than replaced with a space, since a zero-width break inside a long word is
# a hint about where to wrap, not a word boundary.
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\ufeff]")

_WHITESPACE_RE = re.compile(r"\s+")


def clean_markup(raw: Any) -> str:
    """Renders one metadata field as plain text.

    Args:
        raw: Title or abstract text from a literature source, possibly
            carrying markup in either encoding.

    Returns:
        Plain text with formatting tags removed, entities decoded, and runs
        of whitespace collapsed. Empty string for missing or non-string
        input.
    """
    if not isinstance(raw, str) or not raw:
        return ""
    # Decode first so escaped and unescaped markup meet the same strip.
    text = _BLOCK_TAG_RE.sub(" ", html.unescape(raw))
    text = _ZERO_WIDTH_RE.sub("", _INLINE_TAG_RE.sub("", text))
    return _WHITESPACE_RE.sub(" ", text).strip()

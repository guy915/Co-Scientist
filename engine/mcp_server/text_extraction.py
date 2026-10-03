"""Plain-text metadata normalization and structured fulltext extraction."""

import html
import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# Block-level markup becomes a space: "<h4>Aims</h4>The convergence" must
# not close up into "AimsThe".
_BLOCK_TAG_RE = re.compile(r"</?(?:p|br|div|h[1-6])\s*/?>", re.IGNORECASE)

# Inline markup closes up instead: bla<sub>NDM-1</sub> is one gene name,
# and splitting it would break the string a citation is matched on.
_INLINE_TAG_RE = re.compile(
    r"</?(?:i|b|em|strong|u|sup|sub|sc|italic|bold|underline)\s*/?>",
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


def _build_section_block(section: Tag) -> str | None:
    """Render a section's paragraphs, excluding its nested subsections."""
    if section.parent is None or section.parent.name == "sec":
        return None
    paragraphs = [
        text
        for paragraph in section.find_all("p", recursive=False)
        if (text := paragraph.get_text(strip=True))
    ]
    # Direct paragraphs precede paragraphs in boxed/supplementary containers.
    for child in section.children:
        if isinstance(child, Tag) and child.name not in (
            "sec",
            "title",
            "label",
        ):
            paragraphs.extend(
                text
                for paragraph in child.find_all("p")
                if (text := paragraph.get_text(strip=True))
            )
    if not paragraphs:
        return None
    heading = section.find(["title", "label"])
    heading_text = heading.get_text(strip=True) if heading else "section"
    content = "\n\n".join(paragraphs)
    return f"## {heading_text}\n\n{content}"


def truncate_markdown(markdown: str, max_chars: int) -> str:
    """Truncates markdown text to max_chars, logging if truncation occurs.

    Public because the web extractors reuse it, keeping one truncation
    marker across the server.

    Args:
        markdown: Markdown text to (possibly) truncate.
        max_chars: Maximum characters to keep. Bounds the amount of text
            handed to the LLM agent per article (default 200k chars) to
            keep prompt size manageable regardless of how long the source
            paper is.

    Returns:
        The original text, or the text truncated to max_chars with a
        trailing truncation marker appended.
    """
    if len(markdown) > max_chars:
        logger.info(
            "Truncating extracted text from %s to %s chars",
            len(markdown),
            max_chars,
        )
        return markdown[:max_chars] + "\n\n[... truncated for length ...]"
    return markdown


def _pmc_html_to_markdown(html_content: str, max_chars: int) -> str:
    """Parse PMC JATS XML and render the abstract and top-level sections."""
    soup = BeautifulSoup(html_content, "lxml-xml")
    for tag in soup.find_all(
        ["back", "ref-list", "ack", "fn-group", "fig", "table-wrap"]
    ):
        tag.decompose()

    parts = []
    abstract = soup.find("abstract")
    if abstract:
        paragraphs = abstract.find_all("p")
        abstract_text = (
            "\n\n".join(p.get_text(strip=True) for p in paragraphs)
            if paragraphs
            else abstract.get_text(strip=True)
        )
        if abstract_text:
            parts.append(f"# abstract\n\n{abstract_text}")
    body = soup.find("body")
    if body:
        parts.extend(
            block
            for section in body.find_all("sec")
            if (block := _build_section_block(section))
        )
    return truncate_markdown("\n\n".join(parts), max_chars)


def extract_text_from_pmc_html(
    html_content: str, max_chars: int = 200_000
) -> str:
    """Converts PMC HTML fulltext to clean markdown.

    Preserves:
    - section headings (abstract, introduction, methods, results, discussion)
    - paragraphs within sections
    - key structure for agent readability

    Removes:
    - XML/HTML tags
    - references section (citation clutter)
    - author affiliations and metadata
    - figure/table captions (images not useful in text)
    - acknowledgments and funding

    Args:
        html_content: Raw PMC HTML/XML content.
        max_chars: Maximum characters to return (truncate if exceeded).

    Returns:
        Markdown-formatted text ready for LLM consumption.
    """
    try:
        return _pmc_html_to_markdown(html_content, max_chars)
    except Exception as exc:
        logger.error("Failed to extract text from PMC HTML: %s", exc)
        # Retain readable text when structured extraction fails.
        try:
            text = BeautifulSoup(html_content, "lxml-xml").get_text(
                separator="\n", strip=True
            )
            return truncate_markdown(text, max_chars)
        except Exception as fallback_error:
            logger.error(
                "Fallback text extraction also failed: %s", fallback_error
            )
            return "[error: could not extract text from HTML]"

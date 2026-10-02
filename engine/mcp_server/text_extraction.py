"""Extracts clean text from PMC HTML fulltext for agent consumption.

Converts PMC XML/HTML to markdown format, preserving structure while
removing clutter like references, figure captions, and metadata.
"""

import logging

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


def _extract_abstract_text(soup: BeautifulSoup) -> str:
    """Extracts the abstract's text content from a parsed PMC document.

    Args:
        soup: Parsed PMC document (JATS XML) with back-matter tags already
            removed.

    Returns:
        The abstract text, or an empty string if no ``<abstract>`` tag is
        present.
    """
    abstract_text = ""
    abstract = soup.find("abstract")
    if abstract:
        paragraphs = abstract.find_all("p")
        if paragraphs:
            abstract_text = "\n\n".join(
                p.get_text(strip=True) for p in paragraphs
            )
        else:
            # Sometimes abstract is just text without paragraphs
            # (no <p> wrapper), so fall back to the raw text content.
            abstract_text = abstract.get_text(strip=True)
    return abstract_text


def _extract_body_sections(soup: BeautifulSoup) -> list[str]:
    """Renders top-level sections, including paragraphs in boxed containers.

    Direct paragraphs precede container paragraphs; nested sections are
    excluded, matching the PMC corpus format consumed by the engine.

    Args:
        soup: Parsed JATS document with clutter removed.

    Returns:
        Markdown section blocks in document order.
    """
    body = soup.find("body")
    if not body:
        return []
    sections = []
    for section in body.find_all("sec"):
        if section.parent is None or section.parent.name == "sec":
            continue
        paragraphs = list(section.find_all("p", recursive=False))
        paragraphs.extend(
            p
            for child in section.children
            if isinstance(child, Tag)
            and child.name not in ("sec", "title", "label")
            for p in child.find_all("p")
        )
        content = "\n\n".join(
            text for p in paragraphs if (text := p.get_text(strip=True))
        )
        if content:
            heading = section.find(["title", "label"])
            title = heading.get_text(strip=True) if heading else "section"
            sections.append(f"## {title}\n\n{content}")
    return sections


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


def _fallback_extract_text(html_content: str, max_chars: int) -> str:
    """Strips all tags and returns plain text when structured parsing fails.

    Re-parses and just strips all tags, losing headings/structure but still
    yielding readable text instead of no content at all.

    Args:
        html_content: Raw PMC HTML/XML content.
        max_chars: Maximum characters to return (truncate if exceeded).

    Returns:
        Plain text extracted from the document, or an error placeholder
        string if even this fallback parse fails.
    """
    try:
        soup = BeautifulSoup(html_content, "lxml-xml")
        text = soup.get_text(separator="\n", strip=True)
        return truncate_markdown(text, max_chars)
    except Exception as fallback_error:
        logger.error("Fallback text extraction also failed: %s", fallback_error)
        return "[error: could not extract text from HTML]"


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
        soup = BeautifulSoup(html_content, "lxml-xml")
        for tag in soup.find_all(
            ["back", "ref-list", "ack", "fn-group", "fig", "table-wrap"]
        ):
            tag.decompose()
        parts = []
        abstract = _extract_abstract_text(soup)
        if abstract:
            parts.append(f"# abstract\n\n{abstract}")
        parts.extend(_extract_body_sections(soup))
        return truncate_markdown("\n\n".join(parts), max_chars)
    except Exception as e:
        # Structured extraction above assumes well-formed JATS XML; if the
        # document deviates (malformed XML, unexpected schema) fall back to
        # a plain-text dump below rather than failing the whole request.
        logger.error("Failed to extract text from PMC HTML: %s", e)
        return _fallback_extract_text(html_content, max_chars)

"""Extracts clean text from PMC HTML fulltext for agent consumption.

Converts PMC XML/HTML to markdown format, preserving structure while
removing clutter like references, figure captions, and metadata.
"""
# pylint: disable=inconsistent-quotes

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
    abstract = soup.find('abstract')
    if abstract:
        paragraphs = abstract.find_all('p')
        if paragraphs:
            abstract_text = '\n\n'.join(
                p.get_text(strip=True) for p in paragraphs)
        else:
            # Sometimes abstract is just text without paragraphs
            # (no <p> wrapper), so fall back to the raw text content.
            abstract_text = abstract.get_text(strip=True)
    return abstract_text


def _extract_section_text(section: Tag) -> list[str]:
    """Collects the direct-paragraph text of one top-level ``<sec>``.

    Args:
        section: A top-level ``<sec>`` tag (its immediate parent is not
            itself a ``<sec>``).

    Returns:
        List of paragraph text strings found directly within the section,
        excluding any nested subsections.
    """
    # Get direct paragraphs only (not from nested sections)
    body_paragraphs: list[str] = []
    for p in section.find_all('p', recursive=False):
        text = p.get_text(strip=True)
        if text:
            body_paragraphs.append(text)

    # Also check for paragraphs in direct children
    # (not nested sections). Catches <p> tags wrapped one
    # level deeper in a non-<sec> container (e.g. a boxed
    # text or supplementary block) that the recursive=False
    # scan above would miss, while still excluding 'sec'
    # children (subsections, handled/skipped above) and
    # 'title'/'label' (already consumed as the heading).
    for child in section.children:
        if isinstance(child,
                      Tag) and child.name not in ['sec', 'title', 'label']:
            for p in child.find_all('p'):
                text = p.get_text(strip=True)
                if text:
                    body_paragraphs.append(text)

    return body_paragraphs


def _extract_body_sections(soup: BeautifulSoup) -> list[str]:
    """Extracts each top-level body section as a markdown "## heading" block.

    Args:
        soup: Parsed PMC document (JATS XML) with back-matter tags already
            removed.

    Returns:
        List of markdown blocks, one per top-level section that has
        content, in document order.
    """
    sections = []
    body = soup.find('body')
    if body:
        # find_all with recursive=True returns every <sec> at any depth,
        # including nested subsections; the parent-check below filters
        # this down to top-level sections only (see next comment).
        for section in body.find_all('sec', recursive=True):
            # Get section heading
            heading = section.find(['title', 'label'])
            heading_text = heading.get_text(
                strip=True) if heading else "section"

            # Skip nested sections (we'll get them separately)
            # only process top-level sections: a <sec> whose immediate
            # parent is itself a <sec> is a subsection and is filtered
            # out here, so only sections attached directly to <body> (or
            # another non-<sec> container) become their own "## heading"
            # block.
            parent = section.parent
            if parent is not None and parent.name != 'sec':
                body_paragraphs = _extract_section_text(section)
                if body_paragraphs:
                    content = '\n\n'.join(body_paragraphs)
                    sections.append(f"## {heading_text}\n\n{content}")

    return sections


def _truncate_markdown(markdown: str, max_chars: int) -> str:
    """Truncates markdown text to max_chars, logging if truncation occurs.

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
        logger.info("Truncating extracted text from %s to %s chars",
                    len(markdown), max_chars)
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
    try:  # pylint: disable=broad-exception-caught
        soup = BeautifulSoup(html_content, 'lxml-xml')
        text = soup.get_text(separator='\n', strip=True)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[... truncated for length ...]"
        return text
    # pylint: disable-next=broad-exception-caught
    except Exception as fallback_error:
        logger.error("Fallback text extraction also failed: %s", fallback_error)
        return "[error: could not extract text from HTML]"


def extract_text_from_pmc_html(html_content: str,
                               max_chars: int = 200_000) -> str:
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
    try:  # pylint: disable=broad-exception-caught
        # PMC fulltext is JATS XML (a specific article-tag vocabulary), so
        # parse with the lxml-xml parser rather than an HTML parser.
        soup = BeautifulSoup(html_content, 'lxml-xml')

        # Remove sections we don't need. "back" holds trailing matter
        # (references/notes container), "ref-list" is the bibliography,
        # "ack" is acknowledgments, "fn-group" is footnotes, "fig" and
        # "table-wrap" are figure/table containers whose captions are not
        # useful as plain text and whose images cannot be rendered here.
        for tag in soup.find_all(
            ['back', 'ref-list', 'ack', 'fn-group', 'fig', 'table-wrap']):
            tag.decompose()

        abstract_text = _extract_abstract_text(soup)
        sections = _extract_body_sections(soup)

        # Combine abstract and body
        parts = []
        if abstract_text:
            parts.append(f"# abstract\n\n{abstract_text}")

        parts.extend(sections)

        markdown = '\n\n'.join(parts)

        return _truncate_markdown(markdown, max_chars)

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Structured extraction above assumes well-formed JATS XML; if the
        # document deviates (malformed XML, unexpected schema) fall back to
        # a plain-text dump below rather than failing the whole request.
        logger.error("Failed to extract text from PMC HTML: %s", e)
        return _fallback_extract_text(html_content, max_chars)

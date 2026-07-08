"""Extracts clean text from PMC HTML fulltext for agent consumption.

Converts PMC XML/HTML to markdown format, preserving structure while
removing clutter like references, figure captions, and metadata.
"""
# pylint: disable=inconsistent-quotes

import logging
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


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

        # Extract abstract
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

        # Extract main body sections
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
                        if isinstance(child, Tag) and child.name not in [
                                'sec', 'title', 'label'
                        ]:
                            for p in child.find_all('p'):
                                text = p.get_text(strip=True)
                                if text:
                                    body_paragraphs.append(text)

                    if body_paragraphs:
                        content = '\n\n'.join(body_paragraphs)
                        sections.append(f"## {heading_text}\n\n{content}")

        # Combine abstract and body
        parts = []
        if abstract_text:
            parts.append(f"# abstract\n\n{abstract_text}")

        parts.extend(sections)

        markdown = '\n\n'.join(parts)

        # Truncate if too long. max_chars bounds the amount of text handed
        # to the LLM agent per article (default 200k chars) to keep prompt
        # size manageable regardless of how long the source paper is.
        if len(markdown) > max_chars:
            logger.info("Truncating extracted text from %s to %s chars",
                        len(markdown), max_chars)
            markdown = (markdown[:max_chars] +
                        "\n\n[... truncated for length ...]")

        return markdown

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Structured extraction above assumes well-formed JATS XML; if the
        # document deviates (malformed XML, unexpected schema) fall back to
        # a plain-text dump below rather than failing the whole request.
        logger.error("Failed to extract text from PMC HTML: %s", e)
        # Fallback: return raw text extraction
        # Re-parse and just strip all tags, losing headings/structure but
        # still yielding readable text instead of no content at all.
        try:  # pylint: disable=broad-exception-caught
            soup = BeautifulSoup(html_content, 'lxml-xml')
            text = soup.get_text(separator='\n', strip=True)
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n[... truncated for length ...]"
            return text
        except Exception as fallback_error:  # pylint: disable=broad-exception-caught
            logger.error("Fallback text extraction also failed: %s",
                         fallback_error)
            return "[error: could not extract text from HTML]"

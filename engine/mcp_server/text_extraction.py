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
        soup = BeautifulSoup(html_content, 'lxml-xml')

        # Remove sections we don't need
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
                abstract_text = abstract.get_text(strip=True)

        # Extract main body sections
        sections = []
        body = soup.find('body')
        if body:
            for section in body.find_all('sec', recursive=True):
                # Get section heading
                heading = section.find(['title', 'label'])
                heading_text = heading.get_text(
                    strip=True) if heading else "section"

                # Skip nested sections (we'll get them separately)
                # only process top-level sections
                parent = section.parent
                if parent is not None and parent.name != 'sec':
                    # Get direct paragraphs only (not from nested sections)
                    body_paragraphs: list[str] = []
                    for p in section.find_all('p', recursive=False):
                        text = p.get_text(strip=True)
                        if text:
                            body_paragraphs.append(text)

                    # Also check for paragraphs in direct children
                    # (not nested sections)
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

        # Truncate if too long
        if len(markdown) > max_chars:
            logger.info("Truncating extracted text from %s to %s chars",
                        len(markdown), max_chars)
            markdown = (markdown[:max_chars] +
                        "\n\n[... truncated for length ...]")

        return markdown

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to extract text from PMC HTML: %s", e)
        # Fallback: return raw text extraction
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

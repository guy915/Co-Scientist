"""Convert fetched web documents into text an LLM can read cheaply.

Handing raw HTML to a model spends most of the token budget on navigation,
scripts, and boilerplate. Stripping to headings and body text cuts a typical
page by roughly an order of magnitude, which is the difference between a
usable tool and one that exhausts the context window on a single page.

The PMC-specific extractor in ``mcp_server.text_extraction`` parses JATS XML
and does not apply to arbitrary web pages, but its truncation helper is
reused here so the truncation marker stays consistent across the server.
"""

import io
import logging
from typing import Any

from bs4 import BeautifulSoup

from mcp_server.text_extraction import truncate_markdown

logger = logging.getLogger(__name__)

# Page furniture that carries no article content.
_CHROME_TAGS = (
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "noscript",
    "iframe",
    "svg",
)

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_BLOCK_TAGS = (*_HEADING_TAGS, "p", "li", "blockquote", "pre")


def _block_to_markdown(element: Any) -> str:
    """Renders one block-level element as a markdown line.

    Args:
        element: A BeautifulSoup tag drawn from the block allowlist.

    Returns:
        The element's text, prefixed with markdown syntax for headings and
        list items, or "" when the element has no text.
    """
    text = str(element.get_text(separator=" ", strip=True))
    if not text:
        return ""
    name = element.name
    if name in _HEADING_TAGS:
        return f"{'#' * int(name[1])} {text}"
    if name == "li":
        return f"- {text}"
    if name == "blockquote":
        return f"> {text}"
    return text


def _strip_chrome_tags(soup: Any) -> None:
    """Removes page furniture tags from a parsed document, in place.

    Args:
        soup: The parsed document.
    """
    # One traversal for every chrome tag; find_all accepts a name list.
    for tag in soup.find_all(list(_CHROME_TAGS)):
        tag.decompose()


def _select_root(soup: Any) -> Any:
    """Picks the element most likely to hold the article body.

    Args:
        soup: The parsed document, with chrome tags already stripped.

    Returns:
        The first of ``<article>``, ``<main>``, or ``<body>`` that is
        present, falling back to the whole document.
    """
    return soup.find("article") or soup.find("main") or soup.body or soup


def _extract_block_lines(root: Any) -> list[str]:
    """Renders every allowlisted block element under root as markdown.

    Args:
        root: The element selected by ``_select_root``.

    Returns:
        One markdown line per non-empty block element, in document order.
    """
    lines = []
    for element in root.find_all(_BLOCK_TAGS):
        line = _block_to_markdown(element)
        if line:
            lines.append(line)
    return lines


def extract_text_from_html(html: str, max_chars: int = 50_000) -> str:
    """Converts an HTML page to compact markdown.

    Args:
        html: Raw HTML document.
        max_chars: Maximum characters to return before truncating.

    Returns:
        Markdown text with headings and paragraphs preserved and page
        furniture removed. Falls back to a plain tag strip if structured
        extraction yields nothing, and to an error placeholder if parsing
        fails outright.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        logger.warning("HTML parse failed: %s", exc)
        return "[error: could not parse HTML]"

    _strip_chrome_tags(soup)
    root = _select_root(soup)
    text = "\n\n".join(_extract_block_lines(root))
    if not text.strip():
        # Pages built entirely from divs yield no allowlisted blocks;
        # a flat text dump still beats returning nothing.
        text = root.get_text(separator="\n", strip=True)

    title = soup.title.get_text(strip=True) if soup.title else ""
    if title:
        text = f"# {title}\n\n{text}"
    return truncate_markdown(text, max_chars)


def extract_text_from_pdf(data: bytes, max_chars: int = 50_000) -> str:
    """Extracts text from a PDF document.

    Args:
        data: Raw PDF bytes.
        max_chars: Maximum characters to return before truncating.

    Returns:
        Concatenated page text, or an error placeholder when the document
        cannot be parsed. Scanned PDFs with no text layer yield a note
        rather than an empty string, so the agent learns the page is not
        readable instead of retrying.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            if sum(len(p) for p in pages) > max_chars:
                break
        text = "\n\n".join(p for p in pages if p.strip())
    except Exception as exc:
        logger.warning("PDF extraction failed: %s", exc)
        return "[error: could not extract text from PDF]"

    if not text.strip():
        return "[note: PDF has no extractable text layer, likely a scan]"
    return truncate_markdown(text, max_chars)

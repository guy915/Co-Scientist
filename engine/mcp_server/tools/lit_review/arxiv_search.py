"""arXiv's subject API covers fields Europe PMC's life-science index barely
reaches.
"""

import logging
import re
from typing import Any
from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as ElementTree
import httpx

from mcp_server.http_client import make_client
from mcp_server.tools import _results

logger = logging.getLogger(__name__)

_ARXIV_API_URL = "https://export.arxiv.org/api/query"

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"

# Remove revision suffixes so newer versions keep the same paper identity.
_VERSION_SUFFIX_RE = re.compile(r"v\d+$")


def _atom(tag: str) -> str:
    return f"{{{_ATOM_NS}}}{tag}"


def _clean_text(text: str | None) -> str:
    return " ".join((text or "").split())


def _short_id(entry_id: str) -> str:
    """Old arXiv IDs include archive prefixes; splitting only the last slash
    loses identity.
    """
    tail = entry_id.rsplit("/abs/", 1)[-1]
    return _VERSION_SUFFIX_RE.sub("", tail)


def _entry_authors(entry: Element) -> list[str]:
    names = []
    for author in entry.findall(_atom("author")):
        name = author.findtext(_atom("name"))
        if name and name.strip():
            names.append(name.strip())
    return names


def _entry_year(entry: Element) -> int | None:
    published = entry.findtext(_atom("published")) or ""
    return int(published[:4]) if published[:4].isdigit() else None


def _entry_record(entry: Element) -> dict[str, Any] | None:
    """arXiv errors may be entries without IDs; do not surface them as
    synthetic papers.
    """
    raw_id = entry.findtext(_atom("id"))
    if not raw_id:
        return None
    return {
        "source_id": _short_id(raw_id),
        "title": _clean_text(entry.findtext(_atom("title"))),
        "abstract": _clean_text(entry.findtext(_atom("summary"))),
        "year": _entry_year(entry),
        "authors": _entry_authors(entry),
        "doi": entry.findtext(f"{{{_ARXIV_NS}}}doi"),
        # Journal publication does not turn the retrieved arXiv copy into peer-
        # reviewed evidence.
        "is_preprint": True,
        "url": raw_id,
    }


def _parse_feed(xml_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    records = []
    for entry in root.findall(_atom("entry")):
        record = _entry_record(entry)
        if record is not None:
            records.append(record)
    return records


async def search_arxiv(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search arXiv for preprints matching a free-text query.

    Args:
        query: Free-text search query, matched across title, abstract,
            authors, and comments.
        max_results: Maximum records to return, capped at 25.

    Returns:
        Source-stamped preprint records, or an empty-records envelope, with
        non-secret error metadata if arXiv cannot be reached or parsed.
    """
    limit = max(1, min(max_results, 25))
    params = {
        "search_query": f"all:{query}",
        "start": "0",
        "max_results": str(limit),
    }
    try:
        async with make_client(30) as client:
            response = await client.get(_ARXIV_API_URL, params=params)
            response.raise_for_status()
        records = _parse_feed(response.text)[:limit]
    except (httpx.HTTPError, ParseError) as exc:
        error = _results.failure(exc)
        logger.warning("arXiv search failed for %r: %s", query, error["detail"])
        return _results.failed_records("arXiv", query, error)
    return _results.records("arXiv", query, records)

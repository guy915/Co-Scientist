"""arXiv preprint search.

arXiv (https://arxiv.org) is a free, keyless preprint server for physics,
mathematics, computer science, and quantitative biology -- fields Europe
PMC's PubMed-rooted index barely reaches (its ``SRC:PPR`` preprint filter
only pulls in arXiv's life-science crossover, q-bio). Unlike bioRxiv,
arXiv's own API answers a real subject query rather than only listing by
posting date (see ``europepmc_search.py``'s module docstring), so this
hits arxiv.org's export API directly instead of going through a
PubMed-adjacent proxy.
"""

import logging
import re
from typing import Any
from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as ElementTree
import httpx

logger = logging.getLogger(__name__)

_ARXIV_API_URL = "https://export.arxiv.org/api/query"

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"

# Strips the revision suffix ("v2") arXiv appends to its abs-page ids, so
# the id names the paper rather than one revision of it -- stable across a
# later query returning a newer version of the same submission.
_VERSION_SUFFIX_RE = re.compile(r"v\d+$")


def _atom(tag: str) -> str:
    """Qualifies an Atom element name with its namespace."""
    return f"{{{_ATOM_NS}}}{tag}"


def _clean_text(text: str | None) -> str:
    """Collapses arXiv's line-wrapped title/summary text to one line."""
    return " ".join((text or "").split())


def _short_id(entry_id: str) -> str:
    """Extracts arXiv's short id from an entry's abs-page URL.

    Old-style ids carry an archive prefix (``hep-th/9901001v1``) that a
    bare ``rsplit("/", 1)`` would discard, dropping the part that makes
    them unique; splitting on the fixed ``/abs/`` segment instead keeps
    everything arXiv itself considers the id.

    Args:
        entry_id: The entry's ``<id>`` element, e.g.
            ``http://arxiv.org/abs/2401.01234v2``.

    Returns:
        The version-stripped short id, e.g. ``2401.01234``.
    """
    tail = entry_id.rsplit("/abs/", 1)[-1]
    return _VERSION_SUFFIX_RE.sub("", tail)


def _entry_authors(entry: Element) -> list[str]:
    """Collects author display names from one Atom ``<entry>``."""
    names = []
    for author in entry.findall(_atom("author")):
        name = author.findtext(_atom("name"))
        if name and name.strip():
            names.append(name.strip())
    return names


def _entry_year(entry: Element) -> int | None:
    """Extracts the publication year from an entry's ``<published>`` date."""
    published = entry.findtext(_atom("published")) or ""
    return int(published[:4]) if published[:4].isdigit() else None


def _entry_record(entry: Element) -> dict[str, Any] | None:
    """Normalizes one Atom ``<entry>`` into a flat paper record.

    Args:
        entry: One ``<entry>`` element from the parsed Atom feed.

    Returns:
        The normalized record, or None when the entry carries no id --
        an error arXiv answers as a single entry with no ``<id>``, and
        treating that as a paper would surface a synthetic empty record
        instead of the honest empty-records envelope its caller falls
        back to.
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
        # arXiv exists to host work ahead of, or instead of, peer review;
        # a later journal publication does not change what this search
        # actually found -- the arXiv copy.
        "is_preprint": True,
        "url": raw_id,
    }


def _parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """Parses an arXiv Atom feed into paper records, skipping bad entries."""
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
        Source-stamped preprint records, or an empty-records envelope on
        any failure to reach or parse arXiv's response.
    """
    limit = max(1, min(max_results, 25))
    params = {
        "search_query": f"all:{query}",
        "start": "0",
        "max_results": str(limit),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(_ARXIV_API_URL, params=params)
            response.raise_for_status()
        records = _parse_feed(response.text)[:limit]
    except (httpx.HTTPError, ParseError) as exc:
        logger.warning("arXiv search failed for %r: %s", query, exc)
        records = []
    return {"source": "arXiv", "query": query, "records": records}

"""Offline retraction check, independent of what a source already flagged.

``citations.resolver`` marks a paper retracted when PubMed or OpenAlex
already flagged it. That source-side flag can lag: retraction propagation
between indexes runs months behind, so a paper retracted at Crossref can
still read "clean" everywhere else. This module is the second, independent
check: a DOI set extracted from the Crossref/Retraction Watch dataset,
shipped as a gzipped, DOI-only text file committed at
``app/app/data/retractions.txt.gz`` (see ``app/dev/refresh_retractions.py``
for how it is built, and the repo-root ``NOTICE`` for attribution).

Loaded lazily and cached at module level: nothing here touches the
filesystem at import time, so a bare import or CLI invocation that never
resolves a citation never pays for it. A missing or unreadable data file
degrades to an empty set with a warning rather than raising -- this check
is a second line of defense, and losing it must never take citation
resolution down with it.
"""

from __future__ import annotations

import functools
import gzip
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_RETRACTIONS_PATH = Path(__file__).parent / "data" / "retractions.txt.gz"

_DOI_URL_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi.org/")


def normalize_doi(doi: str) -> str:
    """Normalize a DOI for set membership: lowercase, no URL prefix.

    Args:
        doi: A DOI, either bare (``10.1000/xyz``) or as a resolver URL
            (``https://doi.org/10.1000/xyz``).

    Returns:
        The bare, lowercased DOI.
    """
    text = doi.strip().lower()
    for prefix in _DOI_URL_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


@functools.lru_cache(maxsize=4)
def _load_doi_set(path: Path) -> frozenset[str]:
    """Read and cache the gzipped DOI list at ``path``.

    Args:
        path: Location of the gzipped, one-DOI-per-line extract.

    Returns:
        The DOIs found, or an empty set if the file is missing or
        unreadable.
    """
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return frozenset(line.strip() for line in handle if line.strip())
    except OSError as exc:
        logger.warning("Retraction dataset unreadable at %s: %s", path, exc)
        return frozenset()


def is_known_retracted(
    doi: str, *, path: Path = DEFAULT_RETRACTIONS_PATH
) -> bool:
    """Check a DOI against the offline Retraction Watch extract.

    Args:
        doi: The article's DOI, bare or as a resolver URL.
        path: Override for the gzipped DOI list; tests point this at a
            temp fixture so the suite never depends on the shipped
            dataset's contents.

    Returns:
        True if the normalized DOI appears in the offline dataset.
    """
    if not doi:
        return False
    return normalize_doi(doi) in _load_doi_set(path)

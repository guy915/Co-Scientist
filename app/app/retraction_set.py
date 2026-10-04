"""Index flags lag; Crossref/Retraction Watch supplies an independent DOI set.

Load lazily and tolerate missing data so citations remain usable; see NOTICE.
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

"""Index retraction flags can lag; the independent Crossref/Retraction Watch
DOI set is lazy and optional so citations remain usable (see NOTICE).
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
    text = doi.strip().lower()
    for prefix in _DOI_URL_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


@functools.lru_cache(maxsize=4)
def _load_doi_set(path: Path) -> frozenset[str]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return frozenset(line.strip() for line in handle if line.strip())
    except OSError as exc:
        logger.warning("Retraction dataset unreadable at %s: %s", path, exc)
        return frozenset()


def is_known_retracted(
    doi: str, *, path: Path = DEFAULT_RETRACTIONS_PATH
) -> bool:
    if not doi:
        return False
    return normalize_doi(doi) in _load_doi_set(path)

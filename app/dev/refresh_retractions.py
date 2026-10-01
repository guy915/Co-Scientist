"""Refresh the offline Retraction Watch DOI extract.

Downloads the current Crossref/Retraction Watch dataset and rebuilds
``app/app/data/retractions.txt.gz``: the retraction and original-paper DOI
of every row whose ``RetractionNature`` is exactly ``"Retraction"``,
normalized (lowercase, no ``doi.org`` prefix), deduplicated, sorted, and
written one per line into a gzipped file. See the repo-root ``NOTICE`` for
the dataset's attribution.

The dataset is pulled from Crossref's GitLab mirror
(gitlab.com/crossref/retraction-watch-data), updated daily, rather than the
``api.labs.crossref.org/data/retractionwatch`` endpoint some other tools
still use (including the paper-qa reference this module was built from):
Crossref's own Labs page states that endpoint "is no longer running" and
now serves stale data, and names the GitLab CSV as its replacement.

This is the only place in the app that talks to Crossref for this dataset.
``citations.resolver`` (via ``app.retraction_set``) only ever reads the
committed file this script produces -- runtime and CI never reach the
network for it. Re-run this by hand periodically and commit the result;
nothing does so automatically.

Run: python app/dev/refresh_retractions.py
"""

from __future__ import annotations

import csv
import gzip
import io
import sys
from pathlib import Path

import httpx

from app.retraction_set import (
    DEFAULT_RETRACTIONS_PATH,
    _load_doi_set,
    normalize_doi,
)

DATASET_URL = (
    "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/"
    "retraction_watch.csv"
)
RETRACTION_NATURE = "Retraction"
DOI_COLUMNS = ("RetractionDOI", "OriginalPaperDOI")
# Keep the committed file small enough to ship in the image without a
# second thought; if the dataset grows past this, stop and say so rather
# than silently bloating every build.
MAX_COMPRESSED_BYTES = 5 * 1024 * 1024


def _download_csv() -> str:
    """Fetch the current dataset as decoded CSV text."""
    with httpx.Client(timeout=300.0) as client:
        response = client.get(DATASET_URL, follow_redirects=True)
        response.raise_for_status()
        return response.text


def _extract_dois(csv_text: str) -> set[str]:
    """Pull retraction DOIs out of genuine-retraction rows only.

    The DOI columns hold the literal string "unavailable" (any casing) and
    the occasional hand-entry typo (a stray "x"/"xx" glued onto an
    otherwise valid DOI) for rows with no real DOI on record. A DOI always
    starts with "10.", so that prefix is the filter rather than trying to
    enumerate every way the column is wrong.
    """
    dois: set[str] = set()
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        if row.get("RetractionNature") != RETRACTION_NATURE:
            continue
        for column in DOI_COLUMNS:
            doi = normalize_doi(row.get(column) or "")
            if doi.startswith("10."):
                dois.add(doi)
    return dois


def _write_extract(path: Path, dois: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for doi in sorted(dois):
            handle.write(f"{doi}\n")


def main() -> int:
    """Download, filter and write the extract; return the process exit code."""
    print(f"Downloading {DATASET_URL} ...")
    csv_text = _download_csv()
    row_count = csv_text.count("\n")
    print(f"Downloaded {row_count} rows ({len(csv_text):,} bytes).")

    dois = _extract_dois(csv_text)
    print(f"Filtered to {len(dois)} distinct retraction DOIs.")

    before = _load_doi_set(DEFAULT_RETRACTIONS_PATH)
    added = dois - before
    removed = before - dois
    print(f"Added: {len(added)}, removed: {len(removed)}.")

    _write_extract(DEFAULT_RETRACTIONS_PATH, dois)
    size = DEFAULT_RETRACTIONS_PATH.stat().st_size
    print(f"Wrote {DEFAULT_RETRACTIONS_PATH} ({size:,} bytes compressed).")

    if size > MAX_COMPRESSED_BYTES:
        print(
            f"ERROR: compressed size {size:,} exceeds the "
            f"{MAX_COMPRESSED_BYTES:,}-byte ceiling; not committing this "
            "as-is.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Crossref's retired Labs endpoint serves stale data; use its daily GitLab
mirror. Runtime and CI read only the committed extract, with attribution
in NOTICE.
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
# Refuse oversized extracts before dataset growth silently inflates every
# production image.
MAX_COMPRESSED_BYTES = 5 * 1024 * 1024


def _download_csv() -> str:
    with httpx.Client(timeout=300.0) as client:
        response = client.get(DATASET_URL, follow_redirects=True)
        response.raise_for_status()
        return response.text


def _extract_dois(csv_text: str) -> set[str]:
    """Unavailable and mistyped DOI entries are common; require the genuine
    10. prefix.
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

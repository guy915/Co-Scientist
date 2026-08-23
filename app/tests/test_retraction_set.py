"""Tests for the offline Retraction Watch DOI extract (retraction_set.py)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from app import retraction_set


def _write_gz(tmp_path: Path, dois: list[str]) -> Path:
    path = tmp_path / "retractions.txt.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(dois) + "\n")
    return path


def test_doi_in_the_set_is_known_retracted(tmp_path: Path) -> None:
    """A DOI present in the offline extract is reported retracted."""
    path = _write_gz(tmp_path, ["10.1000/known-bad"])

    assert retraction_set.is_known_retracted("10.1000/known-bad", path=path)


def test_doi_not_in_the_set_is_not_retracted(tmp_path: Path) -> None:
    """A DOI absent from the extract is not reported retracted."""
    path = _write_gz(tmp_path, ["10.1000/known-bad"])

    assert not retraction_set.is_known_retracted(
        "10.1000/perfectly-fine", path=path
    )


def test_missing_data_file_degrades_to_empty_set(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A missing data file logs a warning and never raises."""
    path = tmp_path / "does-not-exist.txt.gz"

    with caplog.at_level("WARNING"):
        result = retraction_set.is_known_retracted("10.1000/x", path=path)

    assert result is False
    assert "retraction" in caplog.text.lower()


def test_doi_url_prefix_matches_a_bare_entry(tmp_path: Path) -> None:
    """A https://doi.org/... input normalizes to match a bare DOI entry."""
    path = _write_gz(tmp_path, ["10.1000/known-bad"])

    assert retraction_set.is_known_retracted(
        "https://doi.org/10.1000/KNOWN-BAD", path=path
    )


def test_the_shipped_data_file_loads_and_is_non_empty() -> None:
    """The committed dataset is readable and not accidentally truncated."""
    doi_set = retraction_set._load_doi_set(
        retraction_set.DEFAULT_RETRACTIONS_PATH
    )

    assert len(doi_set) > 0

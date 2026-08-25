"""Tests for the offline corpus-ingest tool's backend selection.

The re-extraction (item D3) is a data change proven by measurement, not by
a test; this file only covers the mechanical part: that `--backend` picks
the right extractor, and that choosing `docling` without it installed
fails fast with a message naming the throwaway-venv install rather than a
bare traceback. The project's own `.venv` genuinely lacks docling, so
these run unmocked against the real absence.
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

import pytest

from dev.corpus_ingest import (
    _BACKENDS,
    _require_backend,
    extract_pdf_docling,
    extract_pdf_pdftotext,
    ingest,
)


def test_backend_table_has_both_extractors() -> None:
    """Each backend name maps to its own extraction function."""
    assert _BACKENDS["pdftotext"] is extract_pdf_pdftotext
    assert _BACKENDS["docling"] is extract_pdf_docling


def test_ingest_defaults_to_pdftotext() -> None:
    """The default backend is unchanged so existing callers are unaffected."""
    assert inspect.signature(ingest).parameters["backend"].default == (
        "pdftotext"
    )


def test_docling_absent_raises_actionable_message() -> None:
    """A missing docling install fails with the throwaway-venv install."""
    with pytest.raises(RuntimeError) as excinfo:
        extract_pdf_docling(Path("unused.pdf"))
    message = str(excinfo.value)
    assert "docling" in message
    assert "venv" in message
    assert "torch" in message


def test_require_backend_docling_absent_fails_fast() -> None:
    """The upfront check raises the same message before any PDF is read."""
    with pytest.raises(RuntimeError, match="venv"):
        _require_backend("docling")


def test_ingest_docling_fails_before_writing_anything(
    tmp_path: Path,
) -> None:
    """Choosing an unavailable backend never creates the destination."""
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"

    with pytest.raises(RuntimeError):
        ingest(source, destination, backend="docling")

    assert not destination.exists()

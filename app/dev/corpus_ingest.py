"""Build the sanitized paper corpus from a directory of PDFs.

Run: python app/dev/corpus_ingest.py SOURCE_DIR [--out corpus/sbi_ucd]
                                      [--backend {pdftotext,docling}]

The default backend shells out to `pdftotext` (poppler) rather than
importing a PDF library: the app already depends on pypdf for user uploads,
but pypdf keeps two-column academic layouts in reading order far less
reliably, and this is a one-off offline step where an external binary costs
nothing at runtime.

`--backend docling` swaps in docling's layout-aware parser, which resolves
multi-column reading order and rebuilds tables that `pdftotext`'s
positioned-glyph output destroys. docling pulls in torch and must never
become a runtime dependency of this project -- it is not listed in
`app/pyproject.toml`, `app/requirements-app.txt`, or either Dockerfile, and
is imported lazily so `--backend pdftotext` (the default, and the only
backend either deployed image can run) never touches it. Install docling
into a throwaway virtualenv outside the repository to use this backend; see
`_DOCLING_INSTALL_MESSAGE` below for the exact command.

The step is deliberately separate from serving. Sanitation is slow, needs
tooling the deployed image does not have, and its output is reviewed by a
human before anything reaches a prompt.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from app.paper_corpus import corpus_dir, sanitize

logger = logging.getLogger(__name__)

# Filenames come from a citation manager, so they carry the paper's title.
# Slugged for a stable, path-safe id that survives re-ingestion unchanged.
_SLUG_KEEP = set("abcdefghijklmnopqrstuvwxyz0123456789")

_CONTROL_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")

_DOCLING_INSTALL_MESSAGE = (
    "docling not installed. It pulls in torch and must never be added to "
    "this project's runtime dependencies -- install it into a throwaway "
    "virtualenv outside the repository instead, e.g. "
    "`python3.12 -m venv /tmp/docling-venv && "
    "/tmp/docling-venv/bin/pip install docling`, then run this script "
    "with that interpreter."
)


def slugify(name: str) -> str:
    """Turn a paper filename into a stable, path-safe identifier."""
    lowered = name.lower()
    out = [c if c in _SLUG_KEEP else "-" for c in lowered]
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:80]


def extract_pdf_pdftotext(path: Path) -> str:
    """Extract one PDF to text with `pdftotext`.

    Args:
        path: The PDF to read.

    Returns:
        The extracted text, or an empty string when extraction fails.
    """
    with tempfile.NamedTemporaryFile(suffix=".txt") as handle:
        try:
            subprocess.run(
                ["pdftotext", "-q", str(path), handle.name],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("Could not extract %s: %s", path.name, exc)
            return ""
        return Path(handle.name).read_text(encoding="utf-8", errors="replace")


def extract_pdf_docling(path: Path) -> str:
    """Extract one PDF to text with docling's layout-aware parser.

    Imported lazily, and only here, so no other code path in this script
    (or anything that imports it) ever loads torch.

    Args:
        path: The PDF to read.

    Returns:
        The extracted text, or an empty string when extraction fails.

    Raises:
        RuntimeError: If docling is not installed.
    """
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError(_DOCLING_INSTALL_MESSAGE) from exc
    try:
        document = DocumentConverter().convert(str(path)).document
        text: str = document.export_to_text()
    except Exception as exc:  # docling raises assorted provider errors
        logger.warning("Could not extract %s: %s", path.name, exc)
        return ""
    # A formula docling could not decode to text becomes this literal
    # comment. Left in, it interacts badly with sanitize()'s furniture
    # filter: >=4 copies in one paper get stripped as boilerplate, fewer
    # are kept as body text. Drop it uniformly so a formula is either
    # real text or nothing, never a stray marker either sanitize step
    # might or might not catch.
    text = text.replace("<!-- formula-not-decoded -->", "")
    # A handful of source PDFs carry a broken font cmap: a minus sign or
    # an accented letter decodes not to the wrong *character* (which
    # `pdftotext` also gets wrong, silently) but to a literal C0 control
    # byte -- NUL, CAN, DC4 -- observed verbatim in docling's output on
    # five of fifteen lab PDFs. Left in, that byte reaches the committed
    # corpus and, from there, a model prompt. Drop the byte; the word
    # around it degrades the same way pdftotext's already does.
    return _CONTROL_CHARS.sub("", text)


_BACKENDS: dict[str, Callable[[Path], str]] = {
    "pdftotext": extract_pdf_pdftotext,
    "docling": extract_pdf_docling,
}


def _require_backend(backend: str) -> None:
    """Fail fast, before writing anything, if a backend's tool is absent.

    Raises:
        RuntimeError: If the backend's tool is missing.
    """
    if backend == "pdftotext" and shutil.which("pdftotext") is None:
        raise RuntimeError(
            "pdftotext not found. Install poppler (brew install poppler)."
        )
    if backend == "docling" and importlib.util.find_spec("docling") is None:
        raise RuntimeError(_DOCLING_INSTALL_MESSAGE)


def ingest(
    source: Path, destination: Path, backend: str = "pdftotext"
) -> int:
    """Extract, sanitize, and write every PDF in `source`.

    Args:
        source: Directory of PDFs. Subdirectories are skipped, so an
            "External Papers" folder alongside the lab's own is left out.
        destination: Where sanitized markdown is written.
        backend: Extraction backend, `"pdftotext"` or `"docling"`.

    Returns:
        The number of papers written.
    """
    _require_backend(backend)
    extract = _BACKENDS[backend]
    destination.mkdir(parents=True, exist_ok=True)

    written = 0
    for pdf in sorted(source.glob("*.pdf")):
        raw = extract(pdf)
        if not raw.strip():
            continue
        body, report = sanitize(raw)
        if not body.strip():
            logger.warning("Nothing survived sanitation for %s", pdf.name)
            continue
        title = pdf.stem.strip()
        out = destination / f"{slugify(title)}.md"
        out.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        written += 1
        print(
            f"{title[:58]:<58} "
            f"{report.kept_chars:>8,} chars kept "
            f"({report.kept_fraction:.0%})"
        )
    return written


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Argument list, defaulting to `sys.argv[1:]`.

    Returns:
        A process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="directory of PDFs")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="destination (default: the configured corpus directory)",
    )
    parser.add_argument(
        "--backend",
        choices=sorted(_BACKENDS),
        default="pdftotext",
        help="extraction backend (default: pdftotext)",
    )
    args = parser.parse_args(argv)
    if not args.source.is_dir():
        print(f"not a directory: {args.source}", file=sys.stderr)
        return 2

    destination = args.out or corpus_dir()
    count = ingest(args.source, destination, backend=args.backend)
    print(f"\nWrote {count} papers to {destination}")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())

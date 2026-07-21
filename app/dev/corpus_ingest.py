"""Build the sanitized paper corpus from a directory of PDFs.

Run: python app/dev/corpus_ingest.py SOURCE_DIR [--out corpus/sbi_ucd]

Extraction shells out to `pdftotext` (poppler) rather than importing a PDF
library: the app already depends on pypdf for user uploads, but pypdf keeps
two-column academic layouts in reading order far less reliably, and this is a
one-off offline step where an external binary costs nothing at runtime.

The step is deliberately separate from serving. Sanitation is slow, needs a
binary the deployed image does not have, and its output is reviewed by a
human before anything reaches a prompt.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app.paper_corpus import corpus_dir, sanitize

logger = logging.getLogger(__name__)

# Filenames come from a citation manager, so they carry the paper's title.
# Slugged for a stable, path-safe id that survives re-ingestion unchanged.
_SLUG_KEEP = set("abcdefghijklmnopqrstuvwxyz0123456789")


def slugify(name: str) -> str:
    """Turn a paper filename into a stable, path-safe identifier."""
    lowered = name.lower()
    out = [c if c in _SLUG_KEEP else "-" for c in lowered]
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:80]


def extract_pdf(path: Path) -> str:
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


def ingest(source: Path, destination: Path) -> int:
    """Extract, sanitize, and write every PDF in `source`.

    Args:
        source: Directory of PDFs. Subdirectories are skipped, so an
            "External Papers" folder alongside the lab's own is left out.
        destination: Where sanitized markdown is written.

    Returns:
        The number of papers written.
    """
    if shutil.which("pdftotext") is None:
        raise RuntimeError(
            "pdftotext not found. Install poppler (brew install poppler)."
        )
    destination.mkdir(parents=True, exist_ok=True)

    written = 0
    for pdf in sorted(source.glob("*.pdf")):
        raw = extract_pdf(pdf)
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
    args = parser.parse_args(argv)
    if not args.source.is_dir():
        print(f"not a directory: {args.source}", file=sys.stderr)
        return 2

    destination = args.out or corpus_dir()
    count = ingest(args.source, destination)
    print(f"\nWrote {count} papers to {destination}")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())

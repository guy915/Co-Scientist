"""Extraction and provenance for scientist-uploaded corpus documents."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import shutil
import subprocess

_TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/tiff", "image/webp"}


@dataclasses.dataclass(frozen=True)
class ExtractedDocument:
    """Extracted document text with immutable upload provenance."""

    text: str
    mime_type: str
    sha256: str
    byte_size: int
    extraction_tool: str


def extract_document(data: bytes, mime_type: str) -> ExtractedDocument:
    """Extract supported text/PDF content without fabricating unavailable OCR.

    Args:
        data: Uploaded file bytes.
        mime_type: Browser-reported media type.

    Returns:
        Extracted text and source provenance.

    Raises:
        ValueError: If the file is empty, oversized, unsupported, encrypted,
            malformed, or contains no extractable text.
    """
    if not data:
        raise ValueError("uploaded document is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("uploaded document exceeds the 25 MB limit")
    normalized_type = mime_type.split(";", 1)[0].strip().lower()
    if normalized_type in _TEXT_TYPES:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("text document must be UTF-8") from exc
        tool = "utf8-decoder-v1"
    elif normalized_type == "application/pdf":
        text = _extract_pdf(data)
        tool = "pypdf-layout+tesseract-fallback-v2"
    elif normalized_type in _IMAGE_TYPES:
        text = _extract_image_ocr(data)
        tool = "tesseract-cli-v1"
    else:
        raise ValueError(
            "unsupported document type; upload PDF, PNG, JPEG, TIFF, WebP, "
            "TXT, Markdown, CSV, or JSON"
        )
    if not text.strip():
        raise ValueError("document contains no extractable text")
    return ExtractedDocument(
        text=text,
        mime_type=normalized_type,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        extraction_tool=tool,
    )


def _extract_pdf(data: bytes) -> str:
    """Extract page text plus OCR for embedded figures on image-only pages."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # Fail honestly on a broken deployment.
        raise ValueError("PDF extraction is unavailable") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("encrypted PDFs are not supported")
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except TypeError:
                text = page.extract_text() or ""
            figure_sections = []
            # OCR embedded figures only when the page has no useful text. This
            # keeps born-digital documents fast while recovering scanned pages.
            if not text.strip():
                for figure_index, image in enumerate(page.images, start=1):
                    image_data = image.data
                    digest = hashlib.sha256(image_data).hexdigest()
                    ocr = _extract_image_ocr(image_data)
                    figure_sections.append(
                        f"[Figure {index}.{figure_index} "
                        f"sha256={digest}]\n{ocr}"
                    )
            page_parts = [f"[Page {index}]", text, *figure_sections]
            pages.append("\n".join(part for part in page_parts if part))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF could not be parsed") from exc
    return "\n\n".join(pages)


def _extract_image_ocr(data: bytes) -> str:
    """OCR one image through a fixed Tesseract stdin/stdout invocation."""
    executable = shutil.which("tesseract")
    if not executable:
        raise ValueError("image OCR is unavailable")
    try:
        completed = subprocess.run(
            [executable, "stdin", "stdout", "--psm", "6"],
            input=data,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("image OCR is unavailable") from exc
    if completed.returncode != 0:
        raise ValueError("image could not be decoded or OCR failed")
    return completed.stdout.decode("utf-8", errors="replace").strip()

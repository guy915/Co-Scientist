from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import shutil
import subprocess
from typing import Any

from fastapi import HTTPException, UploadFile

_TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/tiff", "image/webp"}

# Text has no reliable magic bytes; validate decoding instead. WEBP needs both
# RIFF and its nonadjacent WEBP tag.
_BINARY_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


def _sniff_binary_type(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for signature, mime in _BINARY_SIGNATURES:
        if data.startswith(signature):
            return mime
    return None


def _verify_declared_type(data: bytes, declared_type: str) -> None:
    """Signatures detect mislabeled binary uploads, not valid polyglots or
    threats embedded in genuine documents.
    """
    sniffed = _sniff_binary_type(data)
    if sniffed is not None and sniffed != declared_type:
        raise ValueError(
            f"declared type '{declared_type}' does not match the "
            f"file's actual contents (looks like '{sniffed}')"
        )


@dataclasses.dataclass(frozen=True)
class ExtractedDocument:
    text: str
    mime_type: str
    sha256: str
    byte_size: int
    extraction_tool: str


async def extract_upload(file: UploadFile) -> ExtractedDocument:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        return extract_document(
            data, file.content_type or "application/octet-stream"
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def extract_document(data: bytes, mime_type: str) -> ExtractedDocument:
    if not data:
        raise ValueError("uploaded document is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("uploaded document exceeds the 25 MB limit")
    normalized_type = mime_type.split(";", 1)[0].strip().lower()
    _verify_declared_type(data, normalized_type)
    text, tool = _extract_by_type(data, normalized_type)
    if not text.strip():
        raise ValueError("document contains no extractable text")
    return ExtractedDocument(
        text=text,
        mime_type=normalized_type,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        extraction_tool=tool,
    )


def _extract_by_type(data: bytes, normalized_type: str) -> tuple[str, str]:
    if normalized_type in _TEXT_TYPES:
        return _extract_text_document(data, normalized_type)
    if normalized_type == "application/pdf":
        return _extract_pdf(data), "pypdf-layout+tesseract-fallback-v3"
    if normalized_type in _IMAGE_TYPES:
        return _extract_image_ocr(data), "tesseract-cli-v1"
    raise ValueError(
        "unsupported document type; upload PDF, PNG, JPEG, TIFF, WebP, "
        "TXT, Markdown, CSV, or JSON"
    )


def _extract_csv_document(decoded: str) -> tuple[str, str]:
    try:
        rows = list(csv.reader(io.StringIO(decoded)))
    except csv.Error as exc:
        raise ValueError("CSV document could not be parsed") from exc
    if not rows:
        return "", "csv-table-v1"
    width = max(len(row) for row in rows)
    header = rows[0]
    lines = [
        f"[Table 1 rows={len(rows) - 1} columns={width}]",
        "Header: " + " | ".join(header),
    ]
    lines.extend(
        f"Row {index}: " + " | ".join(row)
        for index, row in enumerate(rows[1:], start=1)
    )
    return "\n".join(lines), "csv-table-v1"


def _extract_json_document(decoded: str) -> tuple[str, str]:
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ValueError("JSON document could not be parsed") from exc
    return (
        "[Structured JSON]\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        "json-structure-v1",
    )


def _extract_text_document(data: bytes, mime_type: str) -> tuple[str, str]:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("text document must be UTF-8") from exc
    if mime_type == "text/csv":
        return _extract_csv_document(decoded)
    if mime_type == "application/json":
        return _extract_json_document(decoded)
    return decoded, "utf8-decoder-v1"


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # Fail honestly on a broken deployment.
        raise ValueError("PDF extraction is unavailable") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("encrypted PDFs are not supported")
        pages = list(reader.pages)
        page_texts = [_extract_pdf_page_text(page) for page in pages]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF could not be parsed") from exc

    page_texts = _apply_heading_markup(reader, pages, page_texts)
    sections = [
        _assemble_pdf_page(index, page, text)
        for index, (page, text) in enumerate(
            zip(pages, page_texts, strict=True), start=1
        )
    ]
    return "\n\n".join(sections)


def _extract_pdf_page_text(page: Any) -> str:
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except TypeError:
        return page.extract_text() or ""


def _apply_heading_markup(
    reader: Any, pages: list[Any], page_texts: list[str]
) -> list[str]:
    """Heading inference is optional; unsupported outlines or styling must
    fall back to extracted text rather than reject the scientist's
    document.
    """
    try:
        from app.pdf import apply_heading_markup

        return apply_heading_markup(reader, pages, page_texts)
    except Exception:
        return page_texts


def _assemble_pdf_page(index: int, page: Any, text: str) -> str:
    figure_sections = _extract_pdf_page_figures(index, page)
    page_parts = [f"[Page {index}]", text, *figure_sections]
    return "\n".join(part for part in page_parts if part)


def _extract_pdf_page_figures(index: int, page: Any) -> list[str]:
    """Figures can carry results even on prose-bearing pages; inspect
    substantial embedded images rather than only image-only pages.
    """
    figure_sections = []
    for figure_index, image in enumerate(page.images, start=1):
        image_data = image.data
        if len(image_data) < 1024:
            continue
        digest = hashlib.sha256(image_data).hexdigest()
        try:
            ocr = _extract_image_ocr(image_data)
        except ValueError:
            figure_sections.append(
                f"[Figure {index}.{figure_index} "
                f"sha256={digest} OCR unavailable]"
            )
            continue
        figure_sections.append(
            f"[Figure {index}.{figure_index} sha256={digest}]\n{ocr}"
        )
    return figure_sections


def _extract_image_ocr(data: bytes) -> str:
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

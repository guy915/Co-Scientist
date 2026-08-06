"""Real private-document upload, extraction, provenance, and steering tests."""

import hashlib
import io
import sys
import types

import pytest
from fastapi.testclient import TestClient

from app import store
from tests._client import make_client


def _client_with_run(goal: str) -> tuple[TestClient, str]:
    """Return a client plus the id of a freshly created draft run."""
    client = make_client()
    run_id = client.post("/api/runs", json={"research_goal": goal}).json()["id"]
    return client, run_id


def test_csv_upload_preserves_table_coordinates() -> None:
    """CSV ingestion labels its header and stable row positions."""
    from app.document_ingest import extract_document

    document = extract_document(
        b"condition,replicate,value\ncontrol,1,4.2\ntreated,1,8.7\n",
        "text/csv",
    )

    assert document.extraction_tool == "csv-table-v1"
    assert "[Table 1 rows=2 columns=3]" in document.text
    assert "Header: condition | replicate | value" in document.text
    assert "Row 2: treated | 1 | 8.7" in document.text


def test_json_upload_preserves_nested_structure() -> None:
    """JSON ingestion validates and emits deterministic structured text."""
    from app.document_ingest import extract_document

    document = extract_document(
        b'{"assay": {"units": "nM", "values": [3, 5]}}',
        "application/json",
    )

    assert document.extraction_tool == "json-structure-v1"
    assert document.text.startswith("[Structured JSON]")
    assert '"units": "nM"' in document.text


def test_pdf_ocr_includes_figures_on_text_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Born-digital page prose does not suppress embedded-figure OCR."""
    from app import document_ingest

    class _Image:
        data = b"x" * 1200

    class _Page:
        def __init__(self) -> None:
            self.images = [_Image()]

        def extract_text(self, **_: object) -> str:
            return "Narrative results."

    class _Reader:
        is_encrypted = False

        def __init__(self, _stream: io.BytesIO) -> None:
            self.pages = [_Page()]

    monkeypatch.setitem(
        sys.modules, "pypdf", types.SimpleNamespace(PdfReader=_Reader)
    )
    monkeypatch.setattr(
        document_ingest,
        "_extract_image_ocr",
        lambda _data: "Plot shows a 42 percent reduction.",
    )

    text = document_ingest._extract_pdf(b"fake-pdf")

    assert "Narrative results" in text
    assert "[Figure 1.1 sha256=" in text
    assert "42 percent reduction" in text


def test_text_upload_is_extracted_with_immutable_provenance(
    isolated_db: str,
) -> None:
    client, run_id = _client_with_run("Use private kinase evidence")
    content = b"Kinase X inhibition reduced growth in the private assay."

    response = client.post(
        f"/api/runs/{run_id}/attachments/upload",
        files={"file": ("assay.md", content, "text/markdown")},
        data={"consent": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sha256"] == hashlib.sha256(content).hexdigest()
    evidence = store.list_evidence(run_id, db_path=isolated_db)
    uploaded = next(item for item in evidence if item["id"] == payload["id"])
    assert uploaded["abstract"] == content.decode()
    assert uploaded["mime_type"] == "text/markdown"
    assert uploaded["byte_size"] == len(content)
    assert uploaded["document_version"] == payload["sha256"]
    assert uploaded["extraction_tool"] == "utf8-decoder-v1"
    pending = store.get_pending_steering(run_id, db_path=isolated_db)
    assert pending[-1].meta == {
        "kind": "attachment",
        "evidence_id": payload["id"],
    }


def test_image_upload_is_ocr_extracted_with_multimodal_provenance(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import document_ingest

    monkeypatch.setattr(
        document_ingest,
        "_extract_image_ocr",
        lambda _data: "Figure 1: Kinase X reduced tumour volume by 42%.",
    )
    client, run_id = _client_with_run("Inspect private figure")

    response = client.post(
        f"/api/runs/{run_id}/attachments/upload",
        files={"file": ("figure.png", b"fixture-image", "image/png")},
        data={"consent": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    evidence = store.list_evidence(run_id, db_path=isolated_db)
    uploaded = next(item for item in evidence if item["id"] == payload["id"])
    assert "Kinase X" in uploaded["abstract"]
    assert uploaded["mime_type"] == "image/png"
    assert uploaded["extraction_tool"] == "tesseract-cli-v1"


def test_pdf_bytes_declared_as_png_are_refused() -> None:
    """A mislabeled upload is caught by its own signature, not trusted (N5)."""
    from app.document_ingest import extract_document

    pdf_bytes = b"%PDF-1.4\n%fake pdf body"

    with pytest.raises(ValueError, match="does not match"):
        extract_document(pdf_bytes, "image/png")


def test_text_declared_as_a_mislabeled_pdf_is_refused() -> None:
    """The check runs both directions: a binary file masquerading as text."""
    from app.document_ingest import extract_document

    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 32

    with pytest.raises(ValueError, match="does not match"):
        extract_document(jpeg_bytes, "text/plain")


def test_genuine_png_declared_as_png_is_accepted() -> None:
    """The signature check is a mismatch guard, not a blanket refusal.

    Exercises the check in isolation rather than through the full OCR
    pipeline: the fixture bytes carry a real PNG signature but not a
    decodable image, so going through ``extract_document`` would fail
    downstream in OCR for a reason unrelated to what this test covers.
    """
    from app.document_ingest import _verify_declared_type

    png_signature = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    _verify_declared_type(png_signature, "image/png")  # does not raise


def test_plain_text_with_no_binary_signature_is_unaffected(
    isolated_db: str,
) -> None:
    """Text formats have no magic bytes.

    They are judged by decodability alone, exactly as before this check
    existed.
    """
    client, run_id = _client_with_run("Plain text sanity check")

    response = client.post(
        f"/api/runs/{run_id}/attachments/upload",
        files={"file": ("notes.txt", b"Just plain notes.", "text/plain")},
        data={"consent": "true"},
    )

    assert response.status_code == 200


def test_upload_endpoint_refuses_a_mislabeled_file(isolated_db: str) -> None:
    """End-to-end: the multipart upload path rejects a mismatched MIME type."""
    client, run_id = _client_with_run("Mislabeled upload check")
    pdf_bytes = b"%PDF-1.4\n%mislabeled"

    response = client.post(
        f"/api/runs/{run_id}/attachments/upload",
        files={"file": ("figure.png", pdf_bytes, "image/png")},
        data={"consent": "true"},
    )

    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]
    assert store.list_evidence(run_id, db_path=isolated_db) == []


def test_invalid_image_is_rejected_without_persisting_evidence(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import document_ingest

    # Force the decode-failure path so the assertion holds regardless of
    # whether Tesseract is installed on the runner; without a monkeypatch,
    # a runner missing the binary raises "image OCR is unavailable" instead.
    def _raise_decode_failure(_data: bytes) -> str:
        raise ValueError("image could not be decoded or OCR failed")

    monkeypatch.setattr(
        document_ingest, "_extract_image_ocr", _raise_decode_failure
    )
    client, run_id = _client_with_run("Inspect private figure")

    response = client.post(
        f"/api/runs/{run_id}/attachments/upload",
        files={"file": ("figure.png", b"not-a-real-image", "image/png")},
        data={"consent": "true"},
    )

    assert response.status_code == 422
    assert "OCR failed" in response.json()["detail"]
    assert store.list_evidence(run_id, db_path=isolated_db) == []

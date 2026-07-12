"""Real private-document upload, extraction, provenance, and steering tests."""

import hashlib

import pytest

from app import store
from tests._client import make_client


def test_text_upload_is_extracted_with_immutable_provenance(
    isolated_db: str,
) -> None:
    client = make_client()
    run_id = client.post(
        "/api/runs", json={"research_goal": "Use private kinase evidence"}
    ).json()["id"]
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
    client = make_client()
    run_id = client.post(
        "/api/runs", json={"research_goal": "Inspect private figure"}
    ).json()["id"]

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


def test_invalid_image_is_rejected_without_persisting_evidence(
    isolated_db: str,
) -> None:
    client = make_client()
    run_id = client.post(
        "/api/runs", json={"research_goal": "Inspect private figure"}
    ).json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/attachments/upload",
        files={"file": ("figure.png", b"not-a-real-image", "image/png")},
        data={"consent": "true"},
    )

    assert response.status_code == 422
    assert "OCR failed" in response.json()["detail"]
    assert store.list_evidence(run_id, db_path=isolated_db) == []

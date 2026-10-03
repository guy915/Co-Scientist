"""Tests for documents."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import types
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app import offline_guard, store
from app.config import settings
from app.interviews import model as interviews_model
from app.run_corpus import (
    CorpusDocument,
    KeywordCorpusRetriever,
    engine_context_sources,
)
from tests._client import make_client
from tests._interviews_helpers import (
    _fake_stream,
    _interview_payload,
    _response,
)
from tests._llm_fake_backend import install_completion_backend

# Tests for permanent staged-document deletion (N3).
#
# Covers ``DELETE /api/documents/{id}``.


_OWNER = {"X-Client-ID": "doc-delete-owner"}
_OTHER = {"X-Client-ID": "someone-else"}


def _deletion_stage(client: TestClient, headers: dict[str, str]) -> Any:
    return client.post(
        "/api/documents",
        headers=headers,
        files={
            "file": (
                "notes.txt",
                io.BytesIO(b"private research notes"),
                "text/plain",
            )
        },
        data={"consent": "true"},
    )


def test_owner_can_delete_their_document() -> None:
    client = make_client()
    document_id = _deletion_stage(client, _OWNER).json()["id"]

    response = client.delete(f"/api/documents/{document_id}", headers=_OWNER)

    assert response.status_code == 204
    # A deleted document can no longer be resolved for the owner.
    interview = client.post(
        "/api/interviews",
        headers=_OWNER,
        json={"research_challenge": "x", "document_ids": [document_id]},
    )
    assert interview.status_code == 404


def test_another_client_cannot_delete_the_document() -> None:
    client = make_client()
    document_id = _deletion_stage(client, _OWNER).json()["id"]

    response = client.delete(f"/api/documents/{document_id}", headers=_OTHER)

    assert response.status_code == 404
    # Still resolvable by its real owner -- nothing was deleted.
    interview = client.post(
        "/api/interviews",
        headers=_OWNER,
        json={"research_challenge": "x", "document_ids": [document_id]},
    )
    assert interview.status_code == 200


def test_delete_unknown_document_404s() -> None:
    client = make_client()
    response = client.delete(
        "/api/documents/not-a-real-document", headers=_OWNER
    )
    assert response.status_code == 404


# Real private-document upload, extraction, provenance, and steering tests.


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


# Tests for the private run-corpus keyword retriever (Milestone 7).


def _corpus() -> list[CorpusDocument]:
    return [
        CorpusDocument(
            "d1",
            "Kinase X in AML",
            "Kinase X inhibition reduces tumor growth in acute myeloid "
            "leukemia cells through apoptosis.",
        ),
        CorpusDocument(
            "d2",
            "Photosynthesis",
            "Chloroplast electron transport drives carbon fixation in plants.",
        ),
        CorpusDocument(
            "d3",
            "Immune surveillance",
            "Receptor Y blockade restores immune surveillance against tumors.",
        ),
    ]


def test_retrieves_topically_relevant_document() -> None:
    """A query retrieves the on-topic document above off-topic ones."""
    retriever = KeywordCorpusRetriever(_corpus())
    hits = retriever.retrieve("kinase inhibition tumor growth AML", k=2)
    assert hits
    assert hits[0].document.doc_id == "d1"
    assert hits[0].score > 0.0


def test_off_topic_query_returns_no_spurious_hits() -> None:
    """A query with no shared terms returns nothing (not a random doc)."""
    retriever = KeywordCorpusRetriever(_corpus())
    assert retriever.retrieve("quantum chromodynamics gluon") == []


def test_retrieval_is_deterministic() -> None:
    """The same query returns the same ordered hits every time."""
    retriever = KeywordCorpusRetriever(_corpus())
    first = [h.document.doc_id for h in retriever.retrieve("tumor immune", k=3)]
    second = [
        h.document.doc_id for h in retriever.retrieve("tumor immune", k=3)
    ]
    assert first == second


def test_empty_corpus_returns_nothing() -> None:
    """Retrieval over an empty corpus is safe and empty."""
    assert KeywordCorpusRetriever([]).retrieve("anything") == []


def test_engine_context_sources_preserve_private_provenance() -> None:
    """Retrieved attachments become bounded, explicitly private sources."""
    rows = [
        {
            "id": "private-1",
            "title": "Unpublished kinase study",
            "source": "attachment",
            "abstract": "Kinase X inhibition reduced AML growth. " * 1000,
        },
        {
            "id": "public-1",
            "title": "Public paper",
            "source": "pubmed",
            "abstract": "Not part of the private corpus.",
        },
    ]

    sources = engine_context_sources(rows, "kinase AML", excerpt_chars=200)

    assert len(sources) == 1
    assert sources[0]["source_type"] == "private_document"
    assert sources[0]["data"]["document_id"] == "private-1"
    assert sources[0]["data"]["private"] is True
    assert len(sources[0]["data"]["excerpt"]) <= 200


# Documents staged before a run exists: grounding, and one commit point.
#
# Two defects, one cause. An attachment used to be uploadable only *after*
# the run had been created, so it could not reach the interview that scoped
# the goal (it arrived after the plan was fixed), and it made run start a
# three-call sequence -- create, upload, start -- whose middle step could
# fail and leave a created, unstarted, ungrounded run behind with nothing
# naming it.
#
# Staging the upload first fixes both: the interview quotes it, and creating
# the run carries it in as part of the same call.


_DOC_TEXT = "Tetraploid zebrafish hearts regenerate via klf2a signalling."
_HEADERS = {"X-Client-ID": "doc-scientist"}


def _documents_stage(
    client: TestClient,
    *,
    text: str = _DOC_TEXT,
    name: str = "lab-notes.txt",
    headers: dict[str, str] | None = None,
) -> Any:
    """Upload one document to the staging endpoint and return the response."""
    return client.post(
        "/api/documents",
        headers=headers if headers is not None else _HEADERS,
        files={"file": (name, io.BytesIO(text.encode()), "text/plain")},
        data={"consent": "true"},
    )


def _stage_id(client: TestClient, **kwargs: Any) -> str:
    """Stage one document and return its id, asserting the upload worked."""
    response = _documents_stage(client, **kwargs)
    assert response.status_code == 200, response.text
    return cast(str, response.json()["id"])


def test_staging_rejects_an_unextractable_document() -> None:
    """A document that cannot be read is refused before anything is stored."""
    client = make_client()
    response = client.post(
        "/api/documents",
        headers=_HEADERS,
        files={"file": ("scan.bin", io.BytesIO(b"\x00\x01"), "application/x")},
        data={"consent": "true"},
    )
    assert response.status_code == 422


def test_staged_document_is_not_visible_to_another_client() -> None:
    """Documents are owner-scoped, so another caller cannot attach one."""
    client = make_client()
    document_id = _stage_id(client)
    response = client.post(
        "/api/interviews",
        headers={"X-Client-ID": "someone-else"},
        json={"research_challenge": "x", "document_ids": [document_id]},
    )
    assert response.status_code == 404


def test_attached_document_reaches_the_interview_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Agent's prompt carries the text of the document the user attached.

    Asserted against the request actually sent to the provider, not against
    the wording of the reply.
    """
    client = make_client()
    document_id = _stage_id(client)
    created = client.post(
        "/api/interviews",
        headers=_HEADERS,
        json={
            "research_challenge": "How do hearts regenerate?",
            "document_ids": [document_id],
        },
    )
    assert created.status_code == 200, created.text

    interview_id = store.list_interviews("doc-scientist")[0]["id"]
    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(json.dumps(_response("Which mechanism?")))

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "openai/gpt-4o")
    # The suite forces offline, which refuses the request before the prompt
    # is shaped; this case is about the prompt, and the provider is fake.
    monkeypatch.setattr(offline_guard, "remote_chat_allowed", lambda: True)
    interview = store.get_interview(str(interview_id))
    assert interview is not None

    import asyncio

    asyncio.run(interviews_model._call_interview_model(interview))

    prompt = " ".join(m["content"] for m in captured["messages"])
    assert _DOC_TEXT in prompt
    assert "lab-notes.txt" in prompt


def test_interview_payload_lists_its_attached_documents() -> None:
    """The chat reports what is attached, so the UI is not claiming it alone."""
    client = make_client()
    document_id = _stage_id(client)
    streamed = client.post(
        "/api/interviews",
        headers=_HEADERS,
        json={"research_challenge": "goal", "document_ids": [document_id]},
    )
    interview_id = store.list_interviews("doc-scientist")[0]["id"]
    payload = client.get(
        f"/api/interviews/{interview_id}", headers=_HEADERS
    ).json()
    assert [d["title"] for d in payload["documents"]] == ["lab-notes.txt"]
    # The streamed turn carries the same list: a client that only ever sees
    # frames must not have to re-fetch to learn what it attached.
    frame = _interview_payload(streamed)
    assert [d["title"] for d in frame["documents"]] == ["lab-notes.txt"]


def test_create_run_carries_staged_documents_into_its_corpus() -> None:
    """A run created with attachments is grounded before it is ever started."""
    client = make_client()
    document_id = _stage_id(client)
    created = client.post(
        "/api/runs",
        headers=_HEADERS,
        json={
            "research_goal": "Cardiac regeneration",
            "tier": "express",
            "document_ids": [document_id],
        },
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["id"]
    evidence = client.get(
        f"/api/runs/{run_id}/evidence", headers=_HEADERS
    ).json()
    titles = [row["title"] for row in evidence["evidence"]]
    assert "lab-notes.txt" in titles


def test_create_run_with_an_unknown_document_creates_no_run() -> None:
    """The failing half of the setup leaves no unstarted run behind.

    This is the whole point of moving the upload ahead of creation: a
    partial failure has to happen before anything is committed, not
    between two writes that nothing reconciles.
    """
    client = make_client()
    before = client.get("/api/runs", headers=_HEADERS).json()["runs"]
    response = client.post(
        "/api/runs",
        headers=_HEADERS,
        json={
            "research_goal": "Cardiac regeneration",
            "document_ids": ["not-a-real-document"],
        },
    )
    assert response.status_code == 404
    after = client.get("/api/runs", headers=_HEADERS).json()["runs"]
    assert len(after) == len(before)


def test_run_created_from_a_chat_inherits_the_chat_documents() -> None:
    """Documents attached to the chat ground the run the chat starts."""
    client = make_client()
    document_id = _stage_id(client)
    client.post(
        "/api/interviews",
        headers=_HEADERS,
        json={"research_challenge": "goal", "document_ids": [document_id]},
    )
    interview_id = str(store.list_interviews("doc-scientist")[0]["id"])
    store.update_interview(
        interview_id,
        {
            "research_challenge": "goal",
            "focus_area": ["signalling"],
            "preferences": [],
            "lab_constraints": [],
            "title": None,
        },
        None,
        completed=True,
    )
    created = client.post(
        "/api/runs",
        headers=_HEADERS,
        json={"research_goal": "goal", "interview_id": interview_id},
    )
    assert created.status_code == 200, created.text
    evidence = client.get(
        f"/api/runs/{created.json()['id']}/evidence", headers=_HEADERS
    ).json()
    assert "lab-notes.txt" in [row["title"] for row in evidence["evidence"]]

"""Attachment endpoints for the scientist-contribution run router."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app import document_ingest, run_corpus, store
from app.auth import client_id
from app.runs.contrib_support import _steer_and_continue
from app.runs.models import HumanAttachmentRequest
from app.runs.support import _require_run
from app.store import ScientificTask

router = APIRouter()


def _persist_and_notify_attachment(
    run_id: str, req: HumanAttachmentRequest
) -> tuple[str, ScientificTask | None]:
    """Persist the pasted document as evidence and steer the run with it."""
    ev_id = store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title=req.title,
            source=run_corpus.ATTACHMENT_SOURCE,
            abstract=req.text,
        )
    )
    continuation = _steer_and_continue(
        run_id,
        "scientist",
        f"Use the private research document '{req.title}' in subsequent work.",
        {"kind": "attachment", "evidence_id": ev_id},
    )
    store.append_event(
        run_id,
        "scientist.attachment",
        {"evidence_id": ev_id, "title": req.title},
    )
    return ev_id, continuation


@router.post("/{run_id}/attachments")
async def add_attachment(
    run_id: str, req: HumanAttachmentRequest
) -> dict[str, Any]:
    """Attach a consented text document to the run's private corpus."""
    _require_run(run_id)
    if not req.consent:
        raise HTTPException(
            status_code=422, detail="consent is required to index a document"
        )
    ev_id, continuation = _persist_and_notify_attachment(run_id, req)
    return {
        "id": ev_id,
        "indexed": True,
        "continuation_task_id": continuation.id if continuation else None,
    }


async def _extract_uploaded_document(
    file: UploadFile,
) -> document_ingest.ExtractedDocument:
    """Read and extract the upload, raising 422 on an invalid document."""
    data = await file.read(document_ingest.MAX_UPLOAD_BYTES + 1)
    try:
        return document_ingest.extract_document(
            data, file.content_type or "application/octet-stream"
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _persist_and_notify_upload(
    run_id: str,
    title: str,
    extracted: document_ingest.ExtractedDocument,
    uploader: str,
) -> tuple[str, ScientificTask | None]:
    """Persist the extracted document as evidence and steer the run with it."""
    evidence_id = store.add_evidence(
        store.NewEvidence(
            run_id=run_id,
            title=title,
            source=run_corpus.ATTACHMENT_SOURCE,
            abstract=extracted.text,
            mime_type=extracted.mime_type,
            sha256=extracted.sha256,
            byte_size=extracted.byte_size,
            document_version=extracted.sha256,
            extraction_tool=extracted.extraction_tool,
        )
    )
    continuation = _steer_and_continue(
        run_id,
        uploader,
        "Use the uploaded private research document "
        f"'{title}' in subsequent work.",
        {"kind": "attachment", "evidence_id": evidence_id},
    )
    store.append_event(
        run_id,
        "scientist.attachment",
        {"evidence_id": evidence_id, "title": title},
    )
    return evidence_id, continuation


@router.post("/{run_id}/attachments/upload")
async def upload_attachment(
    run_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
    consent: Annotated[bool, Form()],
) -> dict[str, Any]:
    """Extract and index a real scientist-uploaded document with provenance."""
    _require_run(run_id)
    uploader = client_id(request)
    if not consent:
        raise HTTPException(
            status_code=422, detail="consent is required to index a document"
        )
    extracted = await _extract_uploaded_document(file)
    title = (file.filename or "Uploaded document").strip()
    evidence_id, continuation = _persist_and_notify_upload(
        run_id, title, extracted, uploader
    )
    return {
        "id": evidence_id,
        "indexed": True,
        "sha256": extracted.sha256,
        "byte_size": extracted.byte_size,
        "mime_type": extracted.mime_type,
        "extraction_tool": extracted.extraction_tool,
        "continuation_task_id": continuation.id if continuation else None,
    }


@router.get("/{run_id}/attachments/search")
async def search_attachments(run_id: str, q: str) -> dict[str, Any]:
    """Retrieve a run's attachment corpus by keyword."""
    _require_run(run_id)
    documents = run_corpus.corpus_from_evidence(store.list_evidence(run_id))
    retriever = run_corpus.KeywordCorpusRetriever(documents)
    hits = retriever.retrieve(q)
    return {
        "results": [
            {
                "id": h.document.doc_id,
                "title": h.document.title,
                "score": h.score,
            }
            for h in hits
        ]
    }

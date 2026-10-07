from __future__ import annotations

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)

import co_scientist.domains.documents.ingest as document_ingest
import co_scientist.platform.retrieval.run_corpus as run_corpus
from co_scientist.api.auth import client_id
from co_scientist.api.runs.models import (
    HumanAttachmentRequest,
)
from co_scientist.api.runs.support import _require_run, _steer_and_continue
from co_scientist.core.async_bridge import off_loop
from co_scientist.domains.research_state.repository import records
from co_scientist.domains.research_state.repository.records import NewEvidence
from co_scientist.orchestration.repository import events as store
from co_scientist.platform.db.models import ScientificTask

attachments_router = APIRouter()


def _persist_and_notify_attachment(
    run_id: str, req: HumanAttachmentRequest
) -> tuple[str, ScientificTask | None]:
    ev_id = records.add_evidence(
        NewEvidence(
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


@attachments_router.post("/{run_id}/attachments")
@off_loop
def add_attachment(run_id: str, req: HumanAttachmentRequest) -> dict[str, Any]:
    """Attach a consented text document to the run's private corpus."""
    _require_run(run_id)
    if not req.consent:
        raise HTTPException(status_code=422, detail="consent is required to index a document")
    ev_id, continuation = _persist_and_notify_attachment(run_id, req)
    return {
        "id": ev_id,
        "indexed": True,
        "continuation_task_id": continuation.id if continuation else None,
    }


def _persist_and_notify_upload(
    run_id: str,
    title: str,
    extracted: document_ingest.ExtractedDocument,
    uploader: str,
) -> tuple[str, ScientificTask | None]:
    evidence_id = records.add_evidence(
        NewEvidence(
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
        f"Use the uploaded private research document '{title}' in subsequent work.",
        {"kind": "attachment", "evidence_id": evidence_id},
    )
    store.append_event(
        run_id,
        "scientist.attachment",
        {"evidence_id": evidence_id, "title": title},
    )
    return evidence_id, continuation


@attachments_router.post("/{run_id}/attachments/upload")
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
        raise HTTPException(status_code=422, detail="consent is required to index a document")
    extracted = await document_ingest.extract_upload(file, owner=uploader or "")
    title = (file.filename or "Uploaded document").strip()
    evidence_id, continuation = _persist_and_notify_upload(run_id, title, extracted, uploader)
    return {
        "id": evidence_id,
        "indexed": True,
        "sha256": extracted.sha256,
        "byte_size": extracted.byte_size,
        "mime_type": extracted.mime_type,
        "extraction_tool": extracted.extraction_tool,
        "continuation_task_id": continuation.id if continuation else None,
    }


router = APIRouter()
router.include_router(attachments_router)

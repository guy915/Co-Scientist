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

import app.document_ingest as document_ingest
import app.human_input as human_input
import app.run_corpus as run_corpus
from app.auth import client_id
from app.hypothesis import screen_hypotheses
from app.runs.models import (
    HumanAttachmentRequest,
    HumanHypothesisRequest,
    HumanReviewRequest,
)
from app.runs.support import _require_run, _steer_and_continue
from app.store import events as store
from app.store import hypotheses, records, runs
from app.store.hypotheses import NewHypothesis
from app.store.models import ScientificTask
from app.store.records import NewEvidence, NewReview

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
async def add_attachment(run_id: str, req: HumanAttachmentRequest) -> dict[str, Any]:
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
    extracted = await document_ingest.extract_upload(file)
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


@attachments_router.get("/{run_id}/attachments/search")
async def search_attachments(run_id: str, q: str) -> dict[str, Any]:
    """Retrieve a run's attachment corpus by keyword."""
    _require_run(run_id)
    documents = run_corpus.corpus_from_evidence(records.list_evidence(run_id))
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


router = APIRouter()
router.include_router(attachments_router)


def _persist_manual_hypothesis(run_id: str, hyp: dict[str, Any], author: str) -> str:
    """Scientist-authored hypotheses must pass the same safety boundary as
    generated ones.
    """
    hyp_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title=str(hyp["title"]),
            statement=str(hyp["statement"]),
            created_by_agent=human_input.SCIENTIST_MANUAL_ORIGIN,
            author=author,
        )
    )
    screen_hypotheses(run_id, hypotheses.list_hypotheses(run_id))
    return hyp_id


def _notify_manual_hypothesis(
    run_id: str, author: str, statement: str, hyp_id: str
) -> ScientificTask | None:
    continuation = _steer_and_continue(
        run_id,
        author,
        (f"Scientist-contributed hypothesis to evaluate in subsequent work: {statement}"),
        {"kind": "manual_hypothesis", "hypothesis_id": hyp_id},
    )
    store.append_event(
        run_id,
        "scientist.hypothesis",
        {"hypothesis_id": hyp_id, "author": author},
    )
    return continuation


@router.post("/{run_id}/hypotheses")
async def add_human_hypothesis(
    run_id: str, req: HumanHypothesisRequest, request: Request
) -> dict[str, Any]:
    """Admit a scientist-contributed hypothesis (Milestone 7).

    The hypothesis passes the *same* per-hypothesis safety review every
    generated hypothesis does (no bypass for human authorship). If admitted,
    it is persisted with `origin=scientist_manual` and its author, screened by
    the shared safety path (so its `safety_status` is set like any other), and
    thereafter appears in the run's hypotheses. A blocked hypothesis returns
    the admission decision and is not persisted (HTTP 200 with admitted=false).
    """
    run = runs.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    author = client_id(request) or req.author
    admission = await human_input.admit_human_hypothesis_with_escalation(
        text=req.statement, author=author, run_id=run_id, title=req.title
    )
    if not admission.admitted or admission.hypothesis is None:
        return {"admitted": False, "safety": admission.safety_review.to_dict()}

    hyp_id = _persist_manual_hypothesis(run_id, admission.hypothesis, author)
    continuation = _notify_manual_hypothesis(run_id, author, req.statement, hyp_id)
    return {
        "admitted": True,
        "id": hyp_id,
        "author": author,
        "continuation_task_id": continuation.id if continuation else None,
        "safety": admission.safety_review.to_dict(),
    }


def _require_run_hypothesis(run_id: str, hypothesis_id: str) -> None:
    hyp = hypotheses.get_hypothesis(hypothesis_id)
    if hyp is None or hyp.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="hypothesis not found in this run")


def _build_human_review_or_422(req: HumanReviewRequest, author: str) -> human_input.HumanReview:
    try:
        return human_input.build_human_review(
            hypothesis_id=req.hypothesis_id,
            author=author,
            verdict=req.verdict,
            critique=req.critique,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _persist_and_notify_human_review(
    run_id: str, review: human_input.HumanReview, author: str
) -> ScientificTask | None:
    records.add_review(
        NewReview(
            run_id=run_id,
            hypothesis_id=review.hypothesis_id,
            reviewer_agent="scientist",
            summary=f"Scientist verdict: {review.verdict} (by {review.author})",
            critique=review.critique,
            # Structured verdict fields remain authoritative rather than being
            # inferred
            # from review prose.
            author=review.author,
            verdict=review.verdict,
        )
    )
    continuation = _steer_and_continue(
        run_id,
        author,
        (
            f"Scientist review of hypothesis {review.hypothesis_id}: "
            f"verdict={review.verdict}; {review.critique}"
        ),
        {"kind": "human_review", "hypothesis_id": review.hypothesis_id},
    )
    store.append_event(
        run_id,
        "scientist.review",
        {
            "hypothesis_id": review.hypothesis_id,
            "author": author,
            "verdict": review.verdict,
        },
    )
    return continuation


@router.post("/{run_id}/reviews")
async def add_human_review(
    run_id: str, req: HumanReviewRequest, request: Request
) -> dict[str, Any]:
    """Persist a scientist-contributed review (Milestone 7).

    The review enters the same reviews table as an agent review, attributed to
    its author with `reviewer_agent=scientist`. The verdict must be one of
    support/oppose/revise, and the reviewed hypothesis must belong to the run
    in the URL (no cross-run or dangling review rows).
    """
    _require_run(run_id)
    _require_run_hypothesis(run_id, req.hypothesis_id)
    author = client_id(request) or req.author
    review = _build_human_review_or_422(req, author)
    continuation = _persist_and_notify_human_review(run_id, review, author)
    return {
        "recorded": True,
        "continuation_task_id": continuation.id if continuation else None,
        **review.to_dict(),
    }


__all__ = ["_steer_and_continue"]

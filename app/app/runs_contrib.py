"""Scientist-contributed input endpoints: hypotheses, reviews, attachments.

Split out of ``app.runs`` (which re-exports every name here and mounts
``router`` on its own, so the served route set is unchanged): the
Milestone 7 human-in-the-loop surface — scientist-authored hypotheses
and reviews, text/document attachments to the run's private corpus, and
keyword search over that corpus.
"""

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

from app import (
    document_ingest,
    engine_tasks,
    human_input,
    run_corpus,
    store,
)
from app.auth import client_id
from app.hypothesis_screening import screen_hypotheses
from app.runs_models import (
    HumanAttachmentRequest,
    HumanHypothesisRequest,
    HumanReviewRequest,
)
from app.runs_support import _require_run
from app.store import ScientificTask

router = APIRouter()


def _steer_and_continue(
    run_id: str,
    sender: str,
    content: str,
    meta: dict[str, Any],
) -> ScientificTask | None:
    """Queue a steering message and reopen the run so the agents read it.

    Every scientist contribution -- a hypothesis, a review, an attachment --
    reaches the run the same way: as a steering message the next cycle
    reads, plus a continuation task so a run that already finished picks the
    contribution up instead of stranding it.

    Args:
        run_id: Run the contribution belongs to.
        sender: Author the steering message is attributed to.
        content: The instruction the agents read on the next cycle.
        meta: Contribution kind and the id of the row it refers to.

    Returns:
        The enqueued continuation task, or None when the run is not a
        completed engine run with a checkpoint to continue from.
    """
    message = store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender=sender,
            content=content,
            kind="steering",
            meta=meta,
        )
    )
    return engine_tasks.enqueue_scientist_continuation(run_id, message.id)


def _persist_manual_hypothesis(
    run_id: str, hyp: dict[str, Any], author: str
) -> str:
    """Persist an admitted manual hypothesis and run the shared safety screen.

    Same safety screen as the pipeline, so the manual hypothesis carries a
    persisted safety_status and any blocking outcome is audited identically.
    """
    hyp_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title=str(hyp["title"]),
            statement=str(hyp["statement"]),
            created_by_agent=human_input.SCIENTIST_MANUAL_ORIGIN,
            author=author,
        )
    )
    screen_hypotheses(run_id, store.list_hypotheses(run_id))
    return hyp_id


def _notify_manual_hypothesis(
    run_id: str, author: str, statement: str, hyp_id: str
) -> ScientificTask | None:
    """Steer the run with the new hypothesis and audit the contribution."""
    continuation = _steer_and_continue(
        run_id,
        author,
        (
            "Scientist-contributed hypothesis to evaluate in "
            f"subsequent work: {statement}"
        ),
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
    _require_run(run_id)
    author = client_id(request) or req.author
    admission = await human_input.admit_human_hypothesis_with_escalation(
        text=req.statement, author=author, run_id=run_id, title=req.title
    )
    if not admission.admitted or admission.hypothesis is None:
        return {"admitted": False, "safety": admission.safety_review.to_dict()}

    hyp_id = _persist_manual_hypothesis(run_id, admission.hypothesis, author)
    continuation = _notify_manual_hypothesis(
        run_id, author, req.statement, hyp_id
    )
    return {
        "admitted": True,
        "id": hyp_id,
        "author": author,
        "continuation_task_id": continuation.id if continuation else None,
        "safety": admission.safety_review.to_dict(),
    }


def _require_run_hypothesis(run_id: str, hypothesis_id: str) -> None:
    """Raise 404 unless hypothesis_id names a hypothesis belonging to run_id."""
    hyp = store.get_hypothesis(hypothesis_id)
    if hyp is None or hyp.get("run_id") != run_id:
        raise HTTPException(
            status_code=404, detail="hypothesis not found in this run"
        )


def _build_human_review_or_422(
    req: HumanReviewRequest, author: str
) -> human_input.HumanReview:
    """Validate and build the scientist review, raising 422 on a bad verdict."""
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
    """Persist the review, steer the run, and audit the contribution."""
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=review.hypothesis_id,
            reviewer_agent="scientist",
            summary=f"Scientist verdict: {review.verdict} (by {review.author})",
            critique=review.critique,
            # The same two facts as their own columns. The summary above is
            # for a reader; recovering the verdict by searching it for a
            # verdict word (which is how the engine merge used to score a
            # human review) reads authored prose as structure.
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
        (
            f"Use the private research document '{req.title}' "
            "in subsequent work."
        ),
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
    """Attach a scientist-provided text document to a run's corpus (M7).

    Text-only and consent-gated: no binary or archive is accepted (so there is
    no extraction/malware surface), the text is size-capped by the request
    model, and ``consent`` must be true. The document is stored as run-scoped
    evidence marked as an attachment and indexed into the private retrieval
    corpus (``run_corpus``).
    """
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
    uploader = client_id(request)  # Requires the authenticated researcher.
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
    """Retrieve a run's attachment corpus by keyword (Milestone 7).

    Proves the attachment path is a live retrieval corpus, not a dead
    connector: the scientist's uploaded documents are searchable via the
    run-scoped keyword retriever.
    """
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

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

router = APIRouter()


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
    admission = human_input.admit_human_hypothesis(
        text=req.statement, author=author, title=req.title
    )
    if not admission.admitted or admission.hypothesis is None:
        return {"admitted": False, "safety": admission.safety_review.to_dict()}

    hyp = admission.hypothesis
    hyp_id = store.add_hypothesis(
        run_id,
        title=str(hyp["title"]),
        statement=str(hyp["statement"]),
        created_by_agent=human_input.SCIENTIST_MANUAL_ORIGIN,
        author=author,
    )
    # Same safety screen as the pipeline, so the manual hypothesis carries a
    # persisted safety_status and any blocking outcome is audited identically.
    screen_hypotheses(run_id, store.list_hypotheses(run_id))
    message = store.append_message(
        run_id,
        author,
        "Scientist-contributed hypothesis to evaluate in subsequent work: "
        f"{req.statement}",
        "steering",
        meta={"kind": "manual_hypothesis", "hypothesis_id": hyp_id},
    )
    continuation = engine_tasks.enqueue_scientist_continuation(
        run_id, message.id
    )
    store.append_event(
        run_id,
        "scientist.hypothesis",
        {"hypothesis_id": hyp_id, "author": author},
    )
    return {
        "admitted": True,
        "id": hyp_id,
        "author": author,
        "continuation_task_id": continuation.id if continuation else None,
        "safety": admission.safety_review.to_dict(),
    }


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
    hyp = store.get_hypothesis(req.hypothesis_id)
    if hyp is None or hyp.get("run_id") != run_id:
        raise HTTPException(
            status_code=404, detail="hypothesis not found in this run"
        )
    author = client_id(request) or req.author
    try:
        review = human_input.build_human_review(
            hypothesis_id=req.hypothesis_id,
            author=author,
            verdict=req.verdict,
            critique=req.critique,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.add_review(
        run_id,
        hypothesis_id=review.hypothesis_id,
        reviewer_agent="scientist",
        summary=f"Scientist verdict: {review.verdict} (by {review.author})",
        critique=review.critique,
    )
    message = store.append_message(
        run_id,
        author,
        "Scientist review of hypothesis "
        f"{req.hypothesis_id}: verdict={review.verdict}; {review.critique}",
        "steering",
        meta={"kind": "human_review", "hypothesis_id": req.hypothesis_id},
    )
    continuation = engine_tasks.enqueue_scientist_continuation(
        run_id, message.id
    )
    store.append_event(
        run_id,
        "scientist.review",
        {
            "hypothesis_id": req.hypothesis_id,
            "author": author,
            "verdict": review.verdict,
        },
    )
    return {
        "recorded": True,
        "continuation_task_id": continuation.id if continuation else None,
        **review.to_dict(),
    }


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
    ev_id = store.add_evidence(
        run_id,
        req.title,
        source=run_corpus.ATTACHMENT_SOURCE,
        abstract=req.text,
    )
    message = store.append_message(
        run_id,
        "scientist",
        f"Use the private research document '{req.title}' in subsequent work.",
        "steering",
        meta={"kind": "attachment", "evidence_id": ev_id},
    )
    continuation = engine_tasks.enqueue_scientist_continuation(
        run_id, message.id
    )
    return {
        "id": ev_id,
        "indexed": True,
        "continuation_task_id": continuation.id if continuation else None,
    }


@router.post("/{run_id}/attachments/upload")
async def upload_attachment(
    run_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
    consent: Annotated[bool, Form()],
) -> dict[str, Any]:
    """Extract and index a real scientist-uploaded document with provenance."""
    _require_run(run_id)
    client_id(request)  # Require the run's authenticated researcher context.
    if not consent:
        raise HTTPException(
            status_code=422, detail="consent is required to index a document"
        )
    data = await file.read(document_ingest.MAX_UPLOAD_BYTES + 1)
    try:
        extracted = document_ingest.extract_document(
            data, file.content_type or "application/octet-stream"
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    title = (file.filename or "Uploaded document").strip()
    evidence_id = store.add_evidence(
        run_id,
        title,
        source=run_corpus.ATTACHMENT_SOURCE,
        abstract=extracted.text,
        mime_type=extracted.mime_type,
        sha256=extracted.sha256,
        byte_size=extracted.byte_size,
        document_version=extracted.sha256,
        extraction_tool=extracted.extraction_tool,
    )
    message = store.append_message(
        run_id,
        client_id(request),
        "Use the uploaded private research document "
        f"'{title}' in subsequent work.",
        "steering",
        meta={"kind": "attachment", "evidence_id": evidence_id},
    )
    continuation = engine_tasks.enqueue_scientist_continuation(
        run_id, message.id
    )
    store.append_event(
        run_id,
        "scientist.attachment",
        {"evidence_id": evidence_id, "title": title},
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

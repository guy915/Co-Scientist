"""Scientist-contributed input endpoints: hypotheses, reviews, attachments."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

import app.document_ingest as document_ingest
import app.human_input as human_input
import app.run_corpus as run_corpus
import app.store as store
import app.task_worker as task_worker
from app.api_contracts.science import HypothesisOutcome
from app.auth import client_id, require_bearer_principal
from app.config import settings
from app.execution_policy import (
    CAMPAIGN,
    campaign_model_for_config,
    scoped_execution_policy,
)
from app.hypothesis import screen_hypotheses
from app.outcome_refinement import (
    OutcomeRefinementContextTooLargeError,
    OutcomeRefinementIneligibleError,
    OutcomeRefinementNotFoundError,
    OutcomeRefinementRequest,
    OutcomeRefinementRequestError,
    get_owner_outcome_refinement_action,
    request_outcome_refinement_action,
)
from app.runs.models import (
    HumanAttachmentRequest,
    HumanHypothesisRequest,
    HumanReviewRequest,
    HypothesisOutcomeRequest,
)
from app.runs.support import _require_run, _run_or_404, _steer_and_continue
from app.store import ScientificTask

attachments_router = APIRouter()


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


@attachments_router.post("/{run_id}/attachments")
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
        raise HTTPException(
            status_code=422, detail="consent is required to index a document"
        )
    extracted = await document_ingest.extract_upload(file)
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


@attachments_router.get("/{run_id}/attachments/search")
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


router = APIRouter()
router.include_router(attachments_router)


def _outcome_refinement_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OutcomeRefinementNotFoundError):
        return HTTPException(status_code=404, detail="run or outcome not found")
    if isinstance(exc, OutcomeRefinementIneligibleError):
        return HTTPException(
            status_code=409,
            detail="run or linked hypothesis is not eligible for refinement",
        )
    if isinstance(exc, OutcomeRefinementContextTooLargeError):
        return HTTPException(
            status_code=422,
            detail="complete outcome context exceeds the refinement limits",
        )
    if isinstance(exc, OutcomeRefinementRequestError):
        return HTTPException(status_code=422, detail="invalid idempotency key")
    return HTTPException(
        status_code=409,
        detail="outcome already has an action or idempotency key conflicts",
    )


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
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    author = client_id(request) or req.author
    with scoped_execution_policy(
        run.execution_policy,
        campaign_model_name=(
            campaign_model_for_config(run.config)
            if run.execution_policy == CAMPAIGN
            else None
        ),
    ):
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


@router.post(
    "/{run_id}/hypotheses/{hypothesis_id}/outcomes",
    status_code=201,
    response_model=HypothesisOutcome,
)
async def record_hypothesis_outcome(
    run_id: str,
    hypothesis_id: str,
    req: HypothesisOutcomeRequest,
    request: Request,
) -> dict[str, Any]:
    """Append a researcher-measured outcome for an existing run hypothesis."""
    run = _run_or_404(run_id)
    author = require_bearer_principal(request).subject
    if run.client_id != author:
        raise HTTPException(status_code=404, detail="run not found")
    _require_run_hypothesis(run_id, hypothesis_id)
    try:
        return store.add_hypothesis_outcome(
            store.NewHypothesisOutcome(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                method_protocol=req.method_protocol,
                conditions=req.conditions,
                measured_observation=req.measured_observation,
                units=req.units,
                controls=req.controls,
                interpretation=req.interpretation,
                referenced_evidence_ids=req.referenced_evidence_ids,
                author=author,
            )
        )
    except store.InvalidOutcomeReferencesError as exc:
        raise HTTPException(
            status_code=404,
            detail="hypothesis or evidence not found in this run",
        ) from exc


@router.post(
    "/{run_id}/hypotheses/{hypothesis_id}/outcomes/{outcome_id}/refine",
    status_code=202,
)
async def request_hypothesis_outcome_refinement(
    run_id: str,
    hypothesis_id: str,
    outcome_id: str,
    request: Request,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
    ],
) -> JSONResponse:
    """Queue the owner's separate, targeted use of one recorded outcome."""
    owner = require_bearer_principal(request).subject
    try:
        action = request_outcome_refinement_action(
            OutcomeRefinementRequest(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                outcome_id=outcome_id,
                owner_id=owner,
                request_idempotency_key=idempotency_key,
            )
        )
        background_task = None
        if (
            settings.coscientist_embedded_worker
            and action["status"] == "queued"
        ):
            background_task = BackgroundTask(
                task_worker.run_run_worker_pool_sync,
                run_id,
                f"embedded-api:outcome-refinement:{action['action_id'][:8]}",
            )
        return JSONResponse(action, status_code=202, background=background_task)
    except (
        OutcomeRefinementNotFoundError,
        OutcomeRefinementIneligibleError,
        OutcomeRefinementContextTooLargeError,
        OutcomeRefinementRequestError,
        store.OutcomeRefinementConflictError,
    ) as exc:
        raise _outcome_refinement_http_error(exc) from exc


@router.get("/{run_id}/hypotheses/{hypothesis_id}/outcomes/{outcome_id}/refine")
async def get_hypothesis_outcome_refinement(
    run_id: str,
    hypothesis_id: str,
    outcome_id: str,
    request: Request,
) -> dict[str, Any]:
    """Read this owner's existing refinement action without side effects."""
    owner = require_bearer_principal(request).subject
    try:
        return get_owner_outcome_refinement_action(
            run_id, hypothesis_id, outcome_id, owner
        )
    except OutcomeRefinementNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="run or outcome not found"
        ) from exc


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


__all__ = ["_steer_and_continue"]

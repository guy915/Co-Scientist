"""Request models and create-run config resolution for the runs router.

The pydantic request bodies and the helpers that turn a create-run request into
a resolved run configuration live here so ``runs`` keeps to route wiring. Every
name is re-exported from ``app.runs`` so the ``app.runs.<name>`` import paths
stay stable.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app import paper_corpus
from app.audience import AUDIENCE_PATTERN, audience_context
from app.discovery_spec import (
    DISCOVERY_CONFIG_KEY,
    DiscoverySpecError,
    evaluator_spec,
    seed_source,
)
from app.discovery_spec import grid as discovery_grid
from app.run_modes import (
    RUN_FOCUS_PATTERN,
    RUN_TIER_PATTERN,
    PlanningLists,
    normalize_run_focus,
    normalize_run_tier,
    resolved_run_config,
    setup_config,
)
from app.text_utils import combine_blocks


class CreateRunRequest(BaseModel):
    """Body for POST /api/runs; everything but the goal is optional."""

    research_goal: str = Field(..., min_length=1)
    interview_id: str | None = None
    # Documents staged through /api/documents before this call. They are
    # copied into the run's private corpus as part of creating it, so a run
    # is grounded the moment it exists rather than by a second write that
    # can fail on its own. Documents already attached to ``interview_id``
    # are carried in too, without being named again.
    document_ids: list[str] = Field(default_factory=list)
    # Free-form planning guidance lists; defaults are filled by setup_config
    # when omitted (direct API calls, seeded demos).
    requirements: list[str] | None = None
    attributes: list[str] | None = None
    criteria: list[str] | None = None
    # Regex-validated enums; invalid values are rejected with a 422 here,
    # while None falls through to normalize_run_* defaults.
    focus: str | None = Field(None, pattern=RUN_FOCUS_PATTERN)
    tier: str | None = Field(None, pattern=RUN_TIER_PATTERN)
    # Numeric knobs override the tier defaults (see resolved_run_config).
    initial_hypotheses_count: int | None = None
    max_iterations: int | None = None
    evolution_max_count: int | None = None
    k_factor: int | None = None
    enable_literature_review: bool | None = None
    enable_web_search: bool | None = None
    # The SBI/UCD paper-corpus connector. Only affects the ``sbi_ucd``
    # audience (the corpus is one lab's library); on by default for it.
    enable_paper_corpus: bool | None = None
    completion_email: str | None = Field(
        None,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    notify_on_completion: bool = False
    # Self-declared audience (honor system). Only "sbi_ucd" changes behavior:
    # it injects lab context into planning. Persisted for provenance.
    audience: str | None = Field(None, pattern=AUDIENCE_PATTERN)
    # Makes this a computational-discovery run: it evolves a program
    # against a measured objective instead of generating hypotheses.
    # Free-form here and validated by `discovery_spec`, which owns the
    # shape -- a second schema in this file would be a copy to keep in
    # step. Validation happens at create time on purpose: the spec is
    # read once per variant, so a malformed one otherwise surfaces as
    # hundreds of identically-failing evaluations rather than as a 422.
    discovery: dict[str, Any] | None = None


class StartRunRequest(BaseModel):
    """Body for POST /api/runs/{id}/start.

    Empty by design (the mock provider option was removed): the engine is
    the only provider now. Kept as a distinct model, rather than dropping
    the request body entirely, so the endpoint keeps accepting the ``{}``
    body existing clients already send.
    """


class RenameRunRequest(BaseModel):
    """Body for PATCH /api/runs/{id} (rename).

    ``max_length`` matches ``app.title_gen._MAX_TITLE_CHARS``, the ceiling
    a generated title is held to, so a hand-written one cannot outgrow the
    surfaces (sidebar rows, run titlebar, report header) built for it.
    """

    title: str = Field(..., min_length=1, max_length=80)


class SendMessageRequest(BaseModel):
    """Body for POST /api/runs/{id}/messages (steering)."""

    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    """Body for POST /api/runs/{id}/messages/ask (Q&A)."""

    question: str = Field(..., min_length=1)
    audience: str | None = Field(None, pattern=AUDIENCE_PATTERN)


class HumanHypothesisRequest(BaseModel):
    """Body for POST /api/runs/{id}/hypotheses (scientist-contributed)."""

    statement: str = Field(..., min_length=1)
    author: str = Field(..., min_length=1)
    title: str = ""


class HumanReviewRequest(BaseModel):
    """Body for POST /api/runs/{id}/reviews (scientist-contributed)."""

    hypothesis_id: str = Field(..., min_length=1)
    author: str = Field(..., min_length=1)
    verdict: str = Field(..., min_length=1)  # support | oppose | revise
    critique: str = ""


# Cap on attachment text size (characters). Attachments are inert text stored
# in SQLite (no binary, no archive extraction, so no zip-bomb/malware surface);
# the cap bounds storage and prompt-context growth.
MAX_ATTACHMENT_CHARS = 200_000


class HumanAttachmentRequest(BaseModel):
    """Body for POST /api/runs/{id}/attachments (scientist-provided corpus).

    Text-only by design: the endpoint accepts a document's plain text, never a
    binary or archive, so there is no extraction/malware surface. ``consent``
    must be true — the scientist explicitly consents to indexing the document
    into the run's private retrieval corpus.
    """

    title: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=MAX_ATTACHMENT_CHARS)
    consent: bool = False


class SafetyAdjudicationRequest(BaseModel):
    """Human resolution of a safety item held for review."""

    resolution: Literal["approved", "rejected"]


def _run_overrides_from_request(
    req: CreateRunRequest, *, focus: str, tier: str, setup: dict[str, Any]
) -> dict[str, Any]:
    """Build the ``resolved_run_config`` overrides for a create-run request.

    Only explicitly-sent numeric knobs become overrides; absent fields keep
    the tier defaults applied by ``resolved_run_config``.

    Args:
        req: The validated create-run request body.
        focus: The normalized research focus for this run.
        tier: The normalized run tier for this run.
        setup: The durable planning block persisted inside config_json.

    Returns:
        The overrides dict to pass to ``resolved_run_config``.
    """
    overrides: dict[str, Any] = {
        "tier": tier,
        "focus": focus,
        "setup": setup,
    }
    if req.audience is not None:
        overrides["audience"] = req.audience
    if req.discovery is not None:
        overrides["discovery"] = req.discovery
    # Only explicitly-sent knobs become overrides; each (key, value) pair
    # is dropped when the request left the field unset.
    numeric_overrides: tuple[tuple[str, Any], ...] = (
        ("initial_hypotheses_count", req.initial_hypotheses_count),
        ("max_iterations", req.max_iterations),
        ("evolution_max_count", req.evolution_max_count),
        ("k_factor", req.k_factor),
        ("enable_literature_review", req.enable_literature_review),
        ("enable_web_search", req.enable_web_search),
        ("enable_paper_corpus", req.enable_paper_corpus),
    )
    for key, value in numeric_overrides:
        if value is not None:
            overrides[key] = value
    return overrides


def _validate_discovery_block(block: dict[str, Any] | None) -> None:
    """Rejects a malformed discovery spec at create time.

    Everything the loop reads is built here once so a bad spec is a 422
    on the request that wrote it. Deferring costs far more than it saves:
    `discovery_spec` raises on every read, so the run would start,
    bootstrap, and fail identically on every variant with the malformed
    key visible only in a task traceback.

    Raises:
        HTTPException: 422, carrying the spec error's own message.
    """
    if block is None:
        return
    config = {DISCOVERY_CONFIG_KEY: block}
    try:
        evaluator_spec(config)
        discovery_grid(config)
        seed_source(config)
    except DiscoverySpecError as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid discovery spec: {exc}"
        ) from exc


def _build_create_run_config(
    req: CreateRunRequest,
) -> tuple[dict[str, Any], str, str]:
    """Resolve a create-run request into its (config, focus, tier) triple."""
    _validate_discovery_block(req.discovery)
    focus = normalize_run_focus(req.focus)
    tier = normalize_run_tier(req.tier)
    # The audience's static context document, plus -- for the SBI/UCD audience
    # with the paper-corpus connector on -- the catalog of the group's own
    # papers (title + abstract of each), so the whole library is always in
    # context and the model can fetch any paper in full. The audience gate in
    # `catalog_context` dominates the toggle, so a non-SBI run never receives
    # the catalog even with the toggle forced on.
    corpus_on = req.enable_paper_corpus is not False
    context = combine_blocks(
        audience_context(req.audience),
        paper_corpus.catalog_context(req.audience, enabled=corpus_on),
    )
    # `setup` is the durable planning block persisted inside config_json.
    setup = setup_config(
        research_goal=req.research_goal,
        lists=PlanningLists(
            requirements=req.requirements,
            attributes=req.attributes,
            criteria=req.criteria,
        ),
        focus=focus,
        tier=tier,
        audience_context=context,
    )
    overrides = _run_overrides_from_request(
        req, focus=focus, tier=tier, setup=setup
    )
    return resolved_run_config(overrides), focus, tier

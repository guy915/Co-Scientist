"""Request models and create-run config resolution for the runs router.

The pydantic request bodies and the helpers that turn a create-run request into
a resolved run configuration live here so ``runs`` keeps to route wiring.
Callers import them from this module.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.run_modes import (
    RUN_FOCUS_PATTERN,
    RUN_TIER_PATTERN,
    PlanningLists,
    normalize_run_focus,
    normalize_run_tier,
    resolved_run_config,
    setup_config,
)


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
    # Each entry is the legacy free-prose string, or the R12-5 structured
    # axis shape mirroring Google's published run plan (a 1-5 ``scale``
    # with anchor text, or a categorical ``values`` list);
    # ``clean_attributes_list`` accepts and validates both.
    attributes: list[str | dict[str, Any]] | None = None
    # Each entry is the legacy free-prose string, or the R12-4
    # ``{"name", "value"}`` pair shape mirroring Google's published run
    # plan; ``clean_criteria_list`` accepts and validates both.
    criteria: list[str | dict[str, str]] | None = None
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
    completion_email: str | None = Field(
        None,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    notify_on_completion: bool = False


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


class StartAnnouncementRequest(BaseModel):
    """Body for POST /api/runs/{id}/messages/started (session announcement).

    ``prompt`` is the scientist's own start request, sent verbatim so it is
    persisted and replayed as the turn it is rather than reconstructed
    server-side from a button press.
    """

    prompt: str = Field(..., min_length=1)


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


class HypothesisOutcomeRequest(BaseModel):
    """Body for a researcher-measured outcome linked to a hypothesis."""

    method_protocol: str = Field(..., min_length=1, max_length=10_000)
    conditions: str = Field(..., min_length=1, max_length=10_000)
    measured_observation: str = Field(..., min_length=1, max_length=10_000)
    units: str | None = Field(None, max_length=120)
    controls: str = Field(..., min_length=1, max_length=10_000)
    interpretation: str = Field(..., min_length=1, max_length=10_000)
    referenced_evidence_ids: list[str] = Field(
        default_factory=list, max_length=50
    )

    @field_validator(
        "method_protocol",
        "conditions",
        "measured_observation",
        "controls",
        "interpretation",
    )
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        """Reject required text fields that contain only whitespace."""
        if not value.strip():
            raise ValueError("must contain non-whitespace text")
        return value

    @field_validator("referenced_evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        """Bound each evidence id and reject duplicate references."""
        if any(not item.strip() or len(item) > 128 for item in value):
            raise ValueError("evidence ids must contain 1 to 128 characters")
        if len(set(value)) != len(value):
            raise ValueError("evidence ids must be unique")
        return value


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
    # Only explicitly-sent knobs become overrides; each (key, value) pair
    # is dropped when the request left the field unset.
    numeric_overrides: tuple[tuple[str, Any], ...] = (
        ("initial_hypotheses_count", req.initial_hypotheses_count),
        ("max_iterations", req.max_iterations),
        ("evolution_max_count", req.evolution_max_count),
        ("k_factor", req.k_factor),
        ("enable_literature_review", req.enable_literature_review),
        ("enable_web_search", req.enable_web_search),
    )
    for key, value in numeric_overrides:
        if value is not None:
            overrides[key] = value
    return overrides


def _build_create_run_config(
    req: CreateRunRequest,
) -> tuple[dict[str, Any], str, str]:
    """Resolve a create-run request into its (config, focus, tier) triple."""
    focus = normalize_run_focus(req.focus)
    tier = normalize_run_tier(req.tier)
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
    )
    overrides = _run_overrides_from_request(
        req, focus=focus, tier=tier, setup=setup
    )
    return resolved_run_config(overrides), focus, tier

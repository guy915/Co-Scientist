"""Request models and create-run config resolution for the runs router.

The pydantic request bodies and the helpers that turn a create-run request into
a resolved run configuration live here so ``runs`` keeps to route wiring. Every
name is re-exported from ``app.runs`` so the ``app.runs.<name>`` import paths
stay stable.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.run_modes import (
    RUN_FOCUS_PATTERN,
    RUN_TIER_PATTERN,
    normalize_run_focus,
    normalize_run_tier,
    resolved_run_config,
    setup_config,
)


class CreateRunRequest(BaseModel):
    """Body for POST /api/runs; everything but the goal is optional."""

    research_goal: str = Field(..., min_length=1)
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


class StartRunRequest(BaseModel):
    """Body for POST /api/runs/{id}/start; optional provider override."""

    force_provider: str | None = Field(None, pattern="^(mock|engine)$")


class SendMessageRequest(BaseModel):
    """Body for POST /api/runs/{id}/messages (steering)."""

    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    """Body for POST /api/runs/{id}/messages/ask (Q&A)."""

    question: str = Field(..., min_length=1)


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
        requirements=req.requirements,
        attributes=req.attributes,
        criteria=req.criteria,
        focus=focus,
        tier=tier,
    )
    overrides = _run_overrides_from_request(
        req, focus=focus, tier=tier, setup=setup
    )
    return resolved_run_config(overrides), focus, tier

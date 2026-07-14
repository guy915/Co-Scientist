"""Model-driven, durable research-goal interview API."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import store
from app.auth import require_principal
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/interviews", tags=["interviews"])

_INTERVIEW_TIMEOUT_SECONDS = 45.0
_RESPONSE_SCHEMA = {
    "name": "research_goal_interview",
    "schema": {
        "type": "object",
        "properties": {
            "assistant_message": {"type": "string", "minLength": 1},
            "research_challenge": {"type": "string", "minLength": 1},
            "focus_area": {"type": "array", "items": {"type": "string"}},
            "preferences": {"type": "array", "items": {"type": "string"}},
            "title": {"type": ["string", "null"]},
            "completed": {"type": "boolean"},
        },
        "required": [
            "assistant_message",
            "research_challenge",
            "focus_area",
            "preferences",
            "title",
            "completed",
        ],
        "additionalProperties": False,
    },
}

_SYSTEM_PROMPT = (
    "You are the Agent conducting Google Hypothesis Generation's "
    "research-goal interview. Collaboratively scope one scientific research "
    "goal. Ask exactly one concise, context-sensitive question at a time. "
    "Derive only information the scientist supplied; never invent laboratory "
    "capabilities, data, constraints, or preferences.\n\n"
    "Maintain exactly four structured fields:\n"
    "1. Research Challenge: the precise scientific question or hypothesis.\n"
    "2. Focus Area: scientific subareas or mechanisms to prioritize.\n"
    "3. Preferences: constraints, available data/models/tools, exclusions, "
    "novelty boundary, feasibility requirements, and desired output depth.\n"
    "4. Title: an optional concise title.\n\n"
    "Continue until the challenge is precise, at least one focus area is "
    "known, and meaningful preferences or an explicit statement that there "
    "are none is captured. Then summarize the finalized goal, set "
    "completed=true, and ask no further question. Return only schema-valid "
    "JSON."
)


class CreateInterviewRequest(BaseModel):
    """Initial scientist challenge for a new interview."""

    research_challenge: str = Field(..., min_length=1, max_length=20_000)


class InterviewTurnRequest(BaseModel):
    """One scientist answer or correction."""

    content: str = Field(..., min_length=1, max_length=20_000)


class InterviewFieldsRequest(BaseModel):
    """Scientist-authored edits to the four structured fields."""

    research_challenge: str = Field(..., min_length=1, max_length=20_000)
    focus_area: list[str]
    preferences: list[str]
    title: str | None = Field(None, max_length=200)


def _client_id(request: Request) -> str:
    """Return the verified researcher subject or compatibility scope."""
    return require_principal(request).subject


def _owned_interview(interview_id: str, request: Request) -> dict[str, Any]:
    """Return an owned interview or raise without leaking its existence."""
    interview = store.get_interview(interview_id)
    if interview is None or interview["client_id"] != _client_id(request):
        raise HTTPException(status_code=404, detail="interview not found")
    return interview


def _clean_list(raw: Any) -> list[str]:
    """Normalize a model- or user-produced list into non-empty strings."""
    if not isinstance(raw, list):
        return []
    return [str(value).strip() for value in raw if str(value).strip()]


def _normalized_fields(response: dict[str, Any]) -> dict[str, Any]:
    """Normalize the model response into the verified four-field contract."""
    title = response.get("title")
    return {
        "research_challenge": str(
            response.get("research_challenge") or ""
        ).strip(),
        "focus_area": _clean_list(response.get("focus_area")),
        "preferences": _clean_list(response.get("preferences")),
        "title": str(title).strip() if title else None,
    }


def _essentials_ready(fields: dict[str, Any]) -> bool:
    """Whether the essential scoping fields (challenge + focus) are present.

    Preferences are intentionally excluded: the interview contract treats an
    explicit "no constraints" as a valid terminal state (see the system
    prompt), so an empty preferences list must not block a model-confirmed
    completion. Used to validate the model's own ``completed`` signal.
    """
    return bool(fields["research_challenge"] and fields["focus_area"])


def _ready(fields: dict[str, Any]) -> bool:
    """Return whether required scoping fields contain substantive values.

    Requires preferences as well, so the deterministic recovery path (which
    fills fields from scientist answers in order) collects a preferences answer
    before it completes, rather than finalizing after the focus-area answer.
    """
    return bool(
        fields["research_challenge"]
        and fields["focus_area"]
        and fields["preferences"]
    )


def _prompt(interview: dict[str, Any]) -> str:
    """Render the persisted transcript and current derivation for the model."""
    transcript = [
        {"role": turn["role"], "content": turn["content"]}
        for turn in interview["turns"]
    ]
    context = {
        "current_fields": interview["fields"],
        "transcript": transcript,
    }
    return json.dumps(context, ensure_ascii=False)


async def _call_interview_model(
    interview: dict[str, Any],
) -> dict[str, Any]:
    """Call the configured semantic interview model with structured output."""
    try:
        import litellm
        from co_scientist.llm_request import (
            _inject_schema_into_prompt,
            _supports_json_schema_response_format,
        )

        model = settings.effective_chat_model
        user_prompt = _prompt(interview)
        if _supports_json_schema_response_format(model):
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": _RESPONSE_SCHEMA,
            }
        else:
            # DeepSeek and other json_object-only providers reject the
            # json_schema response format; downgrade to json_object and restate
            # the schema in the prompt, mirroring the engine's
            # provider-capability shim so the interview survives providers the
            # science path already handles.
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _inject_schema_into_prompt(
                        user_prompt, _RESPONSE_SCHEMA
                    ),
                },
            ]
            response_format = {"type": "json_object"}

        response = await asyncio.wait_for(
            litellm.acompletion(
                model=model,
                messages=messages,
                response_format=response_format,
                temperature=0.3,
                max_tokens=1_500,
            ),
            timeout=_INTERVIEW_TIMEOUT_SECONDS,
        )
        content = response.choices[0].message.content or ""
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("interview response must be a JSON object")
        return {str(key): value for key, value in parsed.items()}
    except Exception as exc:
        logger.warning("Interview model failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="The interview Agent is temporarily unavailable.",
        ) from exc


def _fallback_interview_response(
    interview: dict[str, Any],
) -> dict[str, Any]:
    """Advance the four-field interview from explicit scientist answers.

    The recovery path never infers scientific content. It assigns each new
    answer to the field the Agent most recently requested, preserving a usable
    and resumable interview when the configured model is temporarily absent.
    """
    fields = dict(interview["fields"])
    user_turns = [
        str(turn["content"]).strip()
        for turn in interview["turns"]
        if turn["role"] == "user" and str(turn["content"]).strip()
    ]
    answers = user_turns[1:]
    if not fields.get("focus_area") and answers:
        fields["focus_area"] = [answers[0]]
    if not fields.get("preferences") and len(answers) > 1:
        fields["preferences"] = [answers[1]]
    completed = _ready(fields)
    if completed:
        message = "The research goal is ready for run configuration."
    elif not fields.get("focus_area"):
        message = (
            "Which scientific mechanisms or focus areas should this research "
            "prioritize?"
        )
    else:
        message = (
            "What constraints, available models or data, exclusions, and "
            "feasibility preferences should guide the work?"
        )
    return {
        "assistant_message": message,
        **fields,
        "completed": completed,
    }


async def _advance(interview_id: str) -> dict[str, Any]:
    """Run one Agent turn and persist its derivation for later resume."""
    interview = store.get_interview(interview_id)
    assert interview is not None
    used_fallback = False
    try:
        response = await _call_interview_model(interview)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        response = _fallback_interview_response(interview)
        used_fallback = True
    fields = _normalized_fields(response)
    message = str(response.get("assistant_message") or "").strip()
    if not message:
        raise HTTPException(
            status_code=502, detail="Interview Agent returned no message."
        )
    if used_fallback:
        # The deterministic recovery path sequences its questions via _ready,
        # so let it collect a preferences answer before completing.
        completed = _ready(fields)
    else:
        # Trust the model's own completion signal once the essentials are
        # captured. Empty preferences is a valid "no constraints" terminal
        # state per the interview contract, so requiring it here would deadlock
        # the interview whenever the scientist has no additional constraints.
        completed = bool(response.get("completed")) and _essentials_ready(
            fields
        )
    store.append_interview_turn(interview_id, "agent", message)
    store.update_interview(
        interview_id,
        fields,
        None if completed else message,
        completed=completed,
    )
    updated = store.get_interview(interview_id)
    assert updated is not None
    return updated


@router.post("")
async def create_interview(
    body: CreateInterviewRequest, request: Request
) -> dict[str, Any]:
    """Start and immediately advance a durable Agent interview."""
    interview = store.create_interview(
        _client_id(request), body.research_challenge
    )
    return await _advance(str(interview["id"]))


@router.get("/{interview_id}")
async def get_interview(interview_id: str, request: Request) -> dict[str, Any]:
    """Resume an owned interview with its full transcript and progress."""
    return _owned_interview(interview_id, request)


@router.post("/{interview_id}/turns")
async def add_interview_turn(
    interview_id: str, body: InterviewTurnRequest, request: Request
) -> dict[str, Any]:
    """Append a scientist answer and obtain the Agent's next turn."""
    interview = _owned_interview(interview_id, request)
    if interview["status"] != "active":
        raise HTTPException(status_code=409, detail="interview is not active")
    store.append_interview_turn(interview_id, "user", body.content)
    return await _advance(interview_id)


@router.put("/{interview_id}/fields")
async def edit_interview_fields(
    interview_id: str, body: InterviewFieldsRequest, request: Request
) -> dict[str, Any]:
    """Persist scientist edits and finalize when required fields are ready."""
    _owned_interview(interview_id, request)
    fields = body.model_dump()
    fields["focus_area"] = _clean_list(fields["focus_area"])
    fields["preferences"] = _clean_list(fields["preferences"])
    completed = _ready(fields)
    store.update_interview(
        interview_id,
        fields,
        None if completed else "Continue the interview.",
        completed=completed,
    )
    updated = store.get_interview(interview_id)
    assert updated is not None
    return updated

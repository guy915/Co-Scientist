"""Prompt, schema, and field-normalization helpers for the goal interview.

Pure request-shaping half of ``app.interviews``: the response schema, system
prompt, prompt builders, and field normalization/readiness predicates. The
model call itself, the deterministic fallback, and the streaming/advance
cluster stay in ``app.interviews``, which tests monkeypatch by module
attribute (``interviews._call_interview_model``); everything here is
seam-free and re-exported from that module.
"""

from __future__ import annotations

import json
from typing import Any

from app import paper_corpus
from app.audience import audience_chat_context
from app.config import settings
from app.text_utils import combine_blocks

# ``lab_constraints`` (K5) is declared but not required: the scientist may
# legitimately have none, the field is elicited when relevant rather than on
# a fixed schedule, and normalization defaults an omission to the empty list.
_RESPONSE_SCHEMA = {
    "name": "research_goal_interview",
    "schema": {
        "type": "object",
        "properties": {
            "assistant_message": {"type": "string", "minLength": 1},
            "research_challenge": {"type": "string", "minLength": 1},
            "focus_area": {"type": "array", "items": {"type": "string"}},
            "preferences": {"type": "array", "items": {"type": "string"}},
            "lab_constraints": {
                "type": "array",
                "items": {"type": "string"},
            },
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
    "Maintain exactly five structured fields:\n"
    "1. Research Challenge: the precise scientific question or hypothesis.\n"
    "2. Focus Area: scientific subareas or mechanisms to prioritize.\n"
    "3. Preferences: constraints, available data/models/tools, exclusions, "
    "novelty boundary, feasibility requirements, and desired output depth.\n"
    "4. Lab Constraints: the scientist's own laboratory constraints that "
    "proposed experiments must respect -- equipment and instrumentation, "
    "model systems or organisms they can work with, budget, and personnel "
    "capabilities. Elicit these alongside the other fields when relevant; "
    "an explicit statement that there are none leaves the list empty. "
    "Never infer lab capabilities the scientist has not stated.\n"
    "5. Title: an optional concise title.\n\n"
    "Continue until the challenge is precise, at least one focus area is "
    "known, and meaningful preferences or an explicit statement that there "
    "are none is captured. Then summarize the finalized goal, set "
    "completed=true, and ask no further question. Return only schema-valid "
    "JSON."
)


def _system_prompt(interview: dict[str, Any]) -> str:
    """Return the system prompt, carrying the audience's lab context.

    The interview is the first surface a scientist talks to, so it needs the
    same background the in-run Q&A gets (see runs.ask_question); without it
    the Agent cannot answer "what do you know about my group?" and denies
    knowing the lab it is supposedly briefed on. The long-form reference is
    used for the same reason chat uses it: one call per turn, so the cost is
    paid once rather than per tournament comparison.

    Args:
        interview: The interview row, whose stored audience selects context.

    Returns:
        The system prompt, with lab context and paper catalog appended when
        the audience has them, and unchanged otherwise.
    """
    audience = interview.get("audience")
    joined = combine_blocks(
        audience_chat_context(audience),
        paper_corpus.catalog_context(audience),
    )
    if not joined:
        return _SYSTEM_PROMPT
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        "The following describes the scientist's own group and its published "
        "work. Use it to ask better-targeted questions and to answer "
        "questions about the group; do not treat it as the research goal.\n\n"
        f"{joined}"
    )


def _clean_list(raw: Any) -> list[str]:
    """Normalize a model- or user-produced list into non-empty strings."""
    if not isinstance(raw, list):
        return []
    return [str(value).strip() for value in raw if str(value).strip()]


def _normalized_fields(response: dict[str, Any]) -> dict[str, Any]:
    """Normalize the model response into the verified five-field contract.

    ``lab_constraints`` (K5) defaults to the empty list when the model
    omits it: the scientist may have none, and older turns of an in-flight
    interview predate the field entirely.
    """
    title = response.get("title")
    return {
        "research_challenge": str(
            response.get("research_challenge") or ""
        ).strip(),
        "focus_area": _clean_list(response.get("focus_area")),
        "preferences": _clean_list(response.get("preferences")),
        "lab_constraints": _clean_list(response.get("lab_constraints")),
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


def _transcript_turn(turn: dict[str, Any]) -> dict[str, Any]:
    """Render one transcript turn, carrying its reasoning when stored.

    A chat's turns are few and short, so the Agent's own chain of thought
    stays in the context it is asked to continue from -- the next question
    follows from the reasoning as much as from the message it produced.
    """
    entry = {"role": turn["role"], "content": turn["content"]}
    reasoning = str(turn.get("reasoning") or "").strip()
    if reasoning:
        entry["reasoning"] = reasoning
    return entry


def _prompt(interview: dict[str, Any]) -> str:
    """Render the persisted transcript and current derivation for the model."""
    transcript = [_transcript_turn(turn) for turn in interview["turns"]]
    context = {
        "current_fields": interview["fields"],
        "transcript": transcript,
    }
    return json.dumps(context, ensure_ascii=False)


def _interview_request(interview: dict[str, Any]) -> tuple[str, Any, Any]:
    """Build the model, messages, and response_format for one Agent turn.

    Args:
        interview: The durable interview row being advanced.

    Returns:
        A ``(model, messages, response_format)`` triple ready for litellm.
    """
    from co_scientist.llm_request import _supports_json_schema_response_format

    model = settings.effective_chat_model
    system_prompt = _system_prompt(interview)
    user_prompt = _prompt(interview)
    if _supports_json_schema_response_format(model):
        return model, *_json_schema_turn(system_prompt, user_prompt)
    # DeepSeek and other json_object-only providers reject the json_schema
    # response format; downgrade to json_object and restate the schema in the
    # prompt, mirroring the engine's provider-capability shim so the interview
    # survives providers the science path already handles.
    return model, *_json_object_turn(system_prompt, user_prompt)


def _json_schema_turn(system_prompt: str, user_prompt: str) -> tuple[Any, Any]:
    """Build the messages/response_format pair for a schema-capable model."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return messages, {"type": "json_schema", "json_schema": _RESPONSE_SCHEMA}


def _json_object_turn(system_prompt: str, user_prompt: str) -> tuple[Any, Any]:
    """Build the messages/response_format pair for a json_object-only model."""
    from co_scientist.llm_request import _inject_schema_into_prompt

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": _inject_schema_into_prompt(
                user_prompt, _RESPONSE_SCHEMA
            ),
        },
    ]
    return messages, {"type": "json_object"}

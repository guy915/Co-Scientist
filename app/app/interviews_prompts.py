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

from app import paper_corpus, store
from app.audience import audience_chat_context
from app.config import settings
from app.interviews_wire import CLOSE_MARKER, OPEN_MARKER
from app.text_utils import combine_blocks

# The turn's shape, restated for the model. The five fields are unchanged
# from the JSON-object format this replaced; what changed is where they
# live -- a trailing block, after prose that is now ordinary markdown rather
# than a string inside a JSON document. ``lab_constraints`` (K5) is optional:
# the scientist may legitimately have none, the field is elicited when
# relevant rather than on a fixed schedule, and normalization defaults an
# omission to the empty list.
_FORMAT_PROMPT = (
    "Write your reply to the scientist as ordinary markdown. Then, on its "
    "own line after the reply, emit exactly one block:\n\n"
    f"{OPEN_MARKER}\n"
    '{"research_challenge": "...", "focus_area": ["..."], '
    '"preferences": ["..."], "lab_constraints": ["..."], '
    '"title": "..." or null, "completed": true or false}\n'
    f"{CLOSE_MARKER}\n\n"
    "Rules for the block:\n"
    "- It MUST be the last thing in your reply, and MUST appear exactly "
    "once. Never open it before you have finished writing to the "
    "scientist.\n"
    "- It carries the interview's whole current state, not just what this "
    "turn changed. Repeat fields that did not change.\n"
    "- It is machine-read and never shown to the scientist, so never "
    "mention it, and never refer to it in your reply.\n"
    "- Its contents MUST be valid JSON. Do not wrap it in a code fence."
)

_SYSTEM_PROMPT = (
    "You are the Agent conducting Google Hypothesis Generation's "
    "research-goal interview. Collaboratively scope one scientific research "
    "goal. Derive only information the scientist supplied; never invent "
    "laboratory capabilities, data, constraints, or preferences.\n\n"
    "Ask about one thing at a time: a turn raises a single topic, so the "
    "scientist is never handed a questionnaire. Within that, write the way "
    "a knowledgeable colleague would -- brief prose, and markdown where it "
    "genuinely helps (a short list when you are laying out options, bold "
    "for the term you are asking about, a table only when comparing). "
    "Reflect back what you understood before asking, so the scientist can "
    "correct you. Do not pad: a single clear sentence is a complete turn, "
    "and formatting used for its own sake makes the interview slower to "
    "read, not richer.\n\n"
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
    "When ``attached_documents`` is present, the scientist has attached "
    "those documents to this conversation. Read them, scope the goal "
    "against what they actually say, and ask questions that build on them "
    "rather than re-asking what they already answer. An excerpt marked as "
    "truncated is partial; do not treat it as the whole document.\n\n"
    "Continue until the challenge is precise, at least one focus area is "
    "known, and meaningful preferences or an explicit statement that there "
    "are none is captured. Then summarize the finalized goal, set "
    "completed to true, and ask no further question.\n\n"
    f"{_FORMAT_PROMPT}"
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


def _attached_documents(interview: dict[str, Any]) -> list[dict[str, str]]:
    """Return excerpts of the documents attached to this interview.

    The upload used to be possible only after the run existed, which put
    the scientist's own material behind the plan it was supposed to shape.
    Reading it here is what makes the attachment do what the composer's
    paperclip implies. Empty for an interview with none, and for the
    synthetic rows the prompt builders are exercised with directly.
    """
    interview_id = interview.get("id")
    if not interview_id:
        return []
    return store.interview_document_excerpts(str(interview_id))


def _prompt(interview: dict[str, Any]) -> str:
    """Render the persisted transcript and current derivation for the model."""
    transcript = [_transcript_turn(turn) for turn in interview["turns"]]
    context: dict[str, Any] = {
        "current_fields": interview["fields"],
        "transcript": transcript,
    }
    attached = _attached_documents(interview)
    if attached:
        context["attached_documents"] = attached
    return json.dumps(context, ensure_ascii=False)


def _interview_request(interview: dict[str, Any]) -> tuple[str, Any]:
    """Build the model and messages for one Agent turn.

    The turn carries no ``response_format`` at all. It used to: a
    ``json_schema`` request for providers that support it and a
    ``json_object`` downgrade (with the schema restated in the prompt) for
    those that do not. Both are gone with the JSON envelope they enforced --
    the answer is now prose plus a trailing block, which no provider-side
    format can describe. Little was lost with the branch: production runs
    DeepSeek, which only ever got the ``json_object`` downgrade, and that
    mode constrains the response to *some* JSON object, never to this
    schema.

    Args:
        interview: The durable interview row being advanced.

    Returns:
        A ``(model, messages)`` pair ready for litellm.
    """
    messages = [
        {"role": "system", "content": _system_prompt(interview)},
        {"role": "user", "content": _prompt(interview)},
    ]
    return settings.effective_chat_model, messages

"""Structured multiple-choice questions one interview turn may offer."""

from __future__ import annotations

import logging
from typing import Any

from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.schemas.builders import obj

import app.credentials as credentials
import app.offline_guard as offline_guard
from app.config import settings

logger = logging.getLogger(__name__)

# How many questions one turn may offer. The interview asks about one thing
# at a time (see the system prompt's "Turn taking"), so the usual number is
# one; the cap exists for the turn that splits a single decision into its
# facets, and to bound a model that ignores the instruction outright.
MAX_QUESTIONS = 3

# A choice needs at least two options to be one. The upper bound keeps the
# chooser readable without scrolling and keeps the block's contribution to
# the turn's token budget bounded.
MIN_OPTIONS = 2
MAX_OPTIONS = 6


def _text(raw: Any) -> str:
    """Return ``raw`` as trimmed text, or empty for anything else.

    Deliberately narrow: a number or a nested object where a label belongs
    is a malformed option, not a label to stringify.
    """
    return raw.strip() if isinstance(raw, str) else ""


def _normalized_option(raw: Any) -> dict[str, str] | None:
    """Return one option, or None when it carries no label to click."""
    if not isinstance(raw, dict):
        return None
    label = _text(raw.get("label"))
    if not label:
        return None
    return {"label": label, "description": _text(raw.get("description"))}


def _normalized_options(raw: Any) -> list[dict[str, str]]:
    """Return the well-formed options of one question, capped.

    An oversized list is truncated rather than dropped: the first options a
    model writes are the ones it thought of first, and offering six of eight
    answers is better than offering none.
    """
    if not isinstance(raw, list):
        return []
    options = [option for option in map(_normalized_option, raw) if option]
    return options[:MAX_OPTIONS]


def _normalized_question(raw: Any) -> dict[str, Any] | None:
    """Return one question, or None when it is not a usable choice."""
    if not isinstance(raw, dict):
        return None
    question = _text(raw.get("question"))
    options = _normalized_options(raw.get("options"))
    if not question or len(options) < MIN_OPTIONS:
        return None
    return {
        "header": _text(raw.get("header")),
        "question": question,
        "multi_select": bool(raw.get("multi_select")),
        "options": options,
    }


def normalized_questions(raw: Any) -> list[dict[str, Any]]:
    """Return the questions one turn offers, dropping anything malformed.

    Args:
        raw: The spec block's ``questions`` value, as the model wrote it.

    Returns:
        Up to :data:`MAX_QUESTIONS` well-formed questions, in the order the
        model asked them. Empty for a turn that offered no usable choice,
        which is the common case and never an error.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        logger.warning("Interview questions block is not a list; dropping it")
        return []
    questions = [q for q in map(_normalized_question, raw) if q]
    if raw and not questions:
        # A turn that tried to offer a choice and lost it to normalization
        # is invisible otherwise: the scientist just sees prose. The repair
        # pass (app.interviews.questions) recovers the click, but the
        # count of these is how a malformed-block regression is noticed.
        logger.warning(
            "Interview turn offered %d question(s), none usable", len(raw)
        )
    return questions[:MAX_QUESTIONS]


# The repair answers one question -- the one the prose asked -- so the
# schema describes a single question rather than the turn's whole array.
# ``question`` empty is how the model says the prose asked nothing; the
# normalizer then drops it, which is the outcome that path wants.
_QUESTION_SCHEMA = obj(
    {
        "header": {"type": "string"},
        "question": {"type": "string"},
        "multi_select": {"type": "boolean"},
        "options": {
            "type": "array",
            "items": obj(
                {"label": {"type": "string"}, "description": {"type": "string"}}
            ),
        },
    }
)

# Short by construction: a header, a question restated from prose already
# written, and at most six label/description pairs. The engine's thinking
# floor raises this for a model that reasons, so the answer's own share is
# never what a chain of thought spends.
_MAX_TOKENS = 1200

_PROMPT = """\
A research-goal interview turn has just been written to a scientist. Read \
it and return the question it ends on as clickable answers.

- ``question`` is that question, in full, in the turn's own words.
- ``header`` is a two-or-three word label for what is being chosen.
- ``options`` is {min} to {max} answers a scientist could plausibly click, \
each a short ``label`` and a one-line ``description`` of what choosing it \
would mean for the work. Where the answer space is open, enumerate the \
directions the answer could take rather than guessing at exact values.
- ``multi_select`` is true when several answers can hold at once and false \
when they are alternatives.

If the turn does not ask the scientist anything, return an empty \
``question`` and no options. Never invent a question the turn did not ask.

The turn:
---
{message}
---
"""


def _prompt(message: str) -> str:
    """Render the repair prompt for one turn's message."""
    return _PROMPT.format(
        min=MIN_OPTIONS, max=MAX_OPTIONS, message=message.strip()
    )


async def repair_questions(message: str) -> list[dict[str, Any]]:
    """Derive the clickable answers for the question ``message`` asks.

    Args:
        message: The Agent's whole message to the scientist for this turn.

    Returns:
        The turn's questions in the persisted shape, or an empty list when
        the turn asked nothing or the call could not be completed.
    """
    if not message.strip() or not offline_guard.remote_chat_allowed():
        return []
    model, api_key = credentials.byok_model_and_key(
        settings.effective_chat_model
    )
    spec = CompletionSpec(
        model_name=model,
        max_tokens=_MAX_TOKENS,
        temperature=0,
        json_schema=_QUESTION_SCHEMA,
        api_key=api_key,
    )
    try:
        result = await call_llm_json(
            _prompt(message),
            spec,
            max_attempts=2,
            options=LLMCallOptions(
                prompt_name="interview_question_repair", enable_thinking=False
            ),
        )
    except Exception:
        logger.warning("Interview question repair failed", exc_info=True)
        return []
    return normalized_questions([result])

"""Recovering the clickable answers a turn asked for but did not offer.

An interview turn that ends on a question is supposed to carry that
question's clickable answers in its trailing spec block (see
``app.interviews.prompts``' "Offering answers to click"). Sometimes it does
not: the model writes the question in prose and omits the array, or writes
an array that ``app.interviews.questions`` cannot use, or its budget runs
out on the block -- which is last in the reply and so the first thing lost.

The prose is already correct in every one of those cases, so the turn is
not retried. Instead the question the prose asked is read back out of it,
in one small schema'd call, and turned into the options the turn should
have carried. Nothing here invents a question: a turn whose prose asks
nothing (the completing turn, or a reply to small talk that closes on a
statement) yields no usable question and keeps its empty options, which is
what the scientist sees today anyway.

Best-effort throughout, in the shape ``title_gen`` and ``claims.verifier``
established: any provider, parse, or schema failure logs and returns
nothing, because a turn that lost its buttons is a turn the scientist can
still answer by typing, while a turn that failed is one they cannot.
"""

from __future__ import annotations

import logging
from typing import Any

from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.schemas.builders import obj

from app import credentials, offline_guard
from app.config import settings
from app.interviews.questions import (
    MAX_OPTIONS,
    MIN_OPTIONS,
    normalized_questions,
)

logger = logging.getLogger(__name__)

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

"""Structured multiple-choice questions one interview turn may offer.

An Agent turn is markdown prose ending on a question (see
``app.interviews.prompts``). When that question has a small, known set of
sensible answers, the turn also carries them as structured options, in the
same trailing spec block its five fields already ride in
(``app.interviews.wire``). The scientist then clicks an answer instead of
typing one; the click is posted as an ordinary scientist turn, so the model
sees the conversation it would have seen anyway.

The wire shape mirrors two things deliberately. Its anatomy -- a short
header, the question, and options carrying a label and a one-line
description -- is the one every shipped assistant converged on. Its
semantics come from MCP's elicitation schema (SEP-1330): a choice is
single- or multi-select, and a scientist may accept it, answer something
else entirely, or dismiss it without answering.

Everything here normalizes and *drops*; nothing raises. Production runs
DeepSeek's ``json_object`` mode, which constrains the response to some JSON
object and never to this schema, so a malformed block is an ordinary
outcome rather than an error. The prose is the turn -- losing the options
costs the scientist a click, while failing the turn would cost them the
answer.
"""

from __future__ import annotations

import logging
from typing import Any

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
        # pass (app.interviews.question_repair) recovers the click, but the
        # count of these is how a malformed-block regression is noticed.
        logger.warning(
            "Interview turn offered %d question(s), none usable", len(raw)
        )
    return questions[:MAX_QUESTIONS]

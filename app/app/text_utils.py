"""Small shared text helpers for deriving human-readable labels."""

from __future__ import annotations

import re
from typing import Any

# Sentence boundary: terminal punctuation followed by whitespace or end of
# string, so a mid-word abbreviation period (e.g. "M.tuberculosis") is not
# mistaken for a boundary and truncated to "M".
_SENTENCE_END = re.compile(r"[.?!](\s|$)")


def combine_blocks(*blocks: str) -> str:
    """Join non-empty text blocks with a blank line between them.

    The one assembly rule for prompt-context blocks (audience context, the
    paper catalog), shared by run creation and the interview so the two
    surfaces cannot drift.
    """
    return "\n\n".join(block.strip() for block in blocks if block.strip())


def coalesce(*values: Any, default: Any = "") -> Any:
    """Return the first truthy value, or *default* when all are falsy."""
    for value in values:
        if value:
            return value
    return default


def hypothesis_title(h: dict[str, Any]) -> str:
    """Canonical hypothesis display title: "title" or "text", capped at 140."""
    return str(h.get("title") or h.get("text") or "Untitled")[:140]


def hypothesis_statement(h: dict[str, Any]) -> str:
    """Canonical hypothesis body: "statement" or "text", empty when absent.

    The counterpart of :func:`hypothesis_title` for the other reader-facing
    string an idea has -- the proposal itself, labelled "Proposed hypothesis"
    wherever the report shows it. A store row carries that text as
    ``statement``; an engine payload carries the same text as ``text``, and
    the drain derives the row's ``title`` from it with
    :func:`first_sentence`.

    Deliberately does not fall back to ``title``: on a store row the title is
    the statement's own first sentence, so falling back offers a truncation
    of exactly the field that is missing, and on an engine payload there is
    no title at all while the body is right there under ``text``. Those two
    chains ran in different sections of one report -- the Agent-insights
    panel resolved ``statement or title`` while the markdown body resolved
    ``statement or text`` -- so the same idea could be quoted two ways in the
    same document.

    Args:
        h: A hypothesis in either the store-row or engine-payload shape.

    Returns:
        The proposal text, or an empty string when the idea carries none.
        Callers omit their entry rather than render a bare label.
    """
    return str(h.get("statement") or h.get("text") or "")


def hypothesis_id(h: dict[str, Any]) -> str:
    """Canonical hypothesis id, falling back to title."""
    return str(h.get("id") or h.get("hypothesis_id") or hypothesis_title(h))


def first_sentence(text: str) -> str:
    """Return the first sentence of a statement, used as a derived title.

    Splits on ``_SENTENCE_END`` and returns the whole (stripped) text when it
    has no sentence boundary. Deliberately uncapped: the full title is stored
    and the UI word-truncates it for display, so titles are never persisted as
    mid-word stubs.

    Args:
        text: The statement to derive a title from.

    Returns:
        The first sentence, stripped; empty when ``text`` is empty.
    """
    match = _SENTENCE_END.search(text)
    return (text[: match.start()] if match else text).strip()

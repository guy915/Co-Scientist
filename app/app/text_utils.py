"""Small shared text helpers for deriving human-readable labels."""

from __future__ import annotations

import re

# Sentence boundary: terminal punctuation followed by whitespace or end of
# string, so a mid-word abbreviation period (e.g. "M.tuberculosis") is not
# mistaken for a boundary and truncated to "M".
_SENTENCE_END = re.compile(r"[.?!](\s|$)")


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

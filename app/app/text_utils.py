"""Small shared text helpers for deriving human-readable labels."""

from __future__ import annotations

import re
from typing import Any

# Sentence boundary: terminal punctuation followed by whitespace or end of
# string, so a mid-word abbreviation period (e.g. "M.tuberculosis") is not
# mistaken for a boundary and truncated to "M".
_SENTENCE_END = re.compile(r"[.?!](\s|$)")


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


# Matches a leading "1. " ordinal (the numbered-step prefix
# format_experiment_plan emits) so readable_experiment_summary can drop it.
_ORDINAL_PREFIX = re.compile(r"^\d+\.\s*")


def readable_experiment_summary(text: str) -> str:
    """Collapse a numbered Go/No-Go pilot plan (R14-20) into one prose line.

    ``experimental_context`` may hold a markdown-shaped plan -- numbered
    steps plus separately bolded ``**Go:**``/``**No-Go:**`` lines (see the
    engine's ``format_experiment_plan``) -- but the two surfaces this
    feeds (the "Next experiments" insight list and the technical-topics
    detail panel) run no markdown renderer: ``InsightList`` prints plain
    text, and ``run_detail_learning``'s ``renderInlineHtml`` whitelists
    only literal HTML tags, not markdown syntax. Left alone, the literal
    ``**``/leading-digit markup would show through unrendered. Collapsing
    to one line here keeps both surfaces readable without teaching either
    renderer markdown.

    An older plain-paragraph experiment (no numbered lines, no bold
    markers) passes through with only its own newlines joined, which is a
    no-op for genuinely single-paragraph text.

    Args:
        text: The raw ``experimental_context`` value.

    Returns:
        One prose line, or an empty string when ``text`` has no content.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    parts = []
    for line in lines:
        line = _ORDINAL_PREFIX.sub("", line)
        line = line.replace("**Go:**", "Go:").replace("**No-Go:**", "No-Go:")
        parts.append(line)
    return " ".join(parts)

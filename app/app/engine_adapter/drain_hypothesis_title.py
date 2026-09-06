"""Deriving a drained hypothesis's display title (R14-12).

Split out of ``drain_hypotheses`` to keep that module within the file-size
cap; ``drain_hypotheses._derive_hypothesis_identity`` is the sole caller.
"""

from __future__ import annotations

from typing import Any

from app.text_utils import first_sentence

# Mirrors schemas.generation.MAX_TITLE_CHARS in the engine (raised 100 ->
# 120 after production run b82f9162 -- see that constant's own comment).
# Kept as its own constant rather than a cross-package import -- the app has
# no existing import from co_scientist.schemas, and a json_object-downgraded
# response is not bound by the schema's maxLength anyway, so this cap has to
# hold regardless of what the engine's own copy says.
_TITLE_DISPLAY_CAP = 120


def _authored_title(h: dict[str, Any], text: str) -> str:
    """The hypothesis's display title: an authored title, or a fallback.

    The single point where an LLM-authored ``title`` (R14-12: a compact
    noun phrase, matching the published pattern) is preferred over the
    mechanical ``first_sentence(text)`` fallback that predates it. Every
    other reader of a drained hypothesis (report renderers, the Ideas tab,
    the share payload) reads the persisted ``title`` column this function
    feeds, so none of them need a fallback of their own.

    Falls back to ``first_sentence(text)`` -- unchanged from before this
    field existed -- whenever the raw ``title`` is missing, not a string,
    or blank after stripping: a run predating this field, or a
    ``json_object`` downgrade whose response omits, mistypes, or empties
    it. An over-length authored title is clipped rather than discarded --
    a too-long authored name still reads better than a truncated sentence.

    Args:
        h: The raw engine hypothesis payload.
        text: The hypothesis statement, already read from ``h`` by the
            caller (see ``drain_hypotheses._derive_hypothesis_identity``).

    Returns:
        The title to persist onto the store row.
    """
    raw = h.get("title")
    if isinstance(raw, str):
        authored = raw.strip()
        if authored:
            return authored[:_TITLE_DISPLAY_CAP]
    return first_sentence(text)

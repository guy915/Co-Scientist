"""The interview turn's wire format: markdown prose, then a spec block.

One Agent turn is plain markdown prose followed by a single trailing block::

    Got it -- cardiac fibroblasts it is. Two things worth pinning down:

    - **Model system** -- primary human cells, or an iPSC-derived line?
    - **Readout** -- are you measuring collagen deposition directly?

    <run_spec>
    {"research_challenge": "...", "focus_area": ["..."], "completed": false}
    </run_spec>

The prose is what the scientist reads and is streamed to them as it arrives;
the block carries the five structured fields the interview derives. The
ordering is the whole point: state comes last, so everything before the
opening marker can be relayed the moment it lands. It costs nothing, because
a thinking model has already reasoned in ``reasoning_content`` before it
emits its first content token.

This replaced a format in which the entire turn was one JSON object with the
prose inside a string field, which could not stream (its deltas are fragments
of a JSON document, not sentences) and could not carry markdown without
escaping it. See docs/superpowers/specs/2026-08-15-interview-prose-streaming
-design.md.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

OPEN_MARKER = "<run_spec>"
CLOSE_MARKER = "</run_spec>"


def _parse_spec_body(body: str) -> dict[str, Any] | None:
    """Parse a spec block's body, or None when it is not a JSON object.

    Args:
        body: The text between the open and close markers.

    Returns:
        The parsed object, or None when the body is malformed or is valid
        JSON of some other type (a list, a bare string).
    """
    try:
        parsed = json.loads(body)
    except ValueError:
        logger.warning("Interview spec block is not valid JSON")
        return None
    if not isinstance(parsed, dict):
        logger.warning("Interview spec block is not a JSON object")
        return None
    return {str(key): value for key, value in parsed.items()}


def _held_back_length(buffer: str) -> int:
    """Return how many trailing characters might begin the opening marker.

    A marker split across two deltas (``"<run_"`` then ``"spec>"``) would be
    relayed as prose and then have to be retracted, so any suffix that could
    still grow into the marker is withheld until the next delta resolves it.

    Args:
        buffer: Prose accumulated so far and known to contain no whole
            marker.

    Returns:
        The length of the longest suffix of ``buffer`` that is a proper
        prefix of :data:`OPEN_MARKER`, and so must be held back.
    """
    longest = min(len(buffer), len(OPEN_MARKER) - 1)
    for size in range(longest, 0, -1):
        if buffer.endswith(OPEN_MARKER[:size]):
            return size
    return 0


class TurnSplitter:
    """Splits a streamed turn into prose to relay and a spec block to parse.

    Deltas go in one at a time; prose safe to show the scientist comes back
    immediately, and everything from the opening marker onward accumulates
    for parsing once the turn ends. Call :meth:`finish` to flush the last
    held-back prose and read the result.
    """

    def __init__(self) -> None:
        """Start a splitter for one turn; splitters are not reusable."""
        # Prose whose tail might still turn out to open the spec block.
        self._pending = ""
        # Spec-block text collected once the opening marker was seen.
        self._spec: list[str] = []
        self._in_spec = False
        # Prose already released, kept so finish() can return the whole turn.
        self._prose: list[str] = []

    def feed(self, delta: str) -> str:
        """Consume one content delta and return prose safe to relay.

        Args:
            delta: The next content fragment from the stream.

        Returns:
            Prose to show the scientist, possibly empty when the whole
            delta was held back or belongs to the spec block.
        """
        if self._in_spec:
            self._spec.append(delta)
            return ""
        buffer = self._pending + delta
        start = buffer.find(OPEN_MARKER)
        if start != -1:
            self._in_spec = True
            self._pending = ""
            self._spec.append(buffer[start + len(OPEN_MARKER) :])
            return self._release(buffer[:start])
        held = _held_back_length(buffer)
        self._pending = buffer[len(buffer) - held :] if held else ""
        return self._release(buffer[: len(buffer) - held])

    def _release(self, prose: str) -> str:
        """Record and return prose being relayed to the scientist."""
        if prose:
            self._prose.append(prose)
        return prose

    def finish(self) -> tuple[str, str, dict[str, Any] | None]:
        """Flush held-back prose and return the turn's resolved parts.

        Returns:
            A ``(trailing_prose, whole_prose, fields)`` triple.
            ``trailing_prose`` is the remainder that was still held back and
            has not been relayed yet, so a caller streaming to a scientist
            can emit it as the turn's last fragment. ``fields`` is None when
            the turn carried no parseable spec block.
        """
        trailing = self._release(self._pending)
        self._pending = ""
        whole = "".join(self._prose).strip()
        if not self._in_spec:
            return trailing, whole, None
        body = "".join(self._spec)
        end = body.find(CLOSE_MARKER)
        return (
            trailing,
            whole,
            _parse_spec_body(body if end == -1 else body[:end]),
        )


class CreateInterviewRequest(BaseModel):
    """Initial scientist challenge for a new interview.

    ``document_ids`` names documents already staged through
    ``/api/documents``. They are attached to the interview, so the very
    first turn is scoped with the scientist's own material rather than
    reaching the work only after the plan is fixed.
    """

    research_challenge: str = Field(..., min_length=1, max_length=20_000)
    document_ids: list[str] = Field(default_factory=list)


class InterviewTurnRequest(BaseModel):
    """One scientist answer or correction, with any newly attached documents."""

    content: str = Field(..., min_length=1, max_length=20_000)
    document_ids: list[str] = Field(default_factory=list)


class InterviewFieldsRequest(BaseModel):
    """Scientist-authored edits to the five structured fields.

    ``lab_constraints`` (K5) defaults to empty so clients that predate
    the field keep validating; omitting it records "no constraints".
    """

    research_challenge: str = Field(..., min_length=1, max_length=20_000)
    focus_area: list[str]
    preferences: list[str]
    lab_constraints: list[str] = Field(default_factory=list)
    title: str | None = Field(None, max_length=200)

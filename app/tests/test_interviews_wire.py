"""The interview turn's prose/spec wire format and its streaming splitter.

The splitter is the piece that makes a turn streamable, so its boundary
behavior is pinned directly rather than through a turn: a marker arriving
split across deltas must never be relayed as prose and then retracted.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest

from app.interviews.wire import (
    CLOSE_MARKER,
    OPEN_MARKER,
    TurnSplitter,
)

_FIELDS = '{"research_challenge": "Reverse fibrosis", "completed": false}'


def _block(body: str = _FIELDS) -> str:
    """Return a whole spec block wrapping ``body``."""
    return f"{OPEN_MARKER}\n{body}\n{CLOSE_MARKER}"


class _Streamed(NamedTuple):
    """One streamed turn: what was relayed, and what it resolved to."""

    relayed: str
    whole: str
    fields: dict[str, Any] | None


def _stream(deltas: list[str]) -> _Streamed:
    """Stream every delta through a splitter and resolve the turn."""
    splitter = TurnSplitter()
    relayed = [splitter.feed(delta) for delta in deltas]
    trailing, whole, fields = splitter.finish()
    return _Streamed("".join(relayed) + trailing, whole, fields)


def test_split_separates_prose_from_parsed_fields() -> None:
    _, prose, fields = _stream([f"Which model system?\n\n{_block()}"])

    assert prose == "Which model system?"
    assert fields == {
        "research_challenge": "Reverse fibrosis",
        "completed": False,
    }


def test_split_without_a_block_keeps_the_prose_and_reports_no_fields() -> None:
    """A turn carrying no block is legitimate output, not an error.

    The caller keeps the prose and carries the interview's previous fields
    forward, so this must not raise and must not lose the message.
    """
    _, prose, fields = _stream(["Which model system?"])

    assert prose == "Which model system?"
    assert fields is None


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ('{"research_challenge": "Reverse', "truncated mid-write"),
        ("not json at all", "not JSON"),
        ('["a", "b"]', "JSON, but not an object"),
    ],
)
def test_split_reports_no_fields_for_an_unusable_block(
    body: str, reason: str
) -> None:
    _, prose, fields = _stream([f"Question?\n{OPEN_MARKER}\n{body}"])

    assert prose == "Question?", reason
    assert fields is None, reason


def test_splitter_streams_prose_and_parses_the_block() -> None:
    streamed = _stream(["Which ", "model ", "system?\n\n", _block()])

    assert streamed.relayed == "Which model system?\n\n"
    assert streamed.whole == "Which model system?"
    assert streamed.fields == {
        "research_challenge": "Reverse fibrosis",
        "completed": False,
    }


@pytest.mark.parametrize(
    "deltas",
    [
        ["Question?", "<run_", "spec>", _FIELDS, CLOSE_MARKER],
        ["Question?", "<", "run_spec>", _FIELDS, CLOSE_MARKER],
        ["Question?<r", "un_s", "pec>", _FIELDS, CLOSE_MARKER],
        ["Question?", "<run_spec>" + _FIELDS + CLOSE_MARKER],
    ],
)
def test_marker_split_across_deltas_never_leaks_into_prose(
    deltas: list[str],
) -> None:
    """The marker must never be relayed as prose and then retracted.

    A scientist watching the stream would see the raw marker appear and
    vanish, so any suffix that could still grow into it is held back until
    the next delta resolves it.
    """
    streamed = _stream(deltas)

    assert streamed.relayed == "Question?"
    assert streamed.whole == "Question?"
    assert "<" not in streamed.relayed
    assert "run_spec" not in streamed.relayed
    assert streamed.fields == {
        "research_challenge": "Reverse fibrosis",
        "completed": False,
    }


def test_held_back_prose_is_flushed_when_the_turn_ends() -> None:
    """A tail that looked like a marker but never became one is still prose.

    Without the flush, a turn ending in '<' would silently lose it.
    """
    assert _stream(["Compare A ", "< B"]).relayed == "Compare A < B"


def test_a_turn_that_is_only_a_block_relays_no_prose() -> None:
    streamed = _stream([_block()])

    assert streamed.relayed == ""
    assert streamed.whole == ""
    assert streamed.fields is not None


def test_single_delta_and_fragmented_turn_agree() -> None:
    """Chunk boundaries must leave the parsed turn unchanged."""
    text = f"**Bold** and a list:\n- one\n- two\n\n{_block()}"
    streamed = _stream(list(text))
    _, expected_prose, expected_fields = _stream([text])

    assert streamed.relayed.strip() == expected_prose
    assert streamed.whole == expected_prose
    assert streamed.fields == expected_fields

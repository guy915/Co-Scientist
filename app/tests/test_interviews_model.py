"""Tests for the interview model call (``interviews._call_interview_model``).

These cases drive the model-call boundary directly rather than through the
streaming endpoints: the turn's wire format and what a turn missing its
spec block resolves to.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app import interviews, interviews_prompts
from app.config import settings
from app.interviews_wire import CLOSE_MARKER, OPEN_MARKER

from ._interviews_helpers import _fake_stream, _response, _wire_turn


async def test_interview_asks_for_prose_and_a_spec_block(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The turn carries no response_format, and says so in the prompt.

    Both response formats are gone with the JSON envelope they enforced --
    a json_schema request for providers that support it and a json_object
    downgrade for those that do not. The answer is prose plus a trailing
    block now, which no provider-side format can describe, so the shape is
    stated in the prompt and taken apart by ``interviews_wire``.
    """
    import litellm

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(_wire_turn(_response("Which mechanism?")))

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    interview = {
        "turns": [{"role": "user", "content": "restore susceptibility"}],
        "fields": {},
    }
    result = await interviews._call_interview_model(interview)

    assert "response_format" not in captured
    prompt_text = " ".join(m["content"] for m in captured["messages"])
    assert OPEN_MARKER in prompt_text
    assert CLOSE_MARKER in prompt_text
    assert result["assistant_message"] == "Which mechanism?"


async def test_interview_keeps_fields_when_a_turn_omits_its_block(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """A turn with no spec block keeps the prose and the previous fields.

    The old format made this fatal: unparseable output raised 503 and the
    whole turn was discarded into the deterministic fallback. The fields are
    cumulative interview state, so a turn that reports none has simply
    learned nothing new about them, and the scientist should still be shown
    what the Agent said.
    """
    import litellm

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream("Which mechanism should we prioritize?")

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    previous = {
        "research_challenge": "Restore susceptibility",
        "focus_area": ["Efflux-pump regulation"],
    }
    interview = {
        "turns": [{"role": "user", "content": "restore susceptibility"}],
        "fields": previous,
    }
    result = await interviews._call_interview_model(interview)

    assert (
        result["assistant_message"] == "Which mechanism should we prioritize?"
    )
    assert result["research_challenge"] == "Restore susceptibility"
    assert result["focus_area"] == ["Efflux-pump regulation"]
    assert result["completed"] is False


def test_prompt_tolerates_two_consecutive_scientist_turns() -> None:
    """The prompt builder accepts the shape a stopped turn leaves behind.

    A cancelled turn (see interviews_stream._advance_stream) persists
    nothing for the reply it never finished, so the transcript carries two
    consecutive "user" turns once the scientist sends the next message.
    The builder must not assume strict user/agent alternation.
    """
    interview = {
        "id": "orphaned-turn",
        "fields": {},
        "turns": [
            {"role": "user", "content": "Restore antibiotic susceptibility"},
            {"role": "user", "content": "Prioritize efflux-pump regulation."},
        ],
    }
    _model, messages = interviews_prompts._interview_request(interview)
    context = json.loads(messages[1]["content"])
    assert [t["role"] for t in context["transcript"]] == ["user", "user"]
    assert context["transcript"][0]["content"] == (
        "Restore antibiotic susceptibility"
    )
    assert context["transcript"][1]["content"] == (
        "Prioritize efflux-pump regulation."
    )

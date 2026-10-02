"""Tests for the interview model call in ``interviews.model``.

These cases drive the model-call boundary directly rather than through the
streaming endpoints: the turn's wire format and what a turn missing its
spec block resolves to.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config import settings
from app.interviews import model as interviews_model
from app.interviews import prompts as interviews_prompts
from app.interviews.wire import CLOSE_MARKER, OPEN_MARKER

from ._interviews_helpers import _fake_stream, _response, _wire_turn


def _reasoning_only_stream(reasoning: str) -> Any:
    """A stream that reasons at length and ends without a content delta.

    Distinct from ``_fake_stream``, which always yields a content chunk
    (empty or not): the thinking-only shape this reproduces is a stream
    that never emits ``content`` at all, only ``reasoning_content``, then
    stops.
    """
    from types import SimpleNamespace

    def _chunk(reasoning_content: str) -> SimpleNamespace:
        delta = SimpleNamespace(
            reasoning_content=reasoning_content, content=None
        )
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _chunks() -> Any:
        yield _chunk(reasoning)

    return _chunks()


async def test_interview_asks_for_prose_and_a_spec_block(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The turn carries no response_format, and says so in the prompt.

    Both response formats are gone with the JSON envelope they enforced --
    a json_schema request for providers that support it and a json_object
    downgrade for those that do not. The answer is prose plus a trailing
    block now, which no provider-side format can describe, so the shape is
    stated in the prompt and taken apart by ``interviews.wire``.
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
    result = await interviews_model._call_interview_model(interview)

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
    result = await interviews_model._call_interview_model(interview)

    assert (
        result["assistant_message"] == "Which mechanism should we prioritize?"
    )
    assert result["research_challenge"] == "Restore susceptibility"
    assert result["focus_area"] == ["Efflux-pump regulation"]
    assert result["completed"] is False


async def test_thinking_only_turn_retries_once_with_thinking_off(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """A stream that reasons and writes nothing is retried, not surfaced.

    Production incident 2026-09-06: a thinking model spent its whole reply
    reasoning about the goal and ended the stream with no ``content`` delta
    at all. The turn used to resolve to an empty message and 502 as
    "Interview Agent returned no message." -- this asserts the streaming
    path now retries once with thinking off before that ever surfaces, and
    that the second stream's answer is what the turn resolves to.
    """
    import litellm

    from app.config_thinking import CONVERSATIONAL_REASONING_EFFORT

    calls: list[dict[str, Any]] = []
    streams = [
        _reasoning_only_stream("brainstorming dozens of candidate drugs..."),
        _fake_stream(_wire_turn(_response("Which mechanism?"))),
    ]

    async def _fake_acompletion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return streams[len(calls) - 1]

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    reasoning_fragments: list[str] = []

    async def _on_reasoning(fragment: str) -> None:
        reasoning_fragments.append(fragment)

    interview = {
        "turns": [{"role": "user", "content": "restore susceptibility"}],
        "fields": {},
    }
    result = await interviews_model._call_interview_model(
        interview, on_reasoning=_on_reasoning
    )

    assert len(calls) == 2
    # The first request carries the interview's conversational tier, not
    # the engine's "high" floor.
    assert calls[0]["reasoning_effort"] == CONVERSATIONAL_REASONING_EFFORT
    # The retry turns thinking off outright rather than lowering it further.
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in calls[1]
    # The reader sees the model start over, not silence then an error.
    assert any("retrying" in fragment for fragment in reasoning_fragments)
    assert result["assistant_message"] == "Which mechanism?"


def test_prompt_tolerates_two_consecutive_scientist_turns() -> None:
    """The prompt builder accepts the shape a stopped turn leaves behind.

    A cancelled turn (see interviews.stream._advance_stream) persists
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

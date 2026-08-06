"""Tests for the interview model call (``interviews._call_interview_model``).

These cases drive the model-call boundary directly rather than through the
streaming endpoints: response-format downgrade for DeepSeek, native schema for
supporting models, and audience-context injection.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import interviews
from app.config import settings

from ._interviews_helpers import _fake_stream, _response


async def test_interview_downgrades_response_format_for_deepseek(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """DeepSeek rejects json_schema, so the interview must use json_object.

    The engine already downgrades DeepSeek to json_object + schema-in-prompt;
    the interview call must defer to the same provider-capability check rather
    than hardcoding json_schema (which DeepSeek returns a BadRequest for).
    """
    import json

    import litellm

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(json.dumps(_response("Which mechanism?")))

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    interview = {
        "turns": [{"role": "user", "content": "restore susceptibility"}],
        "fields": {},
    }
    result = await interviews._call_interview_model(interview)

    assert captured["response_format"] == {"type": "json_object"}
    # The schema is restated in the prompt so structure survives the downgrade.
    prompt_text = " ".join(m["content"] for m in captured["messages"])
    assert "assistant_message" in prompt_text
    assert result["assistant_message"] == "Which mechanism?"


async def test_interview_keeps_json_schema_for_supporting_model(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """A model that supports json_schema still gets the native schema format."""
    import json

    import litellm

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(json.dumps(_response("ok")))

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "openai/gpt-4o")

    interview = {
        "turns": [{"role": "user", "content": "test"}],
        "fields": {},
    }
    await interviews._call_interview_model(interview)

    assert captured["response_format"]["type"] == "json_schema"


async def test_interview_carries_audience_lab_context(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The SBI/UCD interview is briefed on the group it is interviewing.

    Regression: the interview is the first surface a scientist talks to, but
    it was the only conversational surface that never received the audience
    context. Asking the Agent "what do you know about SBI?" in SBI mode had
    it deny knowing the lab, while the in-run Q&A answered the same question
    fine.
    """
    import json

    import litellm

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(json.dumps(_response("Which mechanism?")))

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)

    interview = {
        "turns": [{"role": "user", "content": "resistance mechanisms"}],
        "fields": {},
        "audience": "sbi_ucd",
    }
    await interviews._call_interview_model(interview)

    system = next(
        m["content"] for m in captured["messages"] if m["role"] == "system"
    )
    assert "Systems Biology Ireland" in system
    # The group's own papers ride along too, so the Agent can speak to them.
    assert "paper_id" in system


async def test_interview_without_audience_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """A general-audience interview gets no injected lab context."""
    import json

    import litellm

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(json.dumps(_response("Which mechanism?")))

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)

    interview = {
        "turns": [{"role": "user", "content": "resistance mechanisms"}],
        "fields": {},
        "audience": "general",
    }
    await interviews._call_interview_model(interview)

    system = next(
        m["content"] for m in captured["messages"] if m["role"] == "system"
    )
    assert "Systems Biology Ireland" not in system
    assert "paper_id" not in system

"""Recovering an interview turn's clickable answers from its own prose.

The turn's trailing spec block is where a question's options ride, and it
is last in the reply -- so a truncated turn, or one whose model ignored the
instruction, asks in prose with no buttons under it. These cover the small
repair call that reads the question back out of the prose, and the rule
that it must never cost the scientist the turn.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import interviews_question_repair as repair

_ANSWER = {
    "header": "Model system",
    "question": "Which model system should the ideas be built around?",
    "multi_select": False,
    "options": [
        {"label": "Primary human cells", "description": "Closest to biology"},
        {"label": "iPSC-derived line", "description": "Renewable"},
    ],
}


def _patch_call(
    monkeypatch: pytest.MonkeyPatch, result: Any
) -> list[tuple[str, Any]]:
    """Answer the repair's model call with ``result`` (or raise it)."""
    calls: list[tuple[str, Any]] = []

    async def _fake_call(prompt: str, spec: Any, **kwargs: Any) -> Any:
        calls.append((prompt, spec))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(repair, "call_llm_json", _fake_call)
    monkeypatch.setattr("app.offline_guard.remote_chat_allowed", lambda: True)
    return calls


async def test_the_question_the_prose_asked_comes_back_as_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_call(monkeypatch, _ANSWER)

    questions = await repair.repair_questions("Which model system?")

    assert questions == [_ANSWER]
    assert "Which model system?" in calls[0][0]


async def test_a_turn_that_asks_nothing_gets_no_invented_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The completing turn's shape, and any reply that closes on a statement.

    The repair reads a question out of prose; it does not write one, so an
    empty answer stays empty rather than becoming a question the scientist
    was never asked.
    """
    _patch_call(monkeypatch, {**_ANSWER, "question": "", "options": []})

    assert await repair.repair_questions("Understood -- noted.") == []


async def test_a_failed_repair_costs_the_turn_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn without buttons is answerable by typing; a failed turn is not."""
    _patch_call(monkeypatch, RuntimeError("provider down"))

    assert await repair.repair_questions("Which model system?") == []


async def test_a_single_option_is_not_a_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalization is shared with the block's own path, not re-implemented."""
    _patch_call(monkeypatch, {**_ANSWER, "options": [{"label": "Yes"}]})

    assert await repair.repair_questions("Proceed?") == []


async def test_an_empty_message_never_reaches_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_call(monkeypatch, _ANSWER)

    assert await repair.repair_questions("   ") == []
    assert calls == []

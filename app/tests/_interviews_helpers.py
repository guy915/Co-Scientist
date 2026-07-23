"""Shared builders for the interview test modules.

These helpers are imported by both ``test_interviews.py`` (endpoint and field
CRUD cases) and ``test_interviews_model.py`` (direct ``_call_interview_model``
cases), so they live in a non-test module to avoid pytest collecting them.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any


@dataclasses.dataclass(frozen=True)
class InterviewFields:
    """The structured fields one interview-model response carries."""

    challenge: str = "How can resistant bacteria regain drug susceptibility?"
    focus: list[str] | None = None
    preferences: list[str] | None = None
    title: str | None = None
    completed: bool = False


def _response(
    message: str, fields: InterviewFields | None = None
) -> dict[str, Any]:
    fields = fields or InterviewFields()
    return {
        "assistant_message": message,
        "research_challenge": fields.challenge,
        "focus_area": fields.focus or [],
        "preferences": fields.preferences or [],
        "title": fields.title,
        "completed": fields.completed,
    }


def _fake_stream(content: str, reasoning: str = "") -> Any:
    """Build a litellm-style streaming completion.

    Mirrors the real DeepSeek delta order verified against the live API: the
    whole chain of thought arrives as ``reasoning_content`` deltas before the
    first ``content`` delta.

    Args:
        content: The answer text, delivered as a single content delta.
        reasoning: Optional chain of thought delivered before the answer.

    Returns:
        An async iterator of litellm-shaped streaming chunks.
    """

    def _chunk(
        *, reasoning_content: str | None = None, content: str | None = None
    ) -> SimpleNamespace:
        delta = SimpleNamespace(
            reasoning_content=reasoning_content, content=content
        )
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _chunks() -> Any:
        if reasoning:
            yield _chunk(reasoning_content=reasoning)
        yield _chunk(content=content)

    return _chunks()

"""Shared builders for the interview test modules.

These helpers are imported by ``test_interviews.py`` (endpoint and field
CRUD cases), ``test_interviews_model.py`` (direct ``_call_interview_model``
cases) and ``test_run_title_from_interview.py`` (the title a completed
interview hands the run it seeds), so they live in a non-test module to
avoid pytest collecting them.
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app import interviews


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


def _interview_payload(response: Any) -> dict[str, Any]:
    """Return the interview carried by a streamed turn's terminal frame.

    Args:
        response: The TestClient response for a streamed interview endpoint.

    Returns:
        The interview row from the closing ``interview`` frame.

    Raises:
        AssertionError: If the stream carried no ``interview`` frame, which
            means the turn errored instead of resolving.
    """
    for line in response.text.splitlines():
        if not line.startswith("data: "):
            continue
        event = json.loads(line[len("data: ") :])
        if event["type"] == "interview":
            return cast(dict[str, Any], event["interview"])
    raise AssertionError(f"no interview frame in stream: {response.text!r}")


def _patch_model_sequence(
    monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, Any]]
) -> None:
    """Patch the interview model to return each response in turn."""
    replies = iter(responses)

    async def _model(
        _interview: dict[str, Any], _on_reasoning: Any = None
    ) -> dict[str, Any]:
        return next(replies)

    monkeypatch.setattr(interviews, "_call_interview_model", _model)


def _antibiotic_responses() -> list[dict[str, Any]]:
    """Return the three model turns of the antibiotic-resistance interview."""
    return [
        _response("Which resistance mechanism should the study prioritize?"),
        _response(
            "What models, constraints, or exclusions should guide it?",
            InterviewFields(focus=["Efflux-pump regulation"]),
        ),
        _response(
            "The goal is ready for run configuration.",
            InterviewFields(
                focus=["Efflux-pump regulation"],
                preferences=[
                    "Use clinical Gram-negative isolates",
                    "Exclude new antibiotic discovery",
                ],
                title="Restoring Antibiotic Susceptibility",
                completed=True,
            ),
        ),
    ]


def _run_antibiotic_interview(
    client: TestClient, headers: dict[str, str]
) -> tuple[str, Any, Any, Any]:
    """Drive the three-turn antibiotic interview; return id and responses."""
    created = client.post(
        "/api/interviews",
        headers=headers,
        json={
            "research_challenge": (
                "How can resistant bacteria regain drug susceptibility?"
            )
        },
    )
    interview_id = _interview_payload(created)["id"]
    second = client.post(
        f"/api/interviews/{interview_id}/turns",
        headers=headers,
        json={"content": "Prioritize efflux-pump regulation."},
    )
    final = client.post(
        f"/api/interviews/{interview_id}/turns",
        headers=headers,
        json={
            "content": (
                "Use clinical Gram-negative isolates and exclude new "
                "antibiotic discovery."
            )
        },
    )
    return interview_id, created, second, final


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

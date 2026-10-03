# A configured semantic screen with unreachable credentials is a failed control
# and must refuse.

from __future__ import annotations

import logging
import types
from typing import Any

import pytest

from app import safety
from app.safety import screen_contextual
from tests._process_mode_helpers import FakeProcessMode

from ._llm_fake_backend import install_completion_backend


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    # Repeated prompts use different fake replies; cache isolation prevents
    # replaying an earlier verdict.
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        yield


def _fake_semantic_response(content: str) -> Any:

    async def _completion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    return _completion


def _install(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    install_completion_backend(monkeypatch, _fake_semantic_response(content))


async def test_missing_credential_refuses_and_warns(
    caplog: pytest.LogCaptureFixture, fake_process_mode: FakeProcessMode
) -> None:
    fake_process_mode.online(credential=False)
    with caplog.at_level(logging.WARNING, logger="app.safety.semantic"):
        decision = await screen_contextual("A benign research goal.", "intake")

    assert decision.decision == "hold"
    assert decision.requires_review is True
    assert decision.risk_domains == ["assessment_unavailable"]
    assert decision.assessor.endswith(":no_credential")
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "the refusal must be visible in the log"
    assert "credential" in warnings[0].getMessage().lower()


async def test_disabled_screen_still_returns_the_baseline(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    fake_process_mode.online(credential=False)
    decision = await screen_contextual("A benign research goal.", "intake")

    assert decision.decision == "allow"
    assert decision.assessor == "deterministic"


async def test_model_cannot_downgrade_a_deterministic_redaction(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    fake_process_mode.online()
    _install(monkeypatch, '{"category":"allowed","reason":"t"}')
    markdown = "# Report\nThis programme is explicitly dual-use."
    baseline = safety.screen_final(markdown)
    assert baseline.decision == "redact"

    decision = await screen_contextual(
        markdown, "final", deterministic=baseline
    )

    assert decision.decision == "redact"


async def test_model_may_raise_the_deterministic_verdict(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    fake_process_mode.online()
    _install(monkeypatch, '{"category":"prohibited","reason":"t"}')
    decision = await screen_contextual("Ordinary looking text.", "final")

    assert decision.decision == "block"
    assert decision.assessor.startswith("semantic:")


async def test_a_markdown_fenced_answer_still_allows(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    # json_object providers can wrap JSON in fences; use the shared parser
    # rather than rejecting valid answers.
    fake_process_mode.online()
    _install(
        monkeypatch,
        '```json\n{"category":"allowed","reason":"benign"}\n```',
    )

    decision = await screen_contextual("A benign research goal.", "intake")

    assert decision.decision == "allow"
    assert decision.assessor.startswith("semantic:")


async def test_a_persistently_bad_reply_still_falls_back_to_unavailable(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    # Exhausted parse retries must produce a review hold, never raise or allow.
    fake_process_mode.online()
    _install(monkeypatch, "not json at all, and no fence to strip either")

    decision = await screen_contextual("A benign research goal.", "intake")

    assert decision.decision == "hold"
    assert decision.risk_domains == ["assessment_unavailable"]
    assert decision.assessor.endswith(":error")

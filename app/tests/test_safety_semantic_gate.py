"""The contextual screen must refuse rather than degrade to regex-only.

A configured semantic screen whose model has no reachable credential is a
safety control that is not running. It used to return the deterministic
baseline with no log line, so a misconfigured deployment looked identical to a
clean one. It now refuses and says why.

``_call_semantic_safety_model`` is routed through the engine's
``call_llm_json`` seam (see its docstring), so every test here faking the
model's answer patches the engine's own completion boundary
(``litellm.acompletion``) rather than ``app.safety_semantic``'s -- that
module no longer calls litellm directly at all.
"""

from __future__ import annotations

import logging
import types
from typing import Any

import pytest

from app import safety
from app.safety import screen_contextual
from tests._process_mode_helpers import FakeProcessMode


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    """Force every call in this file to miss the engine's response cache.

    Mirrors ``test_claim_verifier.py``: several tests here send the same
    prompt (the same goal text and stage) with a different faked reply to
    prove a different code path, and the cache would otherwise replay an
    earlier test's response instead of calling the fake at all.
    """
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        yield


def _fake_semantic_response(content: str) -> Any:
    """Build a minimal litellm response carrying raw completion text."""

    async def _completion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    return _completion


def _install(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    """Patch the engine's completion boundary with a fixed reply."""
    import litellm

    monkeypatch.setattr(
        litellm, "acompletion", _fake_semantic_response(content)
    )


async def test_missing_credential_refuses_and_warns(
    caplog: pytest.LogCaptureFixture, fake_process_mode: FakeProcessMode
) -> None:
    """No credential for the configured screen holds instead of allowing."""
    fake_process_mode.online(credential=False)
    with caplog.at_level(logging.WARNING, logger="app.safety_semantic"):
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
    """Turning the screen off is configuration, not a broken safety control."""
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    fake_process_mode.online(credential=False)
    decision = await screen_contextual("A benign research goal.", "intake")

    assert decision.decision == "allow"
    assert decision.assessor == "deterministic"


async def test_model_cannot_downgrade_a_deterministic_redaction(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """The deterministic rules are pre-blocks the model may raise, not clear."""
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
    """The model stays primary wherever it is stricter than the rules."""
    fake_process_mode.online()
    _install(monkeypatch, '{"category":"prohibited","reason":"t"}')
    decision = await screen_contextual("Ordinary looking text.", "final")

    assert decision.decision == "block"
    assert decision.assessor.startswith("semantic:")


async def test_a_markdown_fenced_answer_still_allows(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """A json_object reply wrapped in a Markdown fence must not hold the run.

    Reproduces the 2026-09-05 production incident (run bdc73bf3): the free
    fallback chain's first rung (``minimax/minimax-m3:free``) answers a
    ``response_format={"type": "json_object"}`` request with the JSON
    wrapped in a ```json fence. The bare ``json.loads`` this module used to
    call raised "Expecting value: line 1 column 1" on that shape, which
    every caller treats as a provider failure and holds the run for human
    review. The engine's ``call_llm_json`` seam strips the fence before
    parsing, so the same answer must now resolve to a clean allow.
    """
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
    """Unparseable-forever must still hold for review, not raise to the caller.

    ``call_llm_json`` retries a handful of times and then raises once every
    attempt is exhausted (no fallback is registered for this schema); the
    existing ``except Exception`` in ``screen_contextual`` must still catch
    that and produce the same refusal it always has.
    """
    fake_process_mode.online()
    _install(monkeypatch, "not json at all, and no fence to strip either")

    decision = await screen_contextual("A benign research goal.", "intake")

    assert decision.decision == "hold"
    assert decision.risk_domains == ["assessment_unavailable"]
    assert decision.assessor.endswith(":error")

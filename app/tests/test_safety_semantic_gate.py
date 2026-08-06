"""The contextual screen must refuse rather than degrade to regex-only.

A configured semantic screen whose model has no reachable credential is a
safety control that is not running. It used to return the deterministic
baseline with no log line, so a misconfigured deployment looked identical to a
clean one. It now refuses and says why.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app import safety
from app.safety import screen_contextual


def _fake_semantic_response(category: str) -> SimpleNamespace:
    """Build a minimal litellm response carrying one safety category."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=f'{{"category":"{category}","reason":"t"}}'
                )
            )
        ]
    )


async def test_missing_credential_refuses_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No credential for the configured screen holds instead of allowing."""
    monkeypatch.setattr(safety, "_offline_pinned_process", lambda: False)
    monkeypatch.setattr(
        safety, "_semantic_credential_available", lambda _: False
    )
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning the screen off is configuration, not a broken safety control."""
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    monkeypatch.setattr(
        safety, "_semantic_credential_available", lambda _: False
    )
    decision = await screen_contextual("A benign research goal.", "intake")

    assert decision.decision == "allow"
    assert decision.assessor == "deterministic"


async def test_model_cannot_downgrade_a_deterministic_redaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deterministic rules are pre-blocks the model may raise, not clear."""
    import litellm

    async def allow_completion(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("allowed")

    monkeypatch.setattr(safety, "_offline_pinned_process", lambda: False)
    monkeypatch.setattr(
        safety, "_semantic_credential_available", lambda _: True
    )
    monkeypatch.setattr(litellm, "acompletion", allow_completion)
    markdown = "# Report\nThis programme is explicitly dual-use."
    baseline = safety.screen_final(markdown)
    assert baseline.decision == "redact"

    decision = await screen_contextual(
        markdown, "final", deterministic=baseline
    )

    assert decision.decision == "redact"


async def test_model_may_raise_the_deterministic_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model stays primary wherever it is stricter than the rules."""
    import litellm

    async def block_completion(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("prohibited")

    monkeypatch.setattr(safety, "_offline_pinned_process", lambda: False)
    monkeypatch.setattr(
        safety, "_semantic_credential_available", lambda _: True
    )
    monkeypatch.setattr(litellm, "acompletion", block_completion)
    decision = await screen_contextual("Ordinary looking text.", "final")

    assert decision.decision == "block"
    assert decision.assessor.startswith("semantic:")

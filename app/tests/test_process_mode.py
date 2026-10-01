"""The process-mode seam: one installed adapter answers every reader.

The behaviour the adapters implement is pinned elsewhere, through the
environment (``test_provider_selection.py`` for the offline truth table,
``test_safety_process_modes.py`` for the fail-closed screen). These cases pin
the seam itself: that installing an adapter reaches every consumer, which is
what lets a test state a process fact once instead of patching each module
that happens to read it.
"""

from __future__ import annotations

import pytest

from app import engine_adapter, offline_guard, process_mode
from app.engine_adapter import provider
from tests._process_mode_helpers import FakeProcessMode


def test_one_adapter_answers_every_offline_reader(
    fake_process_mode: FakeProcessMode,
) -> None:
    """Online reaches the re-exports, the run-backend rule, the chat guard."""
    fake_process_mode.online()

    assert process_mode.offline_mode() is False
    assert engine_adapter.offline_mode() is False
    assert provider.offline_mode() is False
    assert provider.resolve_offline_backend({}) is False
    assert offline_guard.remote_chat_allowed() is True

    fake_process_mode.offline = True

    assert process_mode.offline_mode() is True
    assert engine_adapter.offline_mode() is True
    assert provider.offline_mode() is True
    assert provider.resolve_offline_backend({}) is True
    assert offline_guard.remote_chat_allowed() is False


def test_a_credential_callable_is_asked_per_model(
    fake_process_mode: FakeProcessMode,
) -> None:
    """A test can vary the answer by model, and see which models were asked."""
    asked: list[str] = []

    def credentialed(model: str) -> bool:
        asked.append(model)
        return model.startswith("openrouter/")

    fake_process_mode.online(credential=credentialed)

    assert process_mode.credential_available("openrouter/x") is True
    assert process_mode.credential_available("anthropic/y") is False
    assert asked == ["openrouter/x", "anthropic/y"]


def test_install_returns_the_replaced_adapter_so_it_can_be_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restoring what ``install`` returned puts the env-derived answer back."""
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    fake = FakeProcessMode()
    fake.online()

    previous = process_mode.install(fake)
    try:
        assert isinstance(previous, process_mode.EnvProcessMode)
        assert process_mode.offline_mode() is False
    finally:
        process_mode.install(previous)

    assert process_mode.offline_mode() is True

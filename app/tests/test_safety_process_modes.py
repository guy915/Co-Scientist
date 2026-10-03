# Forced offline is a deliberate mode; partial credentials are a failed safety
# control and must refuse.

from __future__ import annotations

import types
from collections.abc import Iterator
from typing import Any

import pytest

from app import credentials, safety
from app.config import settings

from ._llm_fake_backend import install_completion_backend

_MODEL = "openrouter/test-safety-model"
_OTHER_PROVIDER_KEY = "ANTHROPIC_API_KEY"
_MODEL_PROVIDER_KEY = "OPENROUTER_API_KEY"
_HELD_TEXT = "A benign research goal."


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Iterator[None]:
    # Repeated prompts use different fake replies; cache isolation prevents
    # replaying an earlier verdict.
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        yield


@pytest.fixture(autouse=True)
def _screen_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "semantic_safety_enabled", True)
    monkeypatch.setattr(settings, "semantic_safety_model", _MODEL)


def _force_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")


def _online_with(monkeypatch: pytest.MonkeyPatch, *keys: str) -> None:
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    for key in keys:
        monkeypatch.setenv(key, "sk-test")


class _Provider:
    def __init__(self, category: str = "allowed") -> None:
        self.calls: list[dict[str, Any]] = []
        self._category = category

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        content = f'{{"category":"{self._category}","reason":"model"}}'
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> _Provider:
    fake = _Provider()
    install_completion_backend(monkeypatch, fake)
    return fake


async def test_a_forced_offline_process_returns_the_baseline_silently(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _force_offline(monkeypatch)
    monkeypatch.setenv(_MODEL_PROVIDER_KEY, "sk-test")

    decision = await safety.screen_contextual(_HELD_TEXT, "intake")

    assert decision.decision == "allow"
    assert decision.assessor == "deterministic"
    assert provider.calls == []


async def test_a_keyless_process_is_pinned_offline_and_returns_the_baseline(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _online_with(monkeypatch)

    decision = await safety.screen_contextual(_HELD_TEXT, "intake")

    assert decision.decision == "allow"
    assert decision.assessor == "deterministic"
    assert provider.calls == []


async def test_a_partially_configured_deployment_refuses_instead_of_allowing(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _online_with(monkeypatch, _OTHER_PROVIDER_KEY)

    decision = await safety.screen_contextual(_HELD_TEXT, "intake")

    assert decision.decision == "hold"
    assert decision.requires_review is True
    assert decision.risk_domains == ["assessment_unavailable"]
    assert decision.assessor.endswith(":no_credential")
    assert provider.calls == []


async def test_a_partial_deployment_keeps_a_deterministic_redaction(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _online_with(monkeypatch, _OTHER_PROVIDER_KEY)
    markdown = "# Report\nThis programme is explicitly dual-use."
    baseline = safety.screen_final(markdown)
    assert baseline.decision == "redact"

    decision = await safety.screen_contextual(
        markdown, "final", deterministic=baseline
    )

    assert decision.decision == "redact"
    assert provider.calls == []


async def test_the_models_own_credential_opens_the_screen(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _online_with(monkeypatch, _MODEL_PROVIDER_KEY)

    decision = await safety.screen_contextual(_HELD_TEXT, "intake")

    assert decision.assessor == f"semantic:{_MODEL}"
    assert len(provider.calls) == 1


async def test_a_scoped_byok_key_opens_the_screen_for_a_partial_deployment(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _online_with(monkeypatch, _OTHER_PROVIDER_KEY)
    byok = credentials.ByokCredential(
        provider="openrouter", api_key="sk-byok", model=_MODEL
    )

    with credentials.scoped_byok(byok):
        decision = await safety.screen_contextual(_HELD_TEXT, "intake")

    assert decision.assessor.startswith("semantic:")
    assert len(provider.calls) == 1


async def test_a_disabled_screen_is_configuration_not_a_refusal(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _online_with(monkeypatch, _OTHER_PROVIDER_KEY)
    monkeypatch.setattr(settings, "semantic_safety_enabled", False)

    decision = await safety.screen_contextual(_HELD_TEXT, "intake")

    assert decision.decision == "allow"
    assert decision.assessor == "deterministic"
    assert provider.calls == []


async def test_a_hold_is_assessed_when_the_model_is_credentialed(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _online_with(monkeypatch, _MODEL_PROVIDER_KEY)

    verdict = await safety.assess_hold_contextually(
        "no-such-run", _HELD_TEXT, "hypothesis"
    )

    assert verdict is not None
    assert verdict.decision == "allow"
    assert len(provider.calls) == 1


async def test_a_hold_is_not_assessed_by_an_offline_pinned_process(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _force_offline(monkeypatch)
    monkeypatch.setenv(_MODEL_PROVIDER_KEY, "sk-test")

    verdict = await safety.assess_hold_contextually(
        "no-such-run", _HELD_TEXT, "hypothesis"
    )

    assert verdict is None
    assert provider.calls == []


async def test_a_hold_is_not_assessed_without_the_models_credential(
    monkeypatch: pytest.MonkeyPatch, provider: _Provider
) -> None:
    _online_with(monkeypatch, _OTHER_PROVIDER_KEY)

    verdict = await safety.assess_hold_contextually(
        "no-such-run", _HELD_TEXT, "hypothesis"
    )

    assert verdict is None
    assert provider.calls == []


async def test_a_hold_is_not_assessed_when_the_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def _down(**_kwargs: Any) -> None:
        raise RuntimeError("provider unavailable")

    install_completion_backend(monkeypatch, _down)
    _online_with(monkeypatch, _MODEL_PROVIDER_KEY)

    verdict = await safety.assess_hold_contextually(
        "no-such-run", _HELD_TEXT, "hypothesis"
    )

    assert verdict is None

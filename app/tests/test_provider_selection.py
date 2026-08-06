"""Tests for provider selection in ``app.engine_adapter.provider``.

Covers ``select_provider`` (now always ``"engine"``, with the engine a hard
dependency), the ``offline_mode`` truth table, the ``_engine_importable``
exception fallback, and the module-level sibling-engine sys.path bridging that
runs at import time.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys

import pytest

from app import safety
from app.config import PROVIDER_CREDENTIAL_ENV
from app.engine_adapter import provider

_ALL_CREDENTIAL_ENV = tuple(
    name for names in PROVIDER_CREDENTIAL_ENV.values() for name in names
)


def _clear_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every provider credential this app knows how to recognize."""
    for key in _ALL_CREDENTIAL_ENV:
        monkeypatch.delenv(key, raising=False)


def test_a_non_default_provider_key_counts_as_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key for any known provider must not read as keyless.

    The defaults are DeepSeek on every tier, so a deployment credentialed
    through some other provider is the case where a second, narrower
    notion of "has a key" would silently route every run to the offline
    backend.
    """
    _clear_credentials(monkeypatch)
    assert provider._has_provider_key() is False

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert provider._has_provider_key() is True


@pytest.mark.parametrize("credential", _ALL_CREDENTIAL_ENV)
def test_every_known_credential_keeps_the_run_on_a_real_provider(
    monkeypatch: pytest.MonkeyPatch, credential: str
) -> None:
    """Any credential the app recognizes anywhere must defeat offline mode.

    The offline-mode probe and the semantic safety screen each carried their
    own provider table and drifted apart: ``GOOGLE_API_KEY`` was known only
    to safety, so a deployment credentialed that way looked keyless here and
    ran every run on the deterministic offline backend -- no error, just
    silently fabricated science. Parametrized over the shared map so a
    provider added to it can never be recognized by only one reader again.
    """
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    _clear_credentials(monkeypatch)
    assert provider.offline_mode() is True

    monkeypatch.setenv(credential, "sk-test")
    assert provider._has_provider_key() is True
    assert provider.offline_mode() is False


def test_credential_lookup_has_one_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both readers answer "is this provider usable" from the same map.

    Pins the consolidation rather than the two answers: a provider added to
    ``PROVIDER_CREDENTIAL_ENV`` has to reach the offline-mode probe and the
    safety screen together, which is precisely what two hand-kept copies
    stopped doing.
    """
    _clear_credentials(monkeypatch)
    monkeypatch.setitem(
        PROVIDER_CREDENTIAL_ENV, "fictional", ("FICTIONAL_KEY",)
    )
    monkeypatch.setenv("FICTIONAL_KEY", "sk-test")

    assert provider._has_provider_key() is True
    assert safety._semantic_credential_available("fictional/model-x") is True


def test_engine_importable_returns_false_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(name: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(importlib.util, "find_spec", _boom)
    assert provider._engine_importable() is False


@pytest.mark.parametrize("has_key", [False, True])
def test_select_provider_is_always_engine(
    monkeypatch: pytest.MonkeyPatch, has_key: bool
) -> None:
    """The mock is retired: selection is engine regardless of key presence."""
    monkeypatch.setattr(provider, "_has_provider_key", lambda: has_key)
    monkeypatch.setattr(provider, "_engine_importable", lambda: True)
    assert provider.select_provider() == "engine"


def test_select_provider_raises_when_engine_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine is a hard dependency; an absent package fails loudly."""
    monkeypatch.setattr(provider, "_engine_importable", lambda: False)
    with pytest.raises(RuntimeError, match="hard dependency"):
        provider.select_provider()


@pytest.mark.parametrize(
    ("force_offline", "force_mock", "has_key", "expected"),
    [
        (None, None, True, False),
        (None, None, False, True),
        ("1", None, True, True),
        (None, "1", True, True),
    ],
    ids=[
        "real_when_key_present",
        "offline_when_no_provider_key",
        "offline_when_force_offline",
        "offline_when_force_mock_deprecated_alias",
    ],
)
def test_offline_mode(
    monkeypatch: pytest.MonkeyPatch,
    force_offline: str | None,
    force_mock: str | None,
    has_key: bool,
    expected: bool,
) -> None:
    """``offline_mode`` is forced by either env flag or a missing key."""
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    if force_offline is not None:
        monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", force_offline)
    if force_mock is not None:
        monkeypatch.setenv("COSCIENTIST_FORCE_MOCK", force_mock)
    monkeypatch.setattr(provider, "_has_provider_key", lambda: has_key)
    assert provider.offline_mode() is expected


def test_missing_engine_src_gets_added_to_syspath_on_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The module-level sys.path bridge fires when the src dir is absent.

    In this checkout the editable install's .pth file already puts the
    sibling engine's src on sys.path before provider.py's own manual insert
    runs, so that line is otherwise unreachable. Removing the entry and
    reloading the module reproduces the "not yet on sys.path" case the
    bridge exists for.
    """
    engine_src = provider._engine_src
    assert os.path.isdir(engine_src), "test assumes a local engine checkout"

    trimmed = [p for p in sys.path if p != engine_src]
    monkeypatch.setattr(sys, "path", trimmed)
    assert engine_src not in sys.path

    importlib.reload(provider)

    assert engine_src in sys.path

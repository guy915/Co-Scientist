"""Tests for provider selection in ``app.engine_adapter.provider``.

Covers the ``select_provider`` branches beyond the ``COSCIENTIST_FORCE_MOCK``
short-circuit (already exercised everywhere via the autouse ``isolated_db``
fixture), the ``_engine_importable`` exception fallback, and the module-level
sibling-engine sys.path bridging that runs at import time.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys

import pytest

from app.engine_adapter import provider
from app.engine_adapter.engine_stream import _real_engine_stream


def test_engine_importable_returns_false_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(name: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(importlib.util, "find_spec", _boom)
    assert provider._engine_importable() is False


@pytest.mark.parametrize(
    ("has_key", "engine_importable", "expected"),
    [
        (False, None, "mock"),
        (True, False, "mock"),
        (True, True, "engine"),
    ],
    ids=[
        "mock_when_no_provider_key",
        "mock_when_engine_not_importable",
        "engine_when_available",
    ],
)
def test_select_provider(
    monkeypatch: pytest.MonkeyPatch,
    has_key: bool,
    engine_importable: bool | None,
    expected: str,
) -> None:
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setattr(provider, "_has_provider_key", lambda: has_key)
    if engine_importable is not None:
        monkeypatch.setattr(
            provider, "_engine_importable", lambda: engine_importable
        )
    assert provider.select_provider() == expected


def test_missing_engine_never_substitutes_mock_science(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run resolved as real fails loudly if its engine disappears."""

    async def _emit(
        _kind: str, _payload: dict[str, object]
    ) -> dict[str, object]:
        return {}

    monkeypatch.setattr(
        "app.engine_adapter.engine_stream._import_hypothesis_generator",
        lambda: None,
    )

    with pytest.raises(RuntimeError, match="refusing to substitute mock"):
        _real_engine_stream(
            "goal",
            "run-id",
            "standard",
            {},
            cancelled=None,
            db_path=None,
            sleep_seconds=0,
            emit=_emit,
        )


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

from __future__ import annotations

import importlib.util
import pathlib
import sys
from collections.abc import Callable
from typing import Any

import pytest

_ENGINE_FAKE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "_llm_fake.py"
)


def load_engine_fake() -> Any:
    spec = importlib.util.spec_from_file_location(
        "engine_llm_fake", _ENGINE_FAKE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def install_completion_backend(
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[..., Any],
    *,
    requests: list[dict[str, Any]] | None = None,
    supports_json_schema: Callable[[str], bool] | None = None,
) -> Any:
    # Install the fake behind the offline router and preserve its JSON-schema
    # capability protocol.
    from co_scientist.llm.request import backend
    from co_scientist.offline.llm import OfflineRouter

    engine_fake = load_engine_fake()
    fake = engine_fake.FakeBackend(
        respond, requests=requests, supports_json_schema=supports_json_schema
    )
    engine_fake.restore_backend_at_teardown(monkeypatch)
    backend.install_backend(OfflineRouter(fake))
    return fake

"""Shared builders for the resume launcher test module.

Not a test module (underscore prefix), so pytest does not collect it. It loads
the engine's LLM fake by file path and installs it, so the legacy-checkpoint
re-bootstrap test in ``test_resume_engine.py`` can drive a fresh durable run
without a real provider.
"""

from __future__ import annotations

import importlib.util
import pathlib
from typing import Any

import pytest

# Load the engine's LLM fake by file path: it lives under engine/tests, which
# is not importable as a package from the app's own ``tests`` namespace.
_ENGINE_FAKE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "_llm_fake.py"
)


def _load_engine_fake() -> Any:
    spec = importlib.util.spec_from_file_location(
        "engine_llm_fake", _ENGINE_FAKE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_fake_engine_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake the engine's LLM boundary and force literature review off."""
    _load_engine_fake().install_fake_llm(monkeypatch)
    # Hard kill switch: never probe the (possibly live) local MCP server.
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "0")
    # These tests exercise resume, not the safety gate; keep the app-level
    # semantic screen offline (it makes a real provider call) so a
    # rate-limited or degraded assessment cannot spuriously hold the run.
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)

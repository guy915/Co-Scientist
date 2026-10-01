"""Shared builders for the resume launcher test module.

Not a test module (underscore prefix), so pytest does not collect it. It
installs the engine's LLM fake (loaded by ``_llm_fake_backend``), so the
legacy-checkpoint re-bootstrap test in ``test_resume_engine.py`` can drive a
fresh durable run without a real provider.
"""

from __future__ import annotations

import pytest

from ._llm_fake_backend import load_engine_fake


def _install_fake_engine_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake the engine's LLM boundary and force literature review off."""
    load_engine_fake().install_fake_llm(monkeypatch)
    # Hard kill switch: never probe the (possibly live) local MCP server.
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "0")
    # These tests exercise resume, not the safety gate; keep the app-level
    # semantic screen offline (it makes a real provider call) so a
    # rate-limited or degraded assessment cannot spuriously hold the run.
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)

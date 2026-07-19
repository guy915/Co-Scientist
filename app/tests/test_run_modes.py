"""Tests for run-mode setup config and guidance."""

from __future__ import annotations

from app import run_modes


def test_setup_config_stores_audience_context() -> None:
    setup = run_modes.setup_config(
        research_goal="goal",
        audience_context="LAB BACKGROUND",
    )
    assert setup["audience_context"] == "LAB BACKGROUND"


def test_setup_config_omits_empty_audience_context() -> None:
    setup = run_modes.setup_config(research_goal="goal")
    assert "audience_context" not in setup


def test_setup_guidance_renders_audience_context() -> None:
    setup = run_modes.setup_config(
        research_goal="goal",
        audience_context="LAB BACKGROUND",
    )
    guidance = run_modes.setup_guidance(setup)
    assert "Audience context:" in guidance
    assert "LAB BACKGROUND" in guidance


def test_setup_guidance_without_audience_context() -> None:
    setup = run_modes.setup_config(research_goal="goal")
    assert "Audience context:" not in run_modes.setup_guidance(setup)

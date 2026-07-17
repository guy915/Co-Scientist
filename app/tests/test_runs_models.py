"""Tests for create-run config resolution with audience context."""

from __future__ import annotations

from app.runs_models import CreateRunRequest, _build_create_run_config


def test_sbi_ucd_injects_audience_context() -> None:
    req = CreateRunRequest(research_goal="goal", audience="sbi_ucd")
    config, _focus, _tier = _build_create_run_config(req)
    assert "SBI" in config["setup"]["audience_context"]


def test_general_audience_has_no_context() -> None:
    req = CreateRunRequest(research_goal="goal", audience="general")
    config, _focus, _tier = _build_create_run_config(req)
    assert "audience_context" not in config["setup"]


def test_missing_audience_has_no_context() -> None:
    req = CreateRunRequest(research_goal="goal")
    config, _focus, _tier = _build_create_run_config(req)
    assert "audience_context" not in config["setup"]


def test_audience_persisted_in_config() -> None:
    req = CreateRunRequest(research_goal="goal", audience="sbi_ucd")
    config, _focus, _tier = _build_create_run_config(req)
    assert config["audience"] == "sbi_ucd"

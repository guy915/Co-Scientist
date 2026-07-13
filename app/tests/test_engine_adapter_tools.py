"""Tests for tools-config wiring: adapter forwarding, validation, /status.

Production sets ``TOOLS_CONFIG=...indra_cancer.yaml`` but the app adapter never
forwarded it to ``HypothesisGenerator``, so real runs silently ran the default
(PubMed-only) tools. These pin the forwarding, the loud startup validation of a
misconfigured path, and the /status disclosure of the effective tools config.
"""

from __future__ import annotations

import pathlib
from typing import Any, ClassVar

import pytest

from app.config import settings
from app.engine_adapter.opts import _build_generator
from app.engine_adapter.tools import (
    tools_config_report,
    validate_tools_config,
)

# The engine ships this example config; a real, readable local YAML to
# validate/enumerate against without needing a network fetch.
_INDRA_CONFIG = str(
    pathlib.Path(__file__).resolve().parents[2]
    / "engine"
    / "src"
    / "co_scientist"
    / "config"
    / "examples"
    / "indra_cancer.yaml"
)


def _cfg() -> dict[str, Any]:
    """A resolved run-config dict with the numeric keys the adapter reads."""
    return {
        "max_iterations": 1,
        "initial_hypotheses_count": 4,
        "evolution_max_count": 4,
        "tournament_pairs": 6,
        "evidence_count": 4,
        "k_factor": 36,
    }


class _FakeGenerator:
    """Captures the kwargs the adapter passes to HypothesisGenerator."""

    last_kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        _FakeGenerator.last_kwargs = kwargs


def test_build_generator_forwards_configured_tools_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured tools_config reaches HypothesisGenerator."""
    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)
    _build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["tools_config"] == _INDRA_CONFIG


def test_build_generator_forwards_none_tools_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset tools_config forwards None (engine uses its defaults)."""
    monkeypatch.setattr(settings, "tools_config", None)
    _build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["tools_config"] is None


def test_build_generator_forwards_run_elo_k_factor() -> None:
    """The persisted run K-factor governs real-engine Elo updates."""
    _build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["elo_k_factor"] == 36


def test_validate_tools_config_accepts_none() -> None:
    """No configured tools_config is valid (defaults apply)."""
    validate_tools_config(None)  # must not raise


def test_validate_tools_config_accepts_readable_path() -> None:
    """A readable local YAML path validates."""
    validate_tools_config(_INDRA_CONFIG)  # must not raise


def test_validate_tools_config_accepts_url() -> None:
    """A URL is passed through without a local-file check."""
    validate_tools_config("https://example.com/tools.yaml")  # must not raise


def test_validate_tools_config_raises_on_unreadable_path() -> None:
    """A configured local path that does not exist fails loudly."""
    with pytest.raises(RuntimeError, match="tools_config"):
        validate_tools_config("/no/such/tools.yaml")


def test_tools_config_report_enumerates_enabled_tools() -> None:
    """The /status report resolves a readable config to its enabled tools."""
    report = tools_config_report(_INDRA_CONFIG)
    assert report["tools_config"] == _INDRA_CONFIG
    assert report["tools_config_valid"] is True
    assert "indra_statements" in report["enabled_tools"]


def test_tools_config_report_marks_bad_path_invalid() -> None:
    """A misconfigured path is reported invalid with no enabled tools."""
    report = tools_config_report("/no/such/tools.yaml")
    assert report["tools_config_valid"] is False
    assert report["enabled_tools"] is None


def test_tools_config_report_none_is_valid_defaults() -> None:
    """An unset config is valid; enabled tools default to None."""
    report = tools_config_report(None)
    assert report["tools_config"] is None
    assert report["tools_config_valid"] is True
    assert report["enabled_tools"] is None

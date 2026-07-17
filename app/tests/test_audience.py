"""Tests for the audience context loader."""

from __future__ import annotations

from app import audience


def test_sbi_ucd_returns_nonempty_context() -> None:
    text = audience.audience_context("sbi_ucd")
    assert "SBI" in text
    assert len(text) > 0


def test_other_audiences_return_empty() -> None:
    assert audience.audience_context("general") == ""
    assert audience.audience_context("google") == ""
    assert audience.audience_context(None) == ""
    assert audience.audience_context("bogus") == ""


def test_pattern_and_values_exposed() -> None:
    assert audience.VALID_AUDIENCES == ("general", "google", "sbi_ucd")
    assert audience.AUDIENCE_PATTERN == "^(general|google|sbi_ucd)$"

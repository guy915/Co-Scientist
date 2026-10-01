"""Tests for create-run request validation."""

from __future__ import annotations

from app.runs.models import CreateRunRequest


def test_stray_audience_field_is_ignored() -> None:
    """An old cached frontend sending the retired `audience` field must not 422.

    Pydantic's default ``extra="ignore"`` drops it silently, so a stale
    client is never broken by the field's removal.
    """
    req = CreateRunRequest(research_goal="goal", audience="sbi_ucd")

    assert not hasattr(req, "audience")

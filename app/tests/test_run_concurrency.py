"""Tests for the per-client concurrent-run ceiling.

The ceiling is uniform across tiers by construction now: ``start_run``
reads ``settings.max_concurrent_runs`` directly and never consults the
tier. (Heavier tiers used to be capped harder -- ultra at 1 -- which
blocked a researcher from running two deep investigations at once; per-run
spend is bounded by the tier's max_llm_calls budget instead.)

It is also *one* ceiling per identity: the reservation query used to
partition the count by the run's tier as well as its client, so a single
caller could hold ``max_concurrent_runs`` express runs plus as many
standard, extended, and ultra ones -- four times the advertised
allowance, on the heaviest tiers included.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from tests._client import make_client

_TIERS = ("express", "standard", "extended", "ultra")


def test_ceiling_is_configurable() -> None:
    """Operators can raise or lower the ceiling without a code change."""
    assert settings.max_concurrent_runs >= 3


def _start(client: TestClient, headers: dict[str, str], tier: str) -> int:
    """Create and start one run of ``tier``, returning the start status."""
    run_id = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": f"{tier} question", "tier": tier},
    ).json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", headers=headers, json={})
    return int(started.status_code)


def test_ceiling_is_one_total_across_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spreading runs across tiers does not multiply one client's allowance."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "max_concurrent_runs", 2)
    client = make_client()
    headers = {"X-Client-ID": "tier-hopper"}

    codes = [_start(client, headers, tier) for tier in _TIERS]

    # Two slots, four attempts: the first two are admitted whatever tier
    # they name, and the rest are refused.
    assert codes == [200, 200, 409, 409]

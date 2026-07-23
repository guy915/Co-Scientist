"""Unit tests for the diagnostics health checks and availability probes."""

from __future__ import annotations

import asyncio
import sys

import pytest

from app import diagnostics
from app.config import settings
from app.diagnostics import (
    DEGRADED,
    HEALTHY,
    PROBE_DOWN,
    PROBE_ERROR,
    PROBE_UP,
    UNHEALTHY,
    HealthCheck,
    ProbeResult,
    _run_probe,
    check_engine,
    check_store,
    clear_probe_cache,
    derive_health_status,
    probe_literature_stack_cached,
)


@pytest.fixture(autouse=True)
def _fresh_probe_cache() -> None:
    """Every test starts (and later tests resume) with an empty probe cache."""
    clear_probe_cache()


# --- health checks -----------------------------------------------------------


def test_check_store_ok_against_isolated_db(isolated_db: str) -> None:
    result = check_store(isolated_db)
    assert result.ok is True
    assert result.detail is None


def test_check_store_reports_failure_detail(tmp_path: object) -> None:
    # A directory is not a valid SQLite database file path.
    result = check_store(str(tmp_path))
    assert result.ok is False
    assert result.detail


def test_check_engine_reflects_importability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostics, "_engine_importable", lambda: True)
    assert check_engine().ok is True

    monkeypatch.setattr(diagnostics, "_engine_importable", lambda: False)
    result = check_engine()
    assert result.ok is False
    assert result.detail


def test_derive_health_status_unhealthy_when_store_down() -> None:
    status = derive_health_status(
        HealthCheck(ok=False, detail="boom"), HealthCheck(ok=True)
    )
    assert status == UNHEALTHY


def test_derive_health_status_degraded_when_key_but_no_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured provider key with no importable engine degrades health."""
    monkeypatch.setattr(diagnostics, "_has_provider_key", lambda: True)
    status = derive_health_status(
        HealthCheck(ok=True), HealthCheck(ok=False, detail="missing")
    )
    assert status == DEGRADED


def test_derive_health_status_healthy_in_pure_offline_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key and no engine is the normal offline mock setup, not degraded."""
    monkeypatch.setattr(diagnostics, "_has_provider_key", lambda: False)
    status = derive_health_status(
        HealthCheck(ok=True), HealthCheck(ok=False, detail="missing")
    )
    assert status == HEALTHY


# --- probe runner ------------------------------------------------------------


async def test_run_probe_maps_answers_to_up_and_down() -> None:
    async def _up() -> bool:
        return True

    async def _down() -> bool:
        return False

    up = await _run_probe(_up(), timeout=1.0)
    down = await _run_probe(_down(), timeout=1.0)
    assert (up.available, up.state, up.error) == (True, PROBE_UP, None)
    assert (down.available, down.state, down.error) == (False, PROBE_DOWN, None)


async def test_run_probe_times_out_as_error_state() -> None:
    async def _hangs() -> bool:
        await asyncio.sleep(5)
        return True

    result = await _run_probe(_hangs(), timeout=0.01)
    assert result.available is False
    assert result.state == PROBE_ERROR
    assert result.error is not None and "timed out" in result.error


async def test_run_probe_maps_exception_to_error_state() -> None:
    async def _raises() -> bool:
        raise ValueError("bad probe")

    result = await _run_probe(_raises(), timeout=1.0)
    assert result.available is False
    assert result.state == PROBE_ERROR
    assert result.error == "ValueError: bad probe"


# --- TTL cache ---------------------------------------------------------------


def _stub_probe_pair(
    calls: list[int],
) -> object:
    """Build a fake `_probe_literature_stack` that counts its invocations."""

    async def _stub() -> tuple[ProbeResult, ProbeResult, ProbeResult]:
        calls.append(1)
        return (
            ProbeResult(available=True, state=PROBE_UP),
            ProbeResult(available=False, state=PROBE_DOWN),
            ProbeResult(available=True, state=PROBE_UP),
        )

    return _stub


async def test_probe_cache_reuses_result_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        diagnostics, "_probe_literature_stack", _stub_probe_pair(calls)
    )
    monkeypatch.setattr(settings, "status_probe_cache_ttl_seconds", 60.0)

    first = await probe_literature_stack_cached()
    second = await probe_literature_stack_cached()

    assert len(calls) == 1
    assert first == second


async def test_probe_cache_expires_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        diagnostics, "_probe_literature_stack", _stub_probe_pair(calls)
    )
    monkeypatch.setattr(settings, "status_probe_cache_ttl_seconds", 0.0)

    await probe_literature_stack_cached()
    await probe_literature_stack_cached()

    assert len(calls) == 2


async def test_clear_probe_cache_forces_reprobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        diagnostics, "_probe_literature_stack", _stub_probe_pair(calls)
    )
    monkeypatch.setattr(settings, "status_probe_cache_ttl_seconds", 60.0)

    await probe_literature_stack_cached()
    clear_probe_cache()
    await probe_literature_stack_cached()

    assert len(calls) == 2


# --- engine-import failure ---------------------------------------------------


async def test_probe_stack_reports_error_when_engine_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unimportable engine yields probe errors, not a definitive down."""
    # Setting the module entry to None makes `from co_scientist.mcp_client
    # import ...` raise ImportError without touching the real installation.
    monkeypatch.setitem(sys.modules, "co_scientist.mcp_client", None)

    mcp, pubmed, web_search = await diagnostics._probe_literature_stack()

    for result in (mcp, pubmed, web_search):
        assert result.available is False
        assert result.state == PROBE_ERROR
        assert result.error is not None
        assert "engine unavailable" in result.error

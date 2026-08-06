"""Shared pytest fixtures."""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest

from app.config import PROVIDER_CREDENTIAL_ENV

# Provider credentials LiteLLM/the engine may read from the environment. The
# suite must be hermetic: a dev machine's real keys must never leak in and let
# an offline-intended run make a paid call, so every fixture deletes all of
# them before a test runs. Derived from the app's own map rather than listed
# again here, so a credential the app learns to honour is a credential the
# scrub removes -- a hand-kept copy already lagged GOOGLE_API_KEY.
_PROVIDER_KEYS = tuple(
    name for names in PROVIDER_CREDENTIAL_ENV.values() for name in names
)


@pytest.fixture(scope="session", autouse=True)
def _offline_router() -> None:
    """Install the deterministic offline LLM router once for the whole suite.

    Every workflow-driving test runs the real engine graph pinned to the
    ``offline/`` model backend (the mock provider has been retired), so the
    router must intercept ``litellm.acompletion`` for the entire session. It is
    idempotent and a harmless passthrough for any non-offline model.
    """
    from co_scientist.offline_llm import install_offline_router

    install_offline_router()


def _apply_offline_env(
    monkeypatch: pytest.MonkeyPatch, db_path: str, reports_dir: str
) -> None:
    """Bind the store to a per-test db and force the hermetic offline path."""
    monkeypatch.setenv("COSCIENTIST_DB_PATH", db_path)
    monkeypatch.setenv("COSCIENTIST_REPORTS_DIR", reports_dir)
    # app.cli.main runs in-process for the CLI suites (app.cli.main.main
    # called directly, not spawned), so its default-identity file would
    # otherwise land under this machine's real home directory every time a
    # test invokes a command with no --client-id. Same tmp_path/db_path
    # pairing the store gets, so it is wiped with everything else.
    monkeypatch.setenv("COSCIENTIST_CLI_CONFIG_DIR", db_path + "-cli-config")
    # Hermetic + offline: strip any real provider credentials and force the
    # deterministic offline backend so tests never make a paid call and every
    # run is reproducible.
    for key in _PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    # Hard kill switch for the literature-review node: never probe the (possibly
    # live) local MCP server. Without it every workflow-driving test pays the
    # per-run MCP-probe cost that dominates an engine run's wall time.
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "0")
    # Offline tests prove deterministic behavior without spending provider
    # calls; production real-engine runs use the semantic default.
    from app.config import settings

    monkeypatch.setattr(settings, "claim_assessor", "deterministic")
    # Same reasoning for evidence availability: offline tests never leave
    # the process to dereference a DOI/PMID.
    monkeypatch.setattr(settings, "evidence_resolver", "offline")


@pytest.fixture(autouse=True)
def isolated_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> Iterator[str]:
    """Point the SQLite store at a per-test database and force offline mode."""
    db_path = str(tmp_path / "test.db")
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    _apply_offline_env(monkeypatch, db_path, reports_dir)
    # The app-level contextual safety screen is not disabled here: offline-
    # backed runs already skip escalation (safety.screen_with_escalation keys
    # on the run's offline backend), so no offline run makes a real safety call,
    # and the dedicated safety tests keep the default (enabled) screen.
    # Wipe any cached default-path init flags from previous tests.
    from app.store import (
        db as _store_db,
    )

    _store_db._initialized.discard(db_path)
    yield db_path
    # Stop any persistent log capture while this test's env is still bound:
    # importing app.main installs capture at import time, and leaving it
    # running would spill stray records into later tests' databases (or
    # drain into the wrong one). Runs before monkeypatch undoes the env, so
    # queued records land in THIS test's db. TestClient lifespans reinstall.
    from app.logging_setup import shutdown_log_capture

    shutdown_log_capture()


@pytest.fixture
def reachable_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lift the suite's forced-offline posture for one test.

    The suite runs hermetically offline, and ``offline_guard`` refuses an
    outbound chat completion in that posture, so a test that asserts on the
    *shape* of a request the app would send has to say that a provider is
    reachable -- otherwise it is asserting on a request the app is not
    supposed to make at all, which is the defect the guard exists to close.

    Faking litellm alone is not enough and should not be: the guard runs
    before the request is built, exactly so a fake transport cannot stand in
    for a reachable provider. The key here is a placeholder; every one of
    these tests replaces the transport, so it is never used to authenticate
    anything.
    """
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-placeholder-for-shape-tests")


@pytest.fixture(autouse=True)
def _fresh_probe_cache() -> None:
    """Start every test with an empty /status probe cache.

    ``clear_probe_cache`` only drops a module-level memo of the last
    MCP/PubMed/web-search probe triple -- it makes no call and installs no
    state -- so clearing it suite-wide can only remove what an earlier test
    left behind, never couple one test to another.
    """
    from app.diagnostics import clear_probe_cache

    clear_probe_cache()


@pytest.fixture(autouse=True)
def _fresh_health_check_cache() -> None:
    """Start every test with an empty ``/health`` queue/disk check cache.

    Same reasoning as ``_fresh_probe_cache``: the cache is a module-level
    memo keyed on wall-clock time, and each test gets its own isolated
    database, so a cached "healthy" from one test's db would otherwise
    leak into the next test's assertions within the TTL window.
    """
    from app.diagnostics import clear_health_check_cache

    clear_health_check_cache()

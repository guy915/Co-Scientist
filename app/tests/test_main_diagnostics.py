"""Tests for the diagnostics endpoints and lifespan startup/shutdown wiring.

``/health`` and the mock-mode branch of ``/status`` are already covered by
``test_health.py``; this file adds the untested ``/`` and ``/config``
endpoints, the full ASGI lifespan (startup reconciliation + demo seeding,
then shutdown checkpoint) via ``TestClient`` used as a context manager, and
the module-level settings-to-environment bridging that runs once per import.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import pathlib
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import store
from app.run_modes import DEFAULT_RUN_TIER, RUN_TIER_DEFAULTS
from app.store import DEMO_CLIENT_ID
from app.version import API_VERSION
from tests._client import make_client as _client

# The engine's example config: a real, readable YAML for the tools_config
# startup path (validation must pass for it and reject a nonexistent path).
_INDRA_CONFIG = str(
    pathlib.Path(__file__).resolve().parents[2]
    / "engine"
    / "src"
    / "co_scientist"
    / "config"
    / "examples"
    / "indra_cancer.yaml"
)


def _seed_interrupted_engine_run(isolated_db: str) -> str:
    """Persist a RUNNING engine run with a checkpoint (a crash's leavings)."""
    interrupted = store.create_run(
        "interrupted goal",
        "default",
        "engine",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    store.update_run_status(
        interrupted.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    store.save_checkpoint(
        interrupted.id,
        store.NewCheckpoint(
            stage="engine_task:test",
            schema_version=1,
            last_event_seq=0,
            state={"provider": "engine", "state": {"hypotheses": []}},
        ),
        db_path=isolated_db,
    )
    return interrupted.id


def test_root_endpoint_returns_api_metadata() -> None:
    res = _client().get("/")
    assert res.status_code == 200
    data = res.json()
    assert data == {
        "message": "Co-Scientist API",
        "version": API_VERSION,
        "docs": "/docs",
    }


def test_version_is_single_sourced_across_surfaces() -> None:
    """Root, /health, and the OpenAPI app all report the same version."""
    import app.main as main_module

    client = _client()
    assert main_module.app.version == API_VERSION
    assert client.get("/").json()["version"] == API_VERSION
    assert client.get("/health").json()["version"] == API_VERSION


def test_config_endpoint_returns_standard_tier_defaults() -> None:
    res = _client().get("/config")
    assert res.status_code == 200
    defaults = RUN_TIER_DEFAULTS[DEFAULT_RUN_TIER]
    assert res.json() == {
        "max_iterations": defaults["max_iterations"],
        "initial_hypotheses_count": defaults["initial_hypotheses_count"],
        "evolution_max_count": defaults["evolution_max_count"],
    }


def test_lifespan_reconciles_interrupted_runs_and_seeds_demo_data(
    isolated_db: str,
) -> None:
    """Startup reconciles stuck runs and seeds demo runs; shutdown cleans up.

    Constructing TestClient does not itself run the ASGI lifespan; using it
    as a context manager does, which is what actually exercises startup and
    shutdown. ``tools_config`` is unset by default, so this also covers
    startup's "not set" logging fallback.
    """
    import app.main as main_module

    interrupted = store.create_run(
        "interrupted goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    store.update_run_status(
        interrupted.id, store.RunStatus.RUNNING, db_path=isolated_db
    )

    with TestClient(main_module.app) as client:
        res = client.get("/health")
        assert res.status_code == 200

    reconciled = store.get_run(interrupted.id, db_path=isolated_db)
    assert reconciled is not None
    assert reconciled.status == store.RunStatus.FAILED.value
    assert reconciled.error and "restart" in reconciled.error

    demo_runs = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(demo_runs) == 3


def test_lifespan_logs_configured_tools_config(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured, readable ``tools_config`` starts up cleanly."""
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)

    with TestClient(main_module.app) as client:
        res = client.get("/health")
        assert res.status_code == 200


def test_lifespan_fails_on_unreadable_tools_config(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured but unreadable ``tools_config`` fails startup.

    Guards the historical bug where a bad TOOLS_CONFIG was logged but never
    forwarded, so the run silently fell back to default tools. Every run is
    on the engine now, so the validation runs unconditionally at startup.
    """
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "tools_config", "/no/such/tools.yaml")

    with (
        pytest.raises(RuntimeError, match="tools_config"),
        TestClient(main_module.app),
    ):
        pass


def test_status_reports_effective_tools_config(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/status discloses the configured tools_config and its enabled tools."""
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)

    with TestClient(main_module.app) as client:
        res = client.get("/status")
        assert res.status_code == 200
        body = res.json()
        assert body["tools_config"] == _INDRA_CONFIG
        assert body["tools_config_valid"] is True
        assert "indra_statements" in body["enabled_tools"]


def test_status_reports_whether_email_can_actually_be_sent(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/status gates the completion-email opt-in on a real SMTP transport.

    Without one the send task can only raise and exhaust its retries where
    no scientist can see it, so the UI must not offer the opt-in at all.
    """
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from_email", "")
    with TestClient(main_module.app) as client:
        assert (
            client.get("/status").json()["email_notifications_available"]
            is False
        )

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@example.org")
    with TestClient(main_module.app) as client:
        assert (
            client.get("/status").json()["email_notifications_available"]
            is True
        )


def test_module_import_bridges_settings_and_logs_missing_mcp_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Module-level env bridging (gemini key, MCP URL) runs on (re)import.

    Reloads ``app.main`` twice: once with settings tweaked to hit both
    conditional branches, then again with the original settings restored so
    later tests see a normally-configured module.
    """
    import app.main as main_module
    from app.config import settings

    original_gemini_key = settings.gemini_api_key
    original_mcp_url = settings.mcp_server_url
    # Recorded as absent so the fixture teardown deletes whatever the reload
    # below sets, regardless of the key's value at that point.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    settings.gemini_api_key = "test-gemini-key"
    settings.mcp_server_url = ""
    try:
        with caplog.at_level(logging.INFO, logger="app.main"):
            importlib.reload(main_module)
        assert os.environ["GEMINI_API_KEY"] == "test-gemini-key"
        assert (
            "mcp_server_url not set - literature review will be disabled"
            in caplog.text
        )
    finally:
        settings.gemini_api_key = original_gemini_key
        settings.mcp_server_url = original_mcp_url
        importlib.reload(main_module)


def test_startup_prunes_checkpoints_but_never_vacuums(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Housekeeping reclaims rows; it must never take an exclusive lock.

    VACUUM needs exclusive access, and SQLite makes a writer that is waiting
    for one block every other writer behind it. This process can never grant
    it: the log-capture thread writes a row for every record the app emits,
    so a VACUUM waits for a quiet moment that never arrives -- and while it
    waits, nothing else can write either. Production wedged exactly that way
    from both sides of the lifespan, before and after serving: an idle
    database, no writes for minutes, and every run creation returning 500
    with "database is locked".

    Pruning alone is enough. It reclaims the rows that actually grow without
    bound, commits in small batches, and never blocks a reader. The file
    keeps its high-water mark, which a 5 GB volume holding a 53 MB database
    can well afford. The never-VACUUM half of the invariant now holds
    structurally: the store ships no VACUUM helper at all (the gated
    ``compact_database`` was removed precisely so nothing could reintroduce
    the livelock), so this pins the pruning half.
    """
    import app.main as main_module

    pruned = threading.Event()

    def _prune(*args: object, **kwargs: object) -> int:
        pruned.set()
        return 0

    monkeypatch.setattr(store, "prune_superseded_checkpoints", _prune)

    with TestClient(main_module.app) as client:
        assert client.get("/health").status_code == 200

    assert pruned.is_set(), "startup should still reclaim checkpoint rows"


def test_startup_does_not_block_on_run_recovery(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming interrupted runs must not gate the server accepting traffic.

    Recovery work scales with the run backlog, and it used to run before the
    lifespan yielded -- so a container that booted with an interrupted run
    started executing that run's provider calls while uvicorn had not yet
    bound a port. Production deploys failed their healthcheck that way, and
    each failure killed the container mid-run, leaving another interrupted
    run for the next boot to choke on. Recovery belongs after startup.
    """
    import app.main as main_module
    import app.runs as runs_module

    resumed = threading.Event()

    async def slow_resume(run_ids: list[str]) -> None:
        # Awaits rather than blocking the loop: a real resume is provider
        # I/O, so the loop stays free and only startup's own sequencing can
        # keep the port shut.
        resumed.set()
        await asyncio.sleep(30)

    async def _no_seed(db_path: str | None = None) -> None:
        # Demo seeding drives real offline runs at startup (covered by
        # ``test_lifespan_reconciles_interrupted_runs_and_seeds_demo_data``);
        # stub it here so this test measures only recovery scheduling latency,
        # not seed compute, which would otherwise dominate the startup budget.
        return None

    monkeypatch.setattr(runs_module, "resume_interrupted_runs", slow_resume)
    monkeypatch.setattr(main_module, "seed_demo_runs", _no_seed)
    _seed_interrupted_engine_run(isolated_db)

    started = time.monotonic()
    with TestClient(main_module.app) as client:
        startup_seconds = time.monotonic() - started
        assert client.get("/health").status_code == 200
    # Recovery was scheduled, not skipped.
    assert resumed.is_set()
    assert startup_seconds < 10

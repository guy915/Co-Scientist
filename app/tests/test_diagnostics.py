"""Tests for diagnostics."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import pathlib
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import API_VERSION, diagnostics, store
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
from app.run_modes import DEFAULT_RUN_TIER, RUN_TIER_DEFAULTS
from app.store import DEMO_CLIENT_ID
from tests._client import make_client, make_operator_client
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status

# Unit tests for the diagnostics health checks and availability probes.


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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    status = derive_health_status(
        HealthCheck(ok=True), HealthCheck(ok=False, detail="missing")
    )
    assert status == DEGRADED


def test_derive_health_status_healthy_in_pure_offline_mode() -> None:
    """No key and no engine is the normal offline mock setup, not degraded.

    Keyless is the suite's own posture: ``isolated_db`` scrubs every provider
    credential before each test.
    """
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


def test_diagnostics_probe_imports() -> None:
    """Every probe helper the stack imports exists in the engine.

    The import above is wrapped in a broad except that degrades to the
    ``error`` state, so a name the engine does not export fails all three
    probes at once and looks exactly like an MCP server that is down --
    which is how a misspelled helper survived unnoticed and left /status
    reporting the whole literature stack unavailable on every deployment.
    """
    from co_scientist import mcp_client

    for name in (
        "check_literature_source_available",
        "check_mcp_available",
        "check_web_search_available",
    ):
        assert hasattr(mcp_client, name), name


async def test_web_search_probe_asks_usability_not_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registered search_web whose key is refused must read as down.

    The server registers the tool whenever a provider key was set at
    boot, so presence survives the provider revoking, unpaying or
    exhausting that key -- and a refused search returns an empty result
    set, which is indistinguishable from a quiet week on the web. The
    connector card said "up" throughout.
    """
    from co_scientist import mcp_client

    async def _usable() -> bool:
        return False

    async def _registered(_name: str) -> bool:
        return True

    async def _up() -> bool:
        return True

    monkeypatch.setattr(mcp_client, "check_web_search_available", _usable)
    monkeypatch.setattr(mcp_client, "check_tool_available", _registered)
    monkeypatch.setattr(mcp_client, "check_mcp_available", _up)
    monkeypatch.setattr(mcp_client, "check_literature_source_available", _up)

    _, _, web_search = await diagnostics._probe_literature_stack()

    assert web_search.available is False
    assert web_search.state == PROBE_DOWN


# Backend health + status endpoints.


def test_health_ok() -> None:
    client = _client()
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "model_name" in data
    assert data["version"] == API_VERSION
    assert data["provider"] == "engine"
    assert data["checks"]["store"]["ok"] is True
    # Engine importability is environment-dependent; the check must be
    # present and well-formed either way.
    assert set(data["checks"]) == {"store", "engine", "queue", "disk"}
    # No active runs and plenty of disk in a test sandbox: both new checks
    # pass, so the overall status is unaffected by their addition.
    assert data["checks"]["queue"]["ok"] is True
    assert data["checks"]["disk"]["ok"] is True


def test_health_unhealthy_when_store_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostics,
        "check_store",
        lambda db_path=None: HealthCheck(ok=False, detail="disk on fire"),
    )

    # An operator client: check detail text is operator-only (it can carry
    # exception text or paths), so a non-operator caller sees `ok` but not
    # `detail` -- covered by the hides-check-detail test below.
    res = make_operator_client().get("/health")

    assert res.status_code == 503
    data = res.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["store"]["ok"] is False
    assert data["checks"]["store"]["detail"] == "disk on fire"


def test_health_hides_check_detail_and_model_from_non_operators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-operator caller sees `ok` but never `detail` or `model_name`."""
    monkeypatch.setattr(
        diagnostics,
        "check_store",
        lambda db_path=None: HealthCheck(ok=False, detail="disk on fire"),
    )

    data = _client().get("/health").json()

    assert data["checks"]["store"]["ok"] is False
    assert data["checks"]["store"]["detail"] is None
    assert data["model_name"] is None


def test_health_degraded_when_key_set_but_engine_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider key present + engine unimportable = degraded, still 200."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        diagnostics,
        "check_engine",
        lambda: HealthCheck(ok=False, detail="not importable"),
    )

    res = _client().get("/health")

    assert res.status_code == 200
    assert res.json()["status"] == "degraded"


def _patch_probes(
    monkeypatch: pytest.MonkeyPatch,
    mcp: ProbeResult,
    pubmed: ProbeResult,
    web_search: ProbeResult | None = None,
) -> None:
    """Patch the uncached probe triple; the autouse fixture cleared cache."""
    resolved_web = web_search or ProbeResult(available=False, state="down")

    async def _stub() -> tuple[ProbeResult, ProbeResult, ProbeResult]:
        return mcp, pubmed, resolved_web

    monkeypatch.setattr(diagnostics, "_probe_literature_stack", _stub)


def test_status_reports_offline_backend() -> None:
    client = _client()
    res = client.get("/status")
    assert res.status_code == 200
    data = res.json()
    # Every run is the engine provider now; the keyless test process runs
    # the deterministic offline backend. `provider`/`llm_backend` are public
    # (the offline-mode banner reads them); `probes` is operator-only, so
    # it is checked via an operator client below instead.
    assert data["provider"] == "engine"
    assert data["llm_backend"] == "offline"
    assert data["probes"] is None


def test_status_reports_offline_backend_probes_to_operators() -> None:
    data = make_operator_client().get("/status").json()
    assert set(data["probes"]) == {"mcp", "pubmed", "web_search"}


def test_status_requires_both_probes_for_literature_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP up with PubMed down must not report literature review available.

    `probes` detail is operator-only, so this reads it through an operator
    client; `mcp_available`/`pubmed_available`/`literature_review_available`
    stay public and are covered without one elsewhere in this file.
    """
    _patch_probes(
        monkeypatch,
        ProbeResult(available=True, state="up"),
        ProbeResult(available=False, state="down"),
    )

    data = make_operator_client().get("/status").json()

    assert data["mcp_available"] is True
    assert data["pubmed_available"] is False
    assert data["literature_review_available"] is False
    assert data["probes"]["mcp"] == {"state": "up", "error": None}
    assert data["probes"]["pubmed"] == {"state": "down", "error": None}


def test_status_reports_literature_review_when_both_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_probes(
        monkeypatch,
        ProbeResult(available=True, state="up"),
        ProbeResult(available=True, state="up"),
    )

    data = _client().get("/status").json()

    assert data["literature_review_available"] is True


def test_status_distinguishes_probe_error_from_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_probes(
        monkeypatch,
        ProbeResult(
            available=False, state="error", error="probe timed out after 3s"
        ),
        ProbeResult(available=False, state="down"),
    )

    data = make_operator_client().get("/status").json()

    assert data["mcp_available"] is False
    assert data["probes"]["mcp"]["state"] == "error"
    assert data["probes"]["mcp"]["error"] == "probe timed out after 3s"
    assert data["probes"]["pubmed"]["state"] == "down"
    assert data["probes"]["pubmed"]["error"] is None


def test_status_supervisor_model_falls_back_to_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With SUPERVISOR_MODEL_NAME unset, /status mirrors the engine fallback.

    ``supervisor_model_name`` is operator-only (unlike ``model_name``, it is
    not read by any frontend surface), so this reads it through an operator
    client.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "model_name", "worker/model")
    monkeypatch.setattr(settings, "supervisor_model_name", None)
    data = make_operator_client().get("/status").json()
    assert data["supervisor_model_name"] == "worker/model"


def test_status_reports_configured_supervisor_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured supervisor model is surfaced distinctly from the worker."""
    from app.config import settings

    monkeypatch.setattr(settings, "model_name", "worker/model")
    monkeypatch.setattr(settings, "supervisor_model_name", "strategic/model")
    data = make_operator_client().get("/status").json()
    assert data["supervisor_model_name"] == "strategic/model"
    assert data["model_name"] == "worker/model"


def test_status_reports_web_search_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server advertising the web search tool surfaces the connector."""
    _patch_probes(
        monkeypatch,
        ProbeResult(available=True, state="up"),
        ProbeResult(available=True, state="up"),
        ProbeResult(available=True, state="up"),
    )

    data = make_operator_client().get("/status").json()

    assert data["web_search_available"] is True
    assert data["probes"]["web_search"]["state"] == "up"
    assert any(item["id"] == "web_search" for item in data["connectors"])


def test_status_omits_web_search_connector_when_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No provider key on the MCP server means no web search connector."""
    _patch_probes(
        monkeypatch,
        ProbeResult(available=True, state="up"),
        ProbeResult(available=True, state="up"),
        ProbeResult(available=False, state="down"),
    )

    data = _client().get("/status").json()

    assert data["web_search_available"] is False
    assert all(item["id"] != "web_search" for item in data["connectors"])


# Tests for the diagnostics endpoints and lifespan startup/shutdown wiring.
#
# ``/health`` and the mock-mode branch of ``/status`` are already covered by
# ``test_health.py``; this file adds the untested ``/`` and ``/config``
# endpoints, the full ASGI lifespan (startup reconciliation + demo seeding,
# then shutdown checkpoint) via ``TestClient`` used as a context manager, and
# the module-level settings-to-environment bridging that runs once per import.


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


def test_root_endpoint_hides_docs_pointer_from_non_operators() -> None:
    """A non-operator caller gets no /docs pointer -- see `is_operator`."""
    res = _client().get("/")
    assert res.status_code == 200
    assert res.json() == {
        "message": "Co-Scientist API",
        "version": API_VERSION,
        "docs": None,
    }


def test_root_endpoint_shows_docs_pointer_to_operators() -> None:
    res = make_operator_client().get("/")
    assert res.status_code == 200
    assert res.json()["docs"] == "/docs"


def test_docs_and_openapi_are_404_for_non_operators() -> None:
    """Swagger, ReDoc, and the raw schema are hidden from an anonymous caller.

    A 404 rather than a 401/403, so a probing caller cannot distinguish
    "no docs route" from "docs exist but you may not see them".
    """
    client = _client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_docs_and_openapi_serve_for_operators() -> None:
    client = make_operator_client()
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "Co-Scientist API"


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
    """/status discloses the configured tools_config to an operator caller.

    See `is_operator`; every other caller sees this and the other
    operator-only fields redacted to null, covered by
    `test_status_redacts_operator_fields_from_non_operators` below.
    """
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)

    # A loopback client host, matching tests/_client.py's operator client:
    # these fields are operator-only, so a default TestClient (host
    # "testclient", not loopback) would see them redacted.
    with TestClient(main_module.app, client=("127.0.0.1", 50000)) as client:
        res = client.get("/status")
        assert res.status_code == 200
        body = res.json()
        assert body["tools_config"] == _INDRA_CONFIG
        assert body["tools_config_valid"] is True
        assert "indra_statements" in body["enabled_tools"]


def test_status_redacts_operator_fields_from_non_operators(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-operator /status caller sees no deployment internals.

    The internal MCP hostname, provider-key/BYOK/engine-importability
    state, and the tools config are operator diagnostics with no product
    use (nothing in the frontend reads them) -- so they come back null
    rather than real values, while the fields the UI does read (the
    availability booleans, `connectors`, and the offline-mode banner's
    `provider`/`llm_backend`/`model_name`) stay populated.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)

    body = _client().get("/status").json()

    assert body["mcp_server_url"] is None
    assert body["has_provider_key"] is None
    assert body["byok_enabled"] is None
    assert body["engine_importable"] is None
    assert body["supervisor_model_name"] is None
    assert body["tools_config"] is None
    assert body["tools_config_valid"] is None
    assert body["enabled_tools"] is None
    assert body["probes"] is None
    # Publicly-used fields survive redaction.
    assert isinstance(body["connectors"], list)
    assert body["provider"] == "engine"
    assert "llm_backend" in body
    assert "model_name" in body


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


# System tests driving only the public HTTP surface, with a real lifespan.
#
# Unlike the rest of the suite (which mostly uses ``tests._client.make_client``
# without entering the client as a context manager, so the ASGI lifespan never
# runs), these use ``TestClient`` as a context manager so startup
# (interrupted-run reconciliation, demo seeding) and shutdown (WAL checkpoint)
# actually execute, matching how the real server boots. Nothing here imports
# ``app.store`` or any other internal module -- every assertion is made against
# HTTP responses only, since the point is to verify the externally-visible
# contract, not implementation details already covered elsewhere.


def _sse_event_types(text: str) -> list[str]:
    """Return the ``type`` of every SSE ``data:`` frame, in order."""
    types: list[str] = []
    for line in text.splitlines():
        if line.startswith("data: "):
            types.append(json.loads(line[len("data: ") :])["type"])
    return types


def _assert_diagnostics(client: TestClient) -> None:
    """Assert /health, /config, and /status report a healthy offline stack."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"

    config = client.get("/config")
    assert config.status_code == 200
    config_body = config.json()
    assert config_body["initial_hypotheses_count"] > 0
    assert config_body["max_iterations"] > 0
    assert config_body["evolution_max_count"] > 0

    status = client.get("/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["provider"] == "engine"
    assert status_body["llm_backend"] == "offline"


def _create_and_complete(client: TestClient, goal: str) -> str:
    """Create + start an express run, returning its id once completed."""
    create = client.post(
        "/api/runs", json={"research_goal": goal, "tier": "express"}
    )
    assert create.status_code == 200
    run_id: str = create.json()["id"]
    assert create.json()["status"] == "draft"
    start = client.post(f"/api/runs/{run_id}/start", json={})
    assert start.status_code == 200
    assert _wait_status(client, run_id, "completed", timeout=30.0)
    return run_id


def _create_and_block(client: TestClient, goal: str) -> str:
    """Create + start a run expected to reach the blocked terminal state."""
    create = client.post(
        "/api/runs", json={"research_goal": goal, "tier": "express"}
    )
    assert create.status_code == 200
    run_id: str = create.json()["id"]
    start = client.post(f"/api/runs/{run_id}/start", json={})
    assert start.status_code == 200
    assert _wait_status(client, run_id, "blocked", timeout=10.0)
    return run_id


def _assert_terminal_events(client: TestClient, run_id: str) -> None:
    """The event stream carries both the report and the terminal marker."""
    events = client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    event_types = _sse_event_types(events.text)
    assert "_terminal" in event_types
    assert "report" in event_types


def _assert_hypotheses_with_lineage(client: TestClient, run_id: str) -> None:
    """Hypotheses carry positive Elo and at least one evolved child."""
    hyps_resp = client.get(f"/api/runs/{run_id}/hypotheses")
    assert hyps_resp.status_code == 200
    hyps = hyps_resp.json()["hypotheses"]
    assert len(hyps) >= 2
    assert all("elo_rating" in h and h["elo_rating"] > 0 for h in hyps)
    assert any(h["parent_id"] for h in hyps), (
        "no evolved lineage in hypotheses response"
    )


def _assert_citations_wellformed(client: TestClient, run_id: str) -> None:
    """Literature review is off, so the citation list is empty but valid."""
    citations_resp = client.get(f"/api/runs/{run_id}/citations")
    assert citations_resp.status_code == 200
    citations = citations_resp.json()["citations"]
    assert {c["state"] for c in citations} <= {
        "verified",
        "partial",
        "unsupported",
        "unavailable",
    }


def _assert_safety_allowed(client: TestClient, run_id: str) -> None:
    """The intake and final gates both allowed this benign goal."""
    safety_resp = client.get(f"/api/runs/{run_id}/safety")
    assert safety_resp.status_code == 200
    safety = safety_resp.json()["safety"]
    decisions_by_stage = {s["stage"]: s["decision"] for s in safety}
    # The engine may also record per-hypothesis claim-gate decisions between.
    assert decisions_by_stage["intake"] == "allow"
    assert decisions_by_stage["final"] == "allow"


def _assert_report_consistent(client: TestClient, run_id: str) -> None:
    """The JSON report and report.md agree on goal and leaderboard."""
    report_resp = client.get(f"/api/runs/{run_id}/report")
    assert report_resp.status_code == 200
    payload = report_resp.json()["payload"]
    assert payload["research_goal"].startswith("System journey")
    assert payload["leaderboard"]

    md_resp = client.get(f"/api/runs/{run_id}/report.md")
    assert md_resp.status_code == 200
    assert md_resp.text
    assert payload["research_goal"] in md_resp.text
    assert payload["leaderboard"][0]["title"] in md_resp.text


def _assert_run_listed(client: TestClient, run_id: str, status: str) -> None:
    """The run appears in the listing with the expected status."""
    listing = client.get("/api/runs")
    assert listing.status_code == 200
    listed_status_by_id = {r["id"]: r["status"] for r in listing.json()["runs"]}
    assert listed_status_by_id.get(run_id) == status


def test_full_user_journey_from_diagnostics_to_completed_report(
    isolated_db: str,
) -> None:
    """A user checks diagnostics, runs a goal, and reads the finished report.

    Covers, in one journey: /health, /config, /status, create -> start ->
    poll/stream to completion, hypotheses with Elo + lineage, citations,
    safety verdicts, report JSON + report.md consistency, and the run
    showing up in the run list.
    """
    with make_client() as client:
        _assert_diagnostics(client)
        run_id = _create_and_complete(
            client,
            "System journey: chart senescent cell clearance pathways",
        )
        _assert_terminal_events(client, run_id)
        _assert_hypotheses_with_lineage(client, run_id)
        _assert_citations_wellformed(client, run_id)
        _assert_safety_allowed(client, run_id)
        _assert_report_consistent(client, run_id)
        _assert_run_listed(client, run_id, "completed")


def test_safety_blocked_goal_surfaces_through_the_api(
    isolated_db: str,
) -> None:
    """An intake-blocked goal never produces hypotheses or a report.

    The blocked terminal state must surface consistently across the run
    row, the safety endpoint, the (still-empty) hypotheses list, the
    now-missing report endpoints, and the run listing.
    """
    with make_client() as client:
        run_id = _create_and_block(
            client,
            "Engineer smallpox virus to enhance human-to-human "
            "transmission and lethality",
        )

        run_resp = client.get(f"/api/runs/{run_id}")
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["status"] == "blocked"
        assert run_data.get("error")

        safety_resp = client.get(f"/api/runs/{run_id}/safety")
        assert safety_resp.status_code == 200
        safety = safety_resp.json()["safety"]
        assert any(
            s["stage"] == "intake" and s["decision"] == "block" for s in safety
        )

        hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
        assert hyps == []

        assert client.get(f"/api/runs/{run_id}/report").status_code == 404
        assert client.get(f"/api/runs/{run_id}/report.md").status_code == 404

        _assert_run_listed(client, run_id, "blocked")

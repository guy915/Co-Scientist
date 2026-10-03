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


def test_check_store_ok_against_isolated_db(isolated_db: str) -> None:
    result = check_store(isolated_db)
    assert result.ok is True
    assert result.detail is None


def test_check_store_reports_failure_detail(tmp_path: object) -> None:
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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    status = derive_health_status(
        HealthCheck(ok=True), HealthCheck(ok=False, detail="missing")
    )
    assert status == DEGRADED


def test_derive_health_status_healthy_in_pure_offline_mode() -> None:
    status = derive_health_status(
        HealthCheck(ok=True), HealthCheck(ok=False, detail="missing")
    )
    assert status == HEALTHY


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


def _stub_probe_pair(
    calls: list[int],
) -> object:

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


async def test_probe_stack_reports_error_when_engine_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "co_scientist.mcp_client", None)

    mcp, pubmed, web_search = await diagnostics._probe_literature_stack()

    for result in (mcp, pubmed, web_search):
        assert result.available is False
        assert result.state == PROBE_ERROR
        assert result.error is not None
        assert "engine unavailable" in result.error


def test_diagnostics_probe_imports() -> None:
    # Broad import fallback masks missing engine probe names as server outages;
    # check exports explicitly.
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
    # Search tools stay registered after keys are revoked or exhausted; presence
    # is not live availability.
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
    assert set(data["checks"]) == {"store", "engine", "queue", "disk"}
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

    res = make_operator_client().get("/health")

    assert res.status_code == 503
    data = res.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["store"]["ok"] is False
    assert data["checks"]["store"]["detail"] == "disk on fire"


def test_health_hides_check_detail_and_model_from_non_operators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    resolved_web = web_search or ProbeResult(available=False, state="down")

    async def _stub() -> tuple[ProbeResult, ProbeResult, ProbeResult]:
        return mcp, pubmed, resolved_web

    monkeypatch.setattr(diagnostics, "_probe_literature_stack", _stub)


def test_status_reports_offline_backend() -> None:
    client = _client()
    res = client.get("/status")
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "engine"
    assert data["llm_backend"] == "offline"
    assert data["probes"] is None


def test_status_reports_offline_backend_probes_to_operators() -> None:
    data = make_operator_client().get("/status").json()
    assert set(data["probes"]) == {"mcp", "pubmed", "web_search"}


def test_status_requires_both_probes_for_literature_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    from app.config import settings

    monkeypatch.setattr(settings, "model_name", "worker/model")
    monkeypatch.setattr(settings, "supervisor_model_name", None)
    data = make_operator_client().get("/status").json()
    assert data["supervisor_model_name"] == "worker/model"


def test_status_reports_configured_supervisor_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "model_name", "worker/model")
    monkeypatch.setattr(settings, "supervisor_model_name", "strategic/model")
    data = make_operator_client().get("/status").json()
    assert data["supervisor_model_name"] == "strategic/model"
    assert data["model_name"] == "worker/model"


def test_status_reports_web_search_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    _patch_probes(
        monkeypatch,
        ProbeResult(available=True, state="up"),
        ProbeResult(available=True, state="up"),
        ProbeResult(available=False, state="down"),
    )

    data = _client().get("/status").json()

    assert data["web_search_available"] is False
    assert all(item["id"] != "web_search" for item in data["connectors"])


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
    # Return 404 for private API docs so anonymous probes cannot distinguish
    # hidden routes from absent ones.
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
    # TestClient only enters lifespan as a context manager; construction alone
    # does not exercise startup.
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
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)

    with TestClient(main_module.app) as client:
        res = client.get("/health")
        assert res.status_code == 200


def test_lifespan_fails_on_unreadable_tools_config(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bad tool configuration must fail startup rather than silently selecting
    # different tools.
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
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)

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
    # MCP hostnames and credential state are operator internals; public
    # availability remains usable.
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
    assert isinstance(body["connectors"], list)
    assert body["provider"] == "engine"
    assert "llm_backend" in body
    assert "model_name" in body


def test_status_reports_whether_email_can_actually_be_sent(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without SMTP, opt-in only creates invisible retry-exhausted notification
    # tasks.
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
    import app.main as main_module
    from app.config import settings

    original_gemini_key = settings.gemini_api_key
    original_mcp_url = settings.mcp_server_url
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
    # VACUUM waits for exclusive access while log writes continue; pruning must
    # never block serving writers.
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
    # Run recovery after binding traffic; provider work before lifespan yield
    # causes healthcheck restart spirals.
    import app.main as main_module
    import app.runs as runs_module

    resumed = threading.Event()

    async def slow_resume(run_ids: list[str]) -> None:
        resumed.set()
        await asyncio.sleep(30)

    async def _no_seed(db_path: str | None = None) -> None:
        # Stub demo compute so the timing assertion measures recovery scheduling
        # rather than seed work.
        return None

    monkeypatch.setattr(runs_module, "resume_interrupted_runs", slow_resume)
    monkeypatch.setattr(main_module, "seed_demo_runs", _no_seed)
    _seed_interrupted_engine_run(isolated_db)

    started = time.monotonic()
    with TestClient(main_module.app) as client:
        startup_seconds = time.monotonic() - started
        assert client.get("/health").status_code == 200
    assert resumed.is_set()
    assert startup_seconds < 10


def _sse_event_types(text: str) -> list[str]:
    types: list[str] = []
    for line in text.splitlines():
        if line.startswith("data: "):
            types.append(json.loads(line[len("data: ") :])["type"])
    return types


def _assert_diagnostics(client: TestClient) -> None:
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
    events = client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    event_types = _sse_event_types(events.text)
    assert "_terminal" in event_types
    assert "report" in event_types


def _assert_hypotheses_with_lineage(client: TestClient, run_id: str) -> None:
    hyps_resp = client.get(f"/api/runs/{run_id}/hypotheses")
    assert hyps_resp.status_code == 200
    hyps = hyps_resp.json()["hypotheses"]
    assert len(hyps) >= 2
    assert all("elo_rating" in h and h["elo_rating"] > 0 for h in hyps)
    assert any(h["parent_id"] for h in hyps), (
        "no evolved lineage in hypotheses response"
    )


def _assert_citations_wellformed(client: TestClient, run_id: str) -> None:
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
    safety_resp = client.get(f"/api/runs/{run_id}/safety")
    assert safety_resp.status_code == 200
    safety = safety_resp.json()["safety"]
    decisions_by_stage = {s["stage"]: s["decision"] for s in safety}
    assert decisions_by_stage["intake"] == "allow"
    assert decisions_by_stage["final"] == "allow"


def _assert_report_consistent(client: TestClient, run_id: str) -> None:
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
    listing = client.get("/api/runs")
    assert listing.status_code == 200
    listed_status_by_id = {r["id"]: r["status"] for r in listing.json()["runs"]}
    assert listed_status_by_id.get(run_id) == status


def test_full_user_journey_from_diagnostics_to_completed_report(
    isolated_db: str,
) -> None:
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

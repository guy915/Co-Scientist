"""Backend health + status endpoints."""

from __future__ import annotations

import pytest

from app import diagnostics
from app.diagnostics import HealthCheck, ProbeResult
from app.version import API_VERSION
from tests._client import make_client as _client


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

    res = _client().get("/health")

    assert res.status_code == 503
    data = res.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["store"]["ok"] is False
    assert data["checks"]["store"]["detail"] == "disk on fire"


def test_health_degraded_when_key_set_but_engine_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider key present + engine unimportable = degraded, still 200."""
    monkeypatch.setattr(diagnostics, "_has_provider_key", lambda: True)
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
    # the deterministic offline backend.
    assert data["provider"] == "engine"
    assert data["llm_backend"] == "offline"
    assert set(data["probes"]) == {"mcp", "pubmed", "web_search"}


def test_status_requires_both_probes_for_literature_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP up with PubMed down must not report literature review available."""
    _patch_probes(
        monkeypatch,
        ProbeResult(available=True, state="up"),
        ProbeResult(available=False, state="down"),
    )

    data = _client().get("/status").json()

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

    data = _client().get("/status").json()

    assert data["mcp_available"] is False
    assert data["probes"]["mcp"]["state"] == "error"
    assert data["probes"]["mcp"]["error"] == "probe timed out after 3s"
    assert data["probes"]["pubmed"]["state"] == "down"
    assert data["probes"]["pubmed"]["error"] is None


def test_status_supervisor_model_falls_back_to_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With SUPERVISOR_MODEL_NAME unset, /status mirrors the engine fallback."""
    from app.config import settings

    monkeypatch.setattr(settings, "model_name", "worker/model")
    monkeypatch.setattr(settings, "supervisor_model_name", None)
    data = _client().get("/status").json()
    assert data["supervisor_model_name"] == "worker/model"


def test_status_reports_configured_supervisor_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured supervisor model is surfaced distinctly from the worker."""
    from app.config import settings

    monkeypatch.setattr(settings, "model_name", "worker/model")
    monkeypatch.setattr(settings, "supervisor_model_name", "strategic/model")
    data = _client().get("/status").json()
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

    data = _client().get("/status").json()

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

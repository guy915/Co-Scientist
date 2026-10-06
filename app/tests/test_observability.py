from __future__ import annotations

import io
import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist import models
from fastapi.testclient import TestClient

from app.credentials import ByokCredential, scoped_byok
from app.logging_setup import (
    RunIdFilter,
    configure_logging,
    run_log_context,
)
from app.store import logs
from app.store.logs import LogFilters
from tests._client import append_log_row, make_client, make_operator_client
from tests._client import create_run as _create_run
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status


def _record(message: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def _restore_default_logging() -> None:
    from app.config import settings

    configure_logging(settings.log_format)


def test_configured_handler_emits_run_tagged_json_lines() -> None:
    try:
        handler = configure_logging("json")
        stream = io.StringIO()
        handler.stream = stream  # type: ignore[attr-defined]

        with run_log_context("run-e2e"):
            logging.getLogger("app.sample").info("inside run scope")

        lines = [
            json.loads(line)
            for line in stream.getvalue().splitlines()
            if line.strip()
        ]
        tagged = [ln for ln in lines if ln.get("run_id") == "run-e2e"]
        assert tagged and tagged[0]["message"] == "inside run scope"
    finally:
        _restore_default_logging()


def test_json_handler_redacts_a_byok_key_from_exception_text() -> None:
    key = "sk-synthetic-json-log-key-12345"
    diagnostic = "provider diagnostic preserved"
    credential = ByokCredential(
        provider="deepseek", api_key=key, model="deepseek/test"
    )
    try:
        handler = configure_logging("json")
        stream = io.StringIO()
        handler.stream = stream  # type: ignore[attr-defined]

        with scoped_byok(credential):
            try:
                raise RuntimeError(f"provider echoed {key}; {diagnostic}")
            except RuntimeError:
                logging.getLogger("app.sample").exception("provider failed")

        payload = json.loads(stream.getvalue().splitlines()[-1])
    finally:
        _restore_default_logging()

    assert key not in payload["exc_info"]
    assert "[REDACTED]" in payload["exc_info"]
    assert diagnostic in payload["exc_info"]


def test_workflow_records_carry_the_run_id(isolated_db: str) -> None:

    class _Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    capture = _Capture()
    capture.addFilter(RunIdFilter())
    logging.getLogger().addHandler(capture)
    try:
        client = _client()
        created = _create_run(
            client, "Correlate logs with events", tier="express"
        )
        run_id = created.json()["id"]
        started = client.post(f"/api/runs/{run_id}/start", json={})
        assert started.status_code == 200
        assert _wait_status(client, run_id, "completed", timeout=30.0)
    finally:
        logging.getLogger().removeHandler(capture)

    tagged = {getattr(r, "run_id", None) for r in capture.records}
    assert run_id in tagged


def _logs_endpoint_seed(
    isolated_db: str,
    message: str,
    *,
    level: str = "INFO",
    levelno: int = logging.INFO,
    run_id: str | None = None,
) -> int:
    return append_log_row(
        isolated_db, message, level=level, levelno=levelno, run_id=run_id
    )


def _seed_from(
    isolated_db: str,
    logger_name: str,
    message: str,
    *,
    level: str = "INFO",
    levelno: int = logging.INFO,
) -> int:
    return append_log_row(
        isolated_db,
        message,
        logger_name=logger_name,
        level=level,
        levelno=levelno,
    )


def test_logs_endpoint_returns_rows_and_last_id(isolated_db: str) -> None:
    first = _logs_endpoint_seed(isolated_db, "first line")
    last = _logs_endpoint_seed(isolated_db, "second line")
    response = make_operator_client().get("/api/logs")
    assert response.status_code == 200
    body = response.json()
    messages = [row["message"] for row in body["logs"]]
    assert "first line" in messages
    assert "second line" in messages
    assert body["last_id"] >= last
    row = body["logs"][messages.index("first line")]
    assert row["id"] == first
    assert row["level"] == "INFO"
    assert row["logger"] == "app.seeded"

    _logs_endpoint_seed(isolated_db, "new line")
    polled = (
        make_operator_client()
        .get("/api/logs", params={"after_id": body["last_id"]})
        .json()
    )
    assert [row["message"] for row in polled["logs"]] == ["new line"]


def test_logs_endpoint_applies_filters_and_rejects_unknown_levels(
    isolated_db: str,
) -> None:
    _logs_endpoint_seed(isolated_db, "quiet info")
    _logs_endpoint_seed(
        isolated_db, "bad error", level="ERROR", levelno=logging.ERROR
    )
    _logs_endpoint_seed(isolated_db, "scoped info", run_id="run-1")
    client = make_operator_client()

    body = client.get("/api/logs", params={"min_level": "warning"}).json()
    assert [row["message"] for row in body["logs"]] == ["bad error"]

    body = client.get("/api/logs", params={"run_id": "run-1"}).json()
    assert [row["message"] for row in body["logs"]] == ["scoped info"]

    body = client.get("/api/logs", params={"q": "bad"}).json()
    assert [row["message"] for row in body["logs"]] == ["bad error"]

    unknown = client.get("/api/logs", params={"min_level": "LOUDEST"})
    assert unknown.status_code == 422


def test_logs_endpoint_hides_noise_by_default(isolated_db: str) -> None:
    _logs_endpoint_seed(isolated_db, "run started")
    _seed_from(isolated_db, "uvicorn.access", "GET /status 200")
    _seed_from(
        isolated_db,
        "uvicorn.access",
        "request blew up",
        level="ERROR",
        levelno=logging.ERROR,
    )
    _seed_from(
        isolated_db, "co_scientist.mcp_client", "initializing MCP client"
    )
    _seed_from(
        isolated_db,
        "co_scientist.evidence.search",
        "Source pubmed: collected 3 papers",
    )
    _seed_from(
        isolated_db,
        "co_scientist.agents.generation",
        "generation degraded to LLM-only",
        level="WARNING",
        levelno=logging.WARNING,
    )
    client = make_operator_client()

    body = client.get("/api/logs").json()
    assert [row["message"] for row in body["logs"]] == [
        "run started",
        "request blew up",
        "generation degraded to LLM-only",
    ]
    assert body["total"] == 3

    body = client.get("/api/logs", params={"verbose": "1"}).json()
    assert [row["message"] for row in body["logs"]] == [
        "run started",
        "GET /status 200",
        "request blew up",
        "initializing MCP client",
        "Source pubmed: collected 3 papers",
        "generation degraded to LLM-only",
    ]
    assert body["total"] == 6


def test_run_logs_endpoint_scopes_to_run(isolated_db: str) -> None:
    client = make_operator_client()
    created = _create_run(client, "logs endpoint test")
    run_id = created.json()["id"]
    _logs_endpoint_seed(isolated_db, "global line")
    _logs_endpoint_seed(isolated_db, "run line", run_id=run_id)
    body = client.get(f"/api/runs/{run_id}/logs").json()
    assert [row["message"] for row in body["logs"]] == ["run line"]
    assert client.get("/api/runs/nope/logs").status_code == 404


def test_post_logs_ingests_ui_records(isolated_db: str) -> None:
    client = make_operator_client()
    response = client.post(
        "/api/logs",
        json={
            "records": [
                {"message": "clicked start", "logger": "session"},
                {"message": "did it", "level": "success"},
                {
                    "message": "stream dropped",
                    "level": "error",
                    "logger": "ui.stream",
                    "run_id": "run-1",
                },
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["added"] == 3
    rows = client.get("/api/logs").json()["logs"]
    by_message = {row["message"]: row for row in rows}
    assert by_message["clicked start"]["logger"] == "ui.session"
    assert by_message["clicked start"]["level"] == "INFO"
    assert by_message["did it"]["level"] == "INFO"
    assert by_message["stream dropped"]["logger"] == "ui.stream"
    assert by_message["stream dropped"]["level"] == "ERROR"
    assert by_message["stream dropped"]["run_id"] == "run-1"

    too_many = {"records": [{"message": "m"}] * 51}
    assert client.post("/api/logs", json=too_many).status_code == 422
    client.post("/api/logs", json={"records": [{"message": "x" * 5000}]})
    rows = client.get("/api/logs").json()["logs"]
    assert max(len(row["message"]) for row in rows) == 2000


# Shared logs contain other tenants and server internals; remote reads need
# ownership or operator access.


def _security_seed(
    isolated_db: str,
    message: str,
    *,
    run_id: str | None = None,
    client_id: str | None = None,
) -> int:
    return append_log_row(
        isolated_db, message, run_id=run_id, client_id=client_id
    )


# TestClient reports a non-loopback host, exercising remote policy unless an
# operator token is supplied.


def _admin_token(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "logs_admin_token", token)


def test_remote_read_is_scoped_to_the_caller(isolated_db: str) -> None:
    _security_seed(isolated_db, "alice ui record", client_id="alice")
    _security_seed(isolated_db, "bob ui record", client_id="bob")
    _security_seed(isolated_db, "server internals")
    client = make_client()

    body = client.get("/api/logs", headers={"X-Client-ID": "alice"}).json()
    messages = [r["message"] for r in body["logs"]]
    assert messages == ["alice ui record"]
    assert body["total"] == 1


def test_ingested_records_are_stamped_with_the_caller_and_sanitized(
    isolated_db: str,
) -> None:
    client = make_client()
    client.post(
        "/api/logs",
        json={
            "records": [
                {
                    "message": "real\n2026-01-01\tINFO\tapp.fake\tforged",
                    "logger": "sess\nion",
                }
            ]
        },
        headers={"X-Client-ID": "alice"},
    )
    alice = logs.list_logs(
        filters=LogFilters(scope_client_id="alice"), db_path=isolated_db
    )
    assert len(alice) == 1
    assert "\n" not in alice[0]["message"] + alice[0]["logger"]
    assert "\t" not in alice[0]["message"]
    assert (
        logs.list_logs(
            filters=LogFilters(scope_client_id="bob"), db_path=isolated_db
        )
        == []
    )


def test_remote_read_without_identity_sees_nothing(isolated_db: str) -> None:
    _security_seed(isolated_db, "alice ui record", client_id="alice")
    _security_seed(isolated_db, "server internals")
    body = make_client().get("/api/logs").json()
    assert body["logs"] == []


def test_admin_token_grants_the_app_wide_view(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _admin_token(monkeypatch, "s3cret")
    _security_seed(isolated_db, "alice ui record", client_id="alice")
    _security_seed(isolated_db, "server internals")
    client = make_client()

    body = client.get("/api/logs", headers={"X-Logs-Token": "s3cret"}).json()
    assert len(body["logs"]) == 2
    body = client.get("/api/logs", headers={"X-Logs-Token": "nope"}).json()
    assert body["logs"] == []


def test_remote_delete_only_clears_the_callers_records(
    isolated_db: str,
) -> None:
    _security_seed(isolated_db, "alice ui record", client_id="alice")
    _security_seed(isolated_db, "bob ui record", client_id="bob")
    _security_seed(isolated_db, "server internals")
    client = make_client()

    response = client.request(
        "DELETE", "/api/logs", headers={"X-Client-ID": "alice"}
    )
    assert response.json()["deleted"] == 1
    remaining = [r["message"] for r in logs.list_logs(db_path=isolated_db)]
    assert remaining == ["bob ui record", "server internals"]


def test_ingestion_is_rate_limited(isolated_db: str) -> None:
    client = make_client()
    headers = {"X-Client-ID": "flooder"}
    last = None
    for _ in range(200):
        last = client.post(
            "/api/logs",
            json={"records": [{"message": "spam"}]},
            headers=headers,
        )
        if last.status_code == 429:
            break
    assert last is not None and last.status_code == 429


_METRIC_FIELDS = (
    "total_time",
    "hypothesis_count",
    "reviews_count",
    "tournaments_count",
    "evolutions_count",
    "llm_calls",
    "phase_times",
)


def _run_to_completion(client: TestClient, goal: str) -> dict[str, Any]:
    created = _create_run(client, goal, tier="express")
    run_id = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200
    assert _wait_status(client, run_id, "completed", timeout=30.0)

    metrics = client.get(f"/api/runs/{run_id}/metrics").json()["metrics"]
    assert metrics is not None
    return dict(metrics)


def test_completed_run_serves_engine_metrics(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Random hypothesis ids shape the offline prompts, so some runs drew no
    # evolved child; a pinned id sequence makes the run reproducible.
    pinned = models._make_id_factory("metrics-run")
    monkeypatch.setattr(
        models,
        "_ID_FACTORY",
        SimpleNamespace(get=lambda: pinned),
    )
    metrics = _run_to_completion(_client(), "Metrics for a full run")

    for field in _METRIC_FIELDS:
        assert field in metrics
    assert metrics["hypothesis_count"] >= 1
    assert metrics["tournaments_count"] >= 1
    assert metrics["evolutions_count"] > 0
    assert metrics["llm_calls"] > 0
    assert isinstance(metrics["phase_times"], dict)
    assert metrics["total_time"] >= 0.0

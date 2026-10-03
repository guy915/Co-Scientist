"""Tests for observability."""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import store
from app.credentials import ByokCredential, scoped_byok
from app.logging_setup import (
    _LITELLM_LOGGER_NAMES,
    TEXT_FORMAT,
    JsonFormatter,
    RunIdFilter,
    TextRunIdFormatter,
    configure_logging,
    current_run_id,
    run_log_context,
)
from tests._client import append_log_row, make_client, make_operator_client
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status

# Tests for the app logging module: formats, run-id tagging, idempotency.


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
    """Reinstall the app's default handler so later tests see normal logs."""
    from app.config import settings

    configure_logging(settings.log_format)


# --- run-id context ----------------------------------------------------------


def test_run_log_context_binds_and_restores_run_id() -> None:
    assert current_run_id() is None
    with run_log_context("run-123"):
        assert current_run_id() == "run-123"
    assert current_run_id() is None


def test_run_id_filter_stamps_context_run_id_onto_records() -> None:
    record = _record()
    with run_log_context("run-abc"):
        RunIdFilter().filter(record)
    assert record.run_id == "run-abc"  # type: ignore[attr-defined]

    unscoped = _record()
    RunIdFilter().filter(unscoped)
    assert unscoped.run_id is None  # type: ignore[attr-defined]


# --- formatters --------------------------------------------------------------


def test_text_formatter_appends_run_id_suffix_only_when_bound() -> None:
    formatter = TextRunIdFormatter(TEXT_FORMAT)

    tagged = _record()
    tagged.run_id = "run-xyz"
    assert formatter.format(tagged).endswith(" [run_id=run-xyz]")

    plain = _record()
    plain.run_id = None
    assert "run_id" not in formatter.format(plain)


def test_json_formatter_emits_structured_fields() -> None:
    record = _record("structured message")
    record.run_id = "run-json"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "structured message"
    assert payload["run_id"] == "run-json"
    assert "time" in payload


def test_json_formatter_includes_exception_detail() -> None:
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        import sys

        record = _record("failed")
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(record))

    assert "kaboom" in payload["exc_info"]


# --- configure_logging -------------------------------------------------------


def _cosci_handlers() -> list[logging.Handler]:
    return [
        h
        for h in logging.getLogger().handlers
        if getattr(h, "_cosci_handler", False)
    ]


def test_configure_logging_is_idempotent_and_selects_format() -> None:
    try:
        configure_logging("json")
        configure_logging("json")
        handlers = _cosci_handlers()
        assert len(handlers) == 1
        assert isinstance(handlers[0].formatter, JsonFormatter)

        configure_logging("text")
        handlers = _cosci_handlers()
        assert len(handlers) == 1
        assert isinstance(handlers[0].formatter, TextRunIdFormatter)
    finally:
        _restore_default_logging()


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


# --- workflow correlation ----------------------------------------------------


def test_workflow_records_carry_the_run_id(isolated_db: str) -> None:
    """Records logged inside a run's workflow task carry that run's id.

    Uses a list-capturing handler with the RunIdFilter attached (mirroring
    the configured stdout handler) so the assertion sees exactly what the
    formatter would.
    """

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
        created = client.post(
            "/api/runs",
            json={
                "research_goal": "Correlate logs with events",
                "tier": "express",
            },
        )
        run_id = created.json()["id"]
        started = client.post(f"/api/runs/{run_id}/start", json={})
        assert started.status_code == 200
        assert _wait_status(client, run_id, "completed", timeout=30.0)
    finally:
        logging.getLogger().removeHandler(capture)

    tagged = {getattr(r, "run_id", None) for r in capture.records}
    assert run_id in tagged


# --- LiteLLM logging noise ---------------------------------------------------


def test_configure_logging_raises_litellm_loggers_to_warning() -> None:
    """Root's own INFO level must not let LiteLLM's loggers stay chatty.

    LiteLLM attaches its own handler directly to these loggers, bypassing
    root entirely, so this must be a level set on the logger itself
    (perturbed to DEBUG first so the assertion cannot pass on stale
    module-import state).
    """
    for name in _LITELLM_LOGGER_NAMES:
        logging.getLogger(name).setLevel(logging.DEBUG)

    configure_logging()

    for name in _LITELLM_LOGGER_NAMES:
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
    _restore_default_logging()


def test_configure_logging_does_not_touch_warning_and_above() -> None:
    """The fix silences chatter, not genuine trouble reports.

    Matches ``UNPERSISTED_LOGGERS``'s own boundary: WARNING+ must still
    reach a handler, since that is what says a dependency is in trouble.
    """
    configure_logging()
    litellm_logger = logging.getLogger("LiteLLM")

    assert litellm_logger.isEnabledFor(logging.WARNING)
    assert not litellm_logger.isEnabledFor(logging.INFO)
    _restore_default_logging()


def test_configure_logging_suppresses_litellms_debug_print_banner() -> None:
    """The "Provider List" banner is a plain print(), not a log record.

    ``litellm.suppress_debug_info`` is the only switch guarding it
    (litellm's ``get_llm_provider_logic.py``), so the logger-level fix
    above leaves it printing unless this flag is also set.
    """
    import litellm

    litellm.suppress_debug_info = False  # perturb first

    configure_logging()

    assert litellm.suppress_debug_info is True
    _restore_default_logging()


# Tests for the persisted-logs endpoints (/api/logs, /api/runs/{id}/logs).


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


def test_logs_endpoint_applies_filters(isolated_db: str) -> None:
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


def test_logs_endpoint_supports_incremental_polling(
    isolated_db: str,
) -> None:
    _logs_endpoint_seed(isolated_db, "old line")
    client = make_operator_client()
    cursor = client.get("/api/logs").json()["last_id"]
    _logs_endpoint_seed(isolated_db, "new line")
    body = client.get("/api/logs", params={"after_id": cursor}).json()
    assert [row["message"] for row in body["logs"]] == ["new line"]


def test_logs_endpoint_total_counts_beyond_limit(isolated_db: str) -> None:
    for i in range(5):
        _logs_endpoint_seed(isolated_db, f"line {i}")
    body = make_operator_client().get("/api/logs", params={"limit": 2}).json()
    # The window is capped, but `total` reports every matching row so the
    # UI badge can show the true table size.
    assert len(body["logs"]) == 2
    assert body["total"] == 5


def test_logs_endpoint_total_respects_filters_not_cursor(
    isolated_db: str,
) -> None:
    _logs_endpoint_seed(isolated_db, "quiet info")
    cursor = _logs_endpoint_seed(
        isolated_db, "bad error", level="ERROR", levelno=40
    )
    client = make_operator_client()
    body = client.get("/api/logs", params={"min_level": "warning"}).json()
    assert body["total"] == 1
    # `after_id` is a paging cursor; it must not shrink the total.
    body = client.get("/api/logs", params={"after_id": cursor}).json()
    assert body["logs"] == []
    assert body["total"] == 2


def test_logs_endpoint_session_total_follows_the_cursor(
    isolated_db: str,
) -> None:
    _logs_endpoint_seed(isolated_db, "before the cursor")
    cursor = _logs_endpoint_seed(isolated_db, "at the cursor")
    _logs_endpoint_seed(isolated_db, "after the cursor")
    client = make_operator_client()

    # Filtered to the seeded rows: log capture writes the app's own
    # startup records from a background thread, so an unfiltered count
    # here would race it.
    body = client.get(
        "/api/logs", params={"after_id": cursor, "q": "cursor"}
    ).json()
    assert [row["message"] for row in body["logs"]] == ["after the cursor"]
    # Two counts of the same filtered set, differing only in the cursor:
    # `total` is the whole matching set, `session_total` only what this
    # poller's anchor has seen. A UI counting its own slice reads the
    # latter, so rows deleted below the anchor cannot drive it negative.
    assert body["total"] == 3
    assert body["session_total"] == 1

    # Filters narrow both counts; only the cursor separates them.
    body = client.get("/api/logs", params={"q": "at the"}).json()
    assert body["total"] == 1
    assert body["session_total"] == 1


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
    # MCP availability probes repeat on every /status poll: noise too.
    _seed_from(
        isolated_db, "co_scientist.mcp_client", "initializing MCP client"
    )
    # The engine's per-call INFO (hundreds per run) is hidden, but a real
    # engine WARNING still surfaces.
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

    # Default: high-volume chatter (HTTP access, clicks, navigation,
    # dependency loggers, engine per-call INFO) is hidden below WARNING;
    # warnings and errors always show.
    body = client.get("/api/logs").json()
    assert [row["message"] for row in body["logs"]] == [
        "run started",
        "request blew up",
        "generation degraded to LLM-only",
    ]
    assert body["total"] == 3

    # verbose=1 opts back into the full stream.
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


def test_logs_endpoint_rejects_unknown_level(isolated_db: str) -> None:
    response = make_operator_client().get(
        "/api/logs", params={"min_level": "LOUDEST"}
    )
    assert response.status_code == 422


def test_run_logs_endpoint_scopes_to_run(isolated_db: str) -> None:
    client = make_operator_client()
    created = client.post(
        "/api/runs", json={"research_goal": "logs endpoint test"}
    )
    run_id = created.json()["id"]
    _logs_endpoint_seed(isolated_db, "global line")
    _logs_endpoint_seed(isolated_db, "run line", run_id=run_id)
    body = client.get(f"/api/runs/{run_id}/logs").json()
    assert [row["message"] for row in body["logs"]] == ["run line"]


def test_run_logs_endpoint_unknown_run_is_404(isolated_db: str) -> None:
    assert make_operator_client().get("/api/runs/nope/logs").status_code == 404


def test_delete_logs_clears_and_restarts_ids(isolated_db: str) -> None:
    _logs_endpoint_seed(isolated_db, "one")
    _logs_endpoint_seed(isolated_db, "two")
    client = make_operator_client()
    response = client.request("DELETE", "/api/logs")
    assert response.status_code == 200
    assert response.json()["deleted"] == 2
    body = client.get("/api/logs").json()
    assert body["logs"] == []
    assert body["last_id"] == 0
    # Records after a clear restart at id 1: the log reads as brand new.
    assert _logs_endpoint_seed(isolated_db, "fresh") == 1


def test_post_logs_ingests_ui_records(isolated_db: str) -> None:
    client = make_operator_client()
    response = client.post(
        "/api/logs",
        json={
            "records": [
                {"message": "clicked start", "logger": "session"},
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
    assert body["added"] == 2
    rows = client.get("/api/logs").json()["logs"]
    by_message = {row["message"]: row for row in rows}
    # Client records are namespaced under ui.* so their origin is obvious.
    assert by_message["clicked start"]["logger"] == "ui.session"
    assert by_message["clicked start"]["level"] == "INFO"
    assert by_message["stream dropped"]["logger"] == "ui.stream"
    assert by_message["stream dropped"]["level"] == "ERROR"
    assert by_message["stream dropped"]["run_id"] == "run-1"


def test_post_logs_maps_unknown_level_to_info(isolated_db: str) -> None:
    client = make_operator_client()
    client.post(
        "/api/logs",
        json={"records": [{"message": "did it", "level": "success"}]},
    )
    rows = client.get("/api/logs").json()["logs"]
    assert rows[0]["level"] == "INFO"


def test_post_logs_caps_batch_and_truncates_messages(
    isolated_db: str,
) -> None:
    client = make_operator_client()
    too_many = {"records": [{"message": "m"}] * 51}
    assert client.post("/api/logs", json=too_many).status_code == 422

    client.post("/api/logs", json={"records": [{"message": "x" * 5000}]})
    rows = client.get("/api/logs").json()["logs"]
    assert len(rows[0]["message"]) == 2000


# Tests for the persisted-log access controls.
#
# The app-wide log carries other tenants' research goals, run activity, and
# server internals, so a remote caller must only ever see records that are
# theirs. Operators (loopback, or a configured admin token) keep the
# app-wide view the CLI needs.


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


def test_records_are_scoped_to_the_owning_client(isolated_db: str) -> None:
    client = make_client()
    created = client.post(
        "/api/runs",
        json={"research_goal": "alice private goal"},
        headers={"X-Client-ID": "alice"},
    )
    alice_run = created.json()["id"]
    _security_seed(isolated_db, "alice run record", run_id=alice_run)
    _security_seed(isolated_db, "alice ui record", client_id="alice")
    _security_seed(isolated_db, "bob ui record", client_id="bob")
    _security_seed(isolated_db, "server startup record")

    rows = store.list_logs(
        filters=store.LogFilters(scope_client_id="alice"), db_path=isolated_db
    )
    messages = [r["message"] for r in rows]
    # Own run records and own ingested records, nothing else -- not
    # another tenant's, and not un-owned server internals.
    assert "alice run record" in messages
    assert "alice ui record" in messages
    assert "bob ui record" not in messages
    assert "server startup record" not in messages
    # Creating the run also logged alice's own lifecycle stage record,
    # so assert the invariant rather than a fixed number.
    assert store.count_logs(
        filters=store.LogFilters(scope_client_id="alice"), db_path=isolated_db
    ) == len(rows)
    assert all("bob" not in m for m in messages)


def test_unscoped_read_still_sees_everything(isolated_db: str) -> None:
    _security_seed(isolated_db, "alice ui record", client_id="alice")
    _security_seed(isolated_db, "server startup record")
    assert store.count_logs(db_path=isolated_db) == 2


def test_clear_can_be_scoped_to_one_client(isolated_db: str) -> None:
    _security_seed(isolated_db, "alice ui record", client_id="alice")
    _security_seed(isolated_db, "bob ui record", client_id="bob")
    deleted = store.clear_logs(scope_client_id="alice", db_path=isolated_db)
    assert deleted == 1
    remaining = [r["message"] for r in store.list_logs(db_path=isolated_db)]
    assert remaining == ["bob ui record"]


# --------------------------------------------------------------------------
# Endpoint access control. TestClient requests report a non-loopback host,
# so they exercise the remote path unless an admin token is supplied.
# --------------------------------------------------------------------------


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
    # A wrong token must not fall back to the app-wide view.
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
    remaining = [r["message"] for r in store.list_logs(db_path=isolated_db)]
    assert remaining == ["bob ui record", "server internals"]


def test_ingested_records_are_stamped_with_the_caller(
    isolated_db: str,
) -> None:
    client = make_client()
    client.post(
        "/api/logs",
        json={"records": [{"message": "alice clicked"}]},
        headers={"X-Client-ID": "alice"},
    )
    rows = store.list_logs(
        filters=store.LogFilters(scope_client_id="alice"), db_path=isolated_db
    )
    assert [r["message"] for r in rows] == ["alice clicked"]
    # And it is not visible to another tenant.
    assert (
        store.list_logs(
            filters=store.LogFilters(scope_client_id="bob"), db_path=isolated_db
        )
        == []
    )


def test_ingestion_strips_control_characters(isolated_db: str) -> None:
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
    row = store.list_logs(
        filters=store.LogFilters(scope_client_id="alice"), db_path=isolated_db
    )[0]
    # Newlines and tabs would let a submitted message forge extra lines
    # in the CLI's tab-delimited output.
    assert "\n" not in row["message"]
    assert "\t" not in row["message"]
    assert "\n" not in row["logger"]


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


# API tests for the run execution-metrics sub-resource.


_METRIC_FIELDS = (
    "total_time",
    "hypothesis_count",
    "reviews_count",
    "tournaments_count",
    "evolutions_count",
    "llm_calls",
    "phase_times",
)

# The offline backend renders byte-identical content for byte-identical
# prompts, but each run's prompts are shaped by that run's own (genuinely
# random) hypothesis ids, so whether evolution's near-duplicate guard accepts
# or rejects a refinement is a real per-run draw -- on express tier's small
# post-dedup pool, occasionally every attempt is rejected and the run
# completes having evolved nothing. A handful of independent, freshly seeded
# runs (never reusing one) makes that rare draw a non-issue without
# weakening what the final assertions check.
_MAX_RUN_ATTEMPTS = 5


def test_metrics_unknown_run_404s() -> None:
    res = _client().get("/api/runs/does-not-exist/metrics")
    assert res.status_code == 404


def test_metrics_null_before_finalize(isolated_db: str) -> None:
    client = _client()
    created = client.post(
        "/api/runs", json={"research_goal": "Draft metrics goal"}
    )
    run_id = created.json()["id"]

    res = client.get(f"/api/runs/{run_id}/metrics")

    assert res.status_code == 200
    assert res.json() == {"metrics": None}


def _run_to_completion(client: TestClient, goal: str) -> dict[str, Any]:
    """Create, start, and wait out one express-tier run; return its metrics.

    Args:
        client: API client to drive the run through.
        goal: Research goal for this run; callers vary it across attempts so
            each retry is a genuinely distinct run rather than a replay.

    Returns:
        The completed run's execution-metrics payload (never None: the run
        reached "completed", which only happens after finalize persists it).
    """
    created = client.post(
        "/api/runs", json={"research_goal": goal, "tier": "express"}
    )
    run_id = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200
    assert _wait_status(client, run_id, "completed", timeout=30.0)

    metrics = client.get(f"/api/runs/{run_id}/metrics").json()["metrics"]
    assert metrics is not None
    return dict(metrics)


def test_completed_run_serves_engine_metrics(
    isolated_db: str,
) -> None:
    """A completed offline engine run persists real execution metrics.

    The engine records metrics from its own instrumentation (LLM calls, phase
    timings, node counts) rather than a mock formula, so the assertions here
    are on the metrics being present, well-formed, and internally consistent
    with the run having done real work -- not on a reconstructed identity with
    the store's summary counts. Own setup: this test seeds and completes its
    own run(s) here rather than depending on any run created elsewhere in
    this module, so it is reachable by name and order-independent.
    """
    client = _client()
    metrics: dict[str, Any] | None = None
    for attempt in range(_MAX_RUN_ATTEMPTS):
        metrics = _run_to_completion(
            client, f"Metrics for a full run {attempt}"
        )
        if metrics["evolutions_count"] > 0:
            break

    assert metrics is not None
    for field in _METRIC_FIELDS:
        assert field in metrics
    # A real engine run generated hypotheses, ran the tournament, evolved, and
    # made LLM calls; the recorded counts must all reflect that work.
    assert metrics["hypothesis_count"] >= 1
    assert metrics["tournaments_count"] >= 1
    assert metrics["evolutions_count"] > 0
    assert metrics["llm_calls"] > 0
    assert isinstance(metrics["phase_times"], dict)
    assert metrics["total_time"] >= 0.0

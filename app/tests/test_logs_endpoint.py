"""Tests for the persisted-logs endpoints (/api/logs, /api/runs/{id}/logs)."""

from __future__ import annotations

import logging

from tests._client import append_log_row, make_operator_client


def _seed(
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
    first = _seed(isolated_db, "first line")
    last = _seed(isolated_db, "second line")
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
    _seed(isolated_db, "quiet info")
    _seed(isolated_db, "bad error", level="ERROR", levelno=logging.ERROR)
    _seed(isolated_db, "scoped info", run_id="run-1")
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
    _seed(isolated_db, "old line")
    client = make_operator_client()
    cursor = client.get("/api/logs").json()["last_id"]
    _seed(isolated_db, "new line")
    body = client.get("/api/logs", params={"after_id": cursor}).json()
    assert [row["message"] for row in body["logs"]] == ["new line"]


def test_logs_endpoint_total_counts_beyond_limit(isolated_db: str) -> None:
    for i in range(5):
        _seed(isolated_db, f"line {i}")
    body = make_operator_client().get("/api/logs", params={"limit": 2}).json()
    # The window is capped, but `total` reports every matching row so the
    # UI badge can show the true table size.
    assert len(body["logs"]) == 2
    assert body["total"] == 5


def test_logs_endpoint_total_respects_filters_not_cursor(
    isolated_db: str,
) -> None:
    _seed(isolated_db, "quiet info")
    cursor = _seed(isolated_db, "bad error", level="ERROR", levelno=40)
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
    _seed(isolated_db, "before the cursor")
    cursor = _seed(isolated_db, "at the cursor")
    _seed(isolated_db, "after the cursor")
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
    _seed(isolated_db, "run started")
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
    _seed(isolated_db, "global line")
    _seed(isolated_db, "run line", run_id=run_id)
    body = client.get(f"/api/runs/{run_id}/logs").json()
    assert [row["message"] for row in body["logs"]] == ["run line"]


def test_run_logs_endpoint_unknown_run_is_404(isolated_db: str) -> None:
    assert make_operator_client().get("/api/runs/nope/logs").status_code == 404


def test_delete_logs_clears_and_restarts_ids(isolated_db: str) -> None:
    _seed(isolated_db, "one")
    _seed(isolated_db, "two")
    client = make_operator_client()
    response = client.request("DELETE", "/api/logs")
    assert response.status_code == 200
    assert response.json()["deleted"] == 2
    body = client.get("/api/logs").json()
    assert body["logs"] == []
    assert body["last_id"] == 0
    # Records after a clear restart at id 1: the log reads as brand new.
    assert _seed(isolated_db, "fresh") == 1


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

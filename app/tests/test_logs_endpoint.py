"""Tests for the persisted-logs endpoints (/api/logs, /api/runs/{id}/logs)."""

from __future__ import annotations

import logging

from app import store
from tests._client import make_client


def _seed(
    isolated_db: str,
    message: str,
    *,
    level: str = "INFO",
    levelno: int = logging.INFO,
    run_id: str | None = None,
) -> int:
    return store.append_log(
        level=level,
        levelno=levelno,
        logger_name="app.seeded",
        message=message,
        run_id=run_id,
        db_path=isolated_db,
    )


def test_logs_endpoint_returns_rows_and_last_id(isolated_db: str) -> None:
    first = _seed(isolated_db, "first line")
    last = _seed(isolated_db, "second line")
    response = make_client().get("/api/logs")
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
    client = make_client()

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
    client = make_client()
    cursor = client.get("/api/logs").json()["last_id"]
    _seed(isolated_db, "new line")
    body = client.get("/api/logs", params={"after_id": cursor}).json()
    assert [row["message"] for row in body["logs"]] == ["new line"]


def test_logs_endpoint_rejects_unknown_level(isolated_db: str) -> None:
    response = make_client().get("/api/logs", params={"min_level": "LOUDEST"})
    assert response.status_code == 422


def test_run_logs_endpoint_scopes_to_run(isolated_db: str) -> None:
    client = make_client()
    created = client.post(
        "/api/runs", json={"research_goal": "logs endpoint test"}
    )
    run_id = created.json()["id"]
    _seed(isolated_db, "global line")
    _seed(isolated_db, "run line", run_id=run_id)
    body = client.get(f"/api/runs/{run_id}/logs").json()
    assert [row["message"] for row in body["logs"]] == ["run line"]


def test_run_logs_endpoint_unknown_run_is_404(isolated_db: str) -> None:
    assert make_client().get("/api/runs/nope/logs").status_code == 404

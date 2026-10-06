# Expose diagnostic delivery failures without turning anonymous submission into
# an email relay.

from __future__ import annotations

from typing import Any

import pytest

import app.logs_api as logs_rate_limit
from app import logs_api
from app.config import settings
from tests._client import make_client

HEADERS = {"X-Client-ID": "reporting-scientist"}


@pytest.fixture(autouse=True)
def fresh_report_budget() -> None:
    logs_rate_limit._report_hits.clear()


def _configure_smtp(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@example.org")
    sent: list[tuple[str, ...]] = []

    async def _deliver(recipient: str, subject: str, body: str) -> None:
        sent.append((recipient, subject, body))

    monkeypatch.setattr(logs_api, "deliver_email", _deliver)
    return sent


def test_a_report_is_emailed_to_the_configured_operator(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _configure_smtp(monkeypatch)
    monkeypatch.setattr(settings, "log_report_email", "ops@example.org")

    response = make_client().post(
        "/api/logs/report",
        json={"report": "=== LOGS (JSON) ===\n[]"},
        headers=HEADERS,
    )

    assert response.status_code == 202
    recipient, subject, body = sent[0]
    assert recipient == "ops@example.org"
    assert "reporting-scientist" in subject
    assert body == "=== LOGS (JSON) ===\n[]"


def test_an_undeliverable_report_fails_at_the_button(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from_email", "")

    response = make_client().post(
        "/api/logs/report", json={"report": "anything"}, headers=HEADERS
    )

    assert response.status_code == 503


def test_a_failed_send_is_reported_as_such(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_smtp(monkeypatch)

    async def _fail(*_args: Any) -> None:
        raise RuntimeError("smtp refused")

    monkeypatch.setattr(logs_api, "deliver_email", _fail)

    response = make_client().post(
        "/api/logs/report", json={"report": "anything"}, headers=HEADERS
    )

    assert response.status_code == 502


def test_reporting_is_rate_limited(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_smtp(monkeypatch)
    client = make_client()

    statuses = [
        client.post(
            "/api/logs/report", json={"report": "spam"}, headers=HEADERS
        ).status_code
        for _ in range(logs_rate_limit.REPORTS_PER_MINUTE + 1)
    ]

    assert statuses[:-1] == [202] * logs_rate_limit.REPORTS_PER_MINUTE
    assert statuses[-1] == 429

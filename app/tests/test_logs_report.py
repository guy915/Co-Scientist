"""Tests for emailing a diagnostic export to the operator.

The Logs panel's Report button is the one path by which a scientist who
cannot reach the operator can hand over what their browser saw, so what
matters here is that an undeliverable report fails loudly at the button
rather than disappearing, and that the endpoint cannot be turned into a
mail relay by the anonymous callers it has to accept.
"""

from __future__ import annotations

from typing import Any

import pytest

import app.logs_api as logs_rate_limit
from app import logs_api, notifications
from app.config import settings
from tests._client import make_client

HEADERS = {"X-Client-ID": "reporting-scientist"}


@pytest.fixture(autouse=True)
def fresh_report_budget() -> None:
    """Give each test the full per-minute report budget."""
    logs_rate_limit._report_hits.clear()


def _configure_smtp(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Pretend an SMTP transport exists; return the messages sent through it."""
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
    """The submitted export reaches the address configured on the server."""
    sent = _configure_smtp(monkeypatch)
    monkeypatch.setattr(settings, "log_report_email", "ops@example.org")

    response = make_client().post(
        "/api/logs/report",
        json={"report": "=== LOGS (JSON) ===\n[]"},
        headers=HEADERS,
    )

    assert response.status_code == 202
    recipient, subject, body = sent[0]
    # The recipient is a setting, never a request field, so the endpoint
    # cannot be pointed at a third party; the subject is assembled here for
    # the same reason, leaving the submitted text as a body only.
    assert recipient == "ops@example.org"
    assert "reporting-scientist" in subject
    assert body == "=== LOGS (JSON) ===\n[]"


def test_an_undeliverable_report_fails_at_the_button(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No transport means 503, not a silent success."""
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from_email", "")

    response = make_client().post(
        "/api/logs/report", json={"report": "anything"}, headers=HEADERS
    )

    assert response.status_code == 503


def test_a_failed_send_is_reported_as_such(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transport that raises surfaces as 502 rather than a claimed send."""
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
    """One click is one report; a flood is capped well short of an inbox."""
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


def test_an_oversized_report_is_refused(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The body is capped so the endpoint is not a bulk-mail relay."""
    _configure_smtp(monkeypatch)

    response = make_client().post(
        "/api/logs/report",
        json={"report": "x" * (logs_api.MAX_REPORT_CHARS + 1)},
        headers=HEADERS,
    )

    assert response.status_code == 422


def test_completion_mail_and_reports_share_one_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``deliver_email`` is the single place a message leaves this process."""
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        notifications, "_send_smtp", lambda *args: sent.append(args)
    )

    import asyncio

    asyncio.run(notifications.deliver_email("to@example.org", "subj", "body"))

    assert sent == [("to@example.org", "subj", "body")]

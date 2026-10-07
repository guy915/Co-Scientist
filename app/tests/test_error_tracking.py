from __future__ import annotations

from typing import Any

import pytest
import sentry_sdk
from co_scientist.core.byok_scope import ByokCredential, scoped_byok
from co_scientist.platform.telemetry import error_tracking


def test_error_tracking_stays_off_without_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    assert error_tracking.init_error_tracking("  ", "production") is False
    assert calls == []


def test_reports_drop_request_headers_bodies_and_query_strings() -> None:
    event = {
        "request": {
            "method": "POST",
            "url": "https://api.example/api/runs",
            "headers": {"X-Client-ID": "owner-capability"},
            "cookies": {"session": "s"},
            "data": {"goal": "unpublished idea"},
            "query_string": "client_id=owner-capability",
        }
    }

    scrubbed = error_tracking.scrub_event(event, secrets=())

    assert scrubbed["request"] == {"method": "POST", "url": "https://api.example/api/runs"}


def test_reports_redact_deployment_and_run_scoped_keys_everywhere() -> None:
    credential = ByokCredential(provider="openrouter", api_key="sk-run-scoped-key", model="m")
    event = {
        "exception": {"values": [{"value": "401 for sk-deploy-key-123 and sk-run-scoped-key"}]},
        "breadcrumbs": {"values": [{"message": "retrying with sk-deploy-key-123"}]},
    }

    with scoped_byok(credential):
        scrubbed = error_tracking.scrub_event(event, secrets=("sk-deploy-key-123",))

    assert scrubbed["exception"]["values"][0]["value"] == "401 for [REDACTED] and [REDACTED]"
    assert scrubbed["breadcrumbs"]["values"][0]["message"] == "retrying with [REDACTED]"


def test_error_tracking_sends_no_pii_locals_bodies_or_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-deploy-secret")

    assert error_tracking.init_error_tracking("https://key@sentry.example/1", "production")

    (options,) = calls
    assert options["environment"] == "production"
    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False
    assert options["max_request_body_size"] == "never"
    assert options["traces_sample_rate"] is None
    assert options["before_send_transaction"]({}, {}) is None
    assert options["auto_enabling_integrations"] is False
    event = options["before_send"]({"message": "key sk-or-deploy-secret leaked"}, {})
    assert event["message"] == "key [REDACTED] leaked"

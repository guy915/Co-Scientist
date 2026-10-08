from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import unquote

from co_scientist.core.byok_scope import redact_byok_text
from co_scientist.platform.telemetry.tracing import OTLP_HEADER_ENV_VARS

# Deployment credentials can surface in provider error text; any variable
# named like a secret is scrubbed wherever it appears in a report.
_SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|DSN)$")
_MIN_SECRET_LENGTH = 8
# X-Client-ID is a bearer-style ownership capability, and bodies carry
# research content and keys, so reports keep only the method and route.
_DROPPED_REQUEST_FIELDS = ("headers", "cookies", "data", "query_string", "env")


def _deployment_secrets() -> tuple[str, ...]:
    values = {
        value
        for name, value in os.environ.items()
        if _SECRET_NAME.search(name.upper()) and len(value) >= _MIN_SECRET_LENGTH
    }
    for name in OTLP_HEADER_ENV_VARS:
        raw = os.environ.get(name, "")
        values.update((raw, unquote(raw)))
        for header in raw.split(","):
            _, _, value = header.partition("=")
            values.update((value.strip(), unquote(value).strip()))
    return tuple(sorted((v for v in values if len(v) >= _MIN_SECRET_LENGTH), key=len, reverse=True))


def _scrub(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        value = redact_byok_text(value)
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {key: _scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item, secrets) for item in value]
    return value


def scrub_event(event: dict[str, Any], secrets: tuple[str, ...]) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        for field in _DROPPED_REQUEST_FIELDS:
            request.pop(field, None)
    scrubbed: dict[str, Any] = _scrub(event, secrets)
    return scrubbed


def init_error_tracking(dsn: str, environment: str) -> bool:
    """The SDK is imported only when a DSN is configured, so local runs, CI
    and forks neither pay its startup cost nor send anything.
    """
    if not dsn.strip():
        return False
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    secrets = _deployment_secrets()

    def before_send(event: Any, hint: Any) -> Any:
        return scrub_event(event, secrets)

    sentry_sdk.init(
        dsn=dsn.strip(),
        environment=environment.strip() or None,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=None,
        before_send=before_send,
        before_send_transaction=lambda event, hint: None,
        # Auto-enabled AI and HTTP-client integrations attach prompts and
        # model output, and importing them adds 1.6 s to startup.
        auto_enabling_integrations=False,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    )
    return True

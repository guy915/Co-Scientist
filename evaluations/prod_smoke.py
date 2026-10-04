"""Non-mutating smoke checks against a deployed Co-Scientist API (N33).

Everything else in ``evaluations/`` runs offline by design (see the package
README); this is the one deliberate exception -- it makes real HTTP requests
to a live deployment. It exists to catch exactly the class of thing offline
tests structurally cannot: that production auth/CORS/ownership behave the
way the code says they should, that the deployed MCP/SMTP integrations are
in the state the operator believes them to be in, and that a stale public
share link fails closed.

**Non-mutating is the hard requirement.** Every check below is a GET or an
OPTIONS preflight against an endpoint that either always existed (``/health``,
``/status``) or is addressed by a random id that (overwhelmingly) does not
exist (a fresh UUID4, a 32-byte random share token). Nothing here creates a
run, a share, a message, or any other row -- there is no POST, PUT, PATCH,
or DELETE call anywhere in this module. Add a check here only if it stays
that way.

Not CI. This calls a real network host, which the hermetic-CI rule (see
``docs/CI.md``: "no external network, no API keys, no retries") rules out
of every blocking job. Run it by hand before/after a release:

    python -m evaluations.prod_smoke
    python -m evaluations.prod_smoke --base-url https://api.ai-co-scientist.com

Exit code 0 means every check passed; 1 means at least one failed. A few
checks are informational only (they report a fact -- e.g. "SMTP is
unconfigured" -- rather than asserting a specific value, since that fact is
an operator decision, not a correctness property) and never fail the run.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.ai-co-scientist.com"
_UNTRUSTED_ORIGIN = "https://evil.example.invalid"
_TIMEOUT_SECONDS = 15.0


@dataclass
class CheckResult:
    name: str
    ok: bool
    info: str
    blocking: bool = True


class _FailedRequest:
    def __init__(self, exc: httpx.HTTPError) -> None:
        self.exc = exc


def _get(
    client: httpx.Client, path: str, **kwargs: Any
) -> httpx.Response | _FailedRequest:
    """Connection failures are findings to report, not harness crashes."""
    try:
        return client.get(path, timeout=_TIMEOUT_SECONDS, **kwargs)
    except httpx.HTTPError as exc:
        return _FailedRequest(exc)


def check_health(client: httpx.Client) -> CheckResult:
    resp = _get(client, "/health")
    if isinstance(resp, _FailedRequest):
        return CheckResult("health", False, f"request failed: {resp.exc}")
    if resp.status_code != 200:
        return CheckResult("health", False, f"status {resp.status_code}")
    status = resp.json().get("status")
    ok = status in ("healthy", "degraded")
    return CheckResult("health", ok, f"reported status={status!r}")


def check_status_probes(client: httpx.Client) -> CheckResult:
    """Missing optional integrations are operator configuration, not smoke
    failures.
    """
    resp = _get(client, "/status")
    if isinstance(resp, _FailedRequest):
        return CheckResult(
            "status_probes", False, f"request failed: {resp.exc}"
        )
    if resp.status_code != 200:
        return CheckResult("status_probes", False, f"status {resp.status_code}")
    body = resp.json()
    info = (
        f"mcp_available={body.get('mcp_available')} "
        f"email_notifications_available="
        f"{body.get('email_notifications_available')} "
        f"llm_backend={body.get('llm_backend')!r}"
    )
    return CheckResult("status_probes", True, info, blocking=False)


def check_ownership_isolation(client: httpx.Client) -> CheckResult:
    """Random unissued IDs probe ownership/absence without creating
    production records.
    """
    bogus_id = str(uuid.uuid4())
    resp = _get(
        client,
        f"/api/runs/{bogus_id}",
        headers={"X-Client-ID": f"prod-smoke-{uuid.uuid4()}"},
    )
    if isinstance(resp, _FailedRequest):
        return CheckResult(
            "ownership_isolation", False, f"request failed: {resp.exc}"
        )
    ok = resp.status_code == 404
    return CheckResult(
        "ownership_isolation", ok, f"status {resp.status_code} (want 404)"
    )


def check_cors_untrusted_origin(client: httpx.Client) -> CheckResult:
    """Untrusted CORS echoes would expose authenticated responses to
    arbitrary web pages.
    """
    resp = _get(
        client,
        "/health",
        headers={"Origin": _UNTRUSTED_ORIGIN},
    )
    if isinstance(resp, _FailedRequest):
        return CheckResult(
            "cors_untrusted_origin", False, f"request failed: {resp.exc}"
        )
    echoed = resp.headers.get("access-control-allow-origin")
    ok = echoed not in (_UNTRUSTED_ORIGIN, "*")
    return CheckResult(
        "cors_untrusted_origin",
        ok,
        f"Access-Control-Allow-Origin={echoed!r} for an untrusted origin",
    )


def check_sanitized_share_404(client: httpx.Client) -> CheckResult:
    """Random unissued share tokens probe confidentiality without creating
    shares.
    """
    bogus_token = uuid.uuid4().hex + uuid.uuid4().hex
    resp = _get(client, f"/api/shared/{bogus_token}")
    if isinstance(resp, _FailedRequest):
        return CheckResult(
            "sanitized_share_404", False, f"request failed: {resp.exc}"
        )
    if resp.status_code != 404:
        return CheckResult(
            "sanitized_share_404",
            False,
            f"status {resp.status_code} (want 404)",
        )
    leaky_markers = ("Traceback", "sqlite3.", "SELECT ", "/app/", "/Users/")
    body_text = resp.text
    leaked = [m for m in leaky_markers if m in body_text]
    ok = not leaked
    info = "clean 404" if ok else f"leaked markers in body: {leaked}"
    return CheckResult("sanitized_share_404", ok, info)


_CHECKS = (
    check_health,
    check_status_probes,
    check_ownership_isolation,
    check_cors_untrusted_origin,
    check_sanitized_share_404,
)


def run(
    base_url: str, *, transport: httpx.BaseTransport | None = None
) -> list[CheckResult]:
    with httpx.Client(base_url=base_url, transport=transport) as client:
        return [check(client) for check in _CHECKS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL to smoke (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args(argv)

    results = run(args.base_url)
    failed_blocking = False
    for result in results:
        marker = "OK  " if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {result.info}")
        if not result.ok and result.blocking:
            failed_blocking = True

    if failed_blocking:
        print("prod_smoke: FAILED")
        return 1
    print("prod_smoke: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

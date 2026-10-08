import json
import math
import re
from pathlib import Path
from typing import Any

import httpx
from co_scientist.platform.llm.decisions import (
    DecisionSettings,
    DecisionUnavailableError,
    SystemOneClient,
)
from co_scientist.platform.llm.telemetry import scoped_telemetry

from evaluations.decision_cases import DecisionCase

_QUOTA_FIELDS = {
    "limit",
    "remaining",
    "reset",
    "retry_after",
    "max_tokens",
    "max_requests",
    "tokens_per_minute",
    "tokens_per_hour",
    "tokens_per_day",
    "requests_per_minute",
    "requests_per_hour",
    "requests_per_day",
    "remaining_tokens",
    "remaining_requests",
}
_CONTAINERS = {"error", "detail", "limits", "rate_limit", "quota"}
_MESSAGES = {"error", "detail", "message", "reason"}
_AMOUNT = re.compile(
    r"\b(\d[\d,]*(?:\.\d+)?)\s*(tokens?|requests?|questions?)"
    r"\s*(?:per|/)\s*(second|minute|hour|day)s?\b",
    re.IGNORECASE,
)
_TERMS = ("token", "request", "question", "minute", "hour", "day", "quota", "capacity")


def quota_metadata(payload: Any, key: str) -> dict[str, Any]:
    numbers: dict[str, int | float] = {}
    matches = []
    terms: set[str] = set()

    def visit(node: Any, depth: int) -> None:
        if not isinstance(node, dict) or depth > 4:
            return
        for name, value in node.items():
            if (
                name in _QUOTA_FIELDS
                and type(value) in (int, float)
                and math.isfinite(value)
                and 0 <= value <= 1_000_000_000_000
            ):
                numbers[name] = value
            if name in _CONTAINERS:
                visit(value, depth + 1)
            if name not in _MESSAGES or not isinstance(value, str):
                continue
            if key and (key in value or key[:8] in value):
                continue
            for amount, unit, window in _AMOUNT.findall(value):
                numeric = float(amount.replace(",", ""))
                if math.isfinite(numeric) and 0 <= numeric <= 1_000_000_000_000:
                    matches.append(
                        {
                            "amount": numeric,
                            "unit": unit.lower().rstrip("s"),
                            "window": window.lower(),
                        }
                    )
            for term in _TERMS:
                if re.search(rf"\b{term}s?\b", value, re.IGNORECASE):
                    terms.add(term)

    visit(payload, 0)
    return {
        "numeric_fields": numbers,
        "reported_quotas": matches,
        "recognized_terms": sorted(terms),
    }


class QuotaCapture:
    def __init__(self, key: str) -> None:
        self._key = key
        self.metadata: dict[str, Any] = {}

    async def observe(self, response: httpx.Response) -> None:
        self.metadata["status"] = response.status_code
        if response.status_code < 400:
            return
        content = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            if len(content) + len(chunk) > 16_384:
                self.metadata["body_exceeded_diagnostic_bound"] = True
                return
            content.extend(chunk)
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            self.metadata["body_was_json"] = False
            return
        self.metadata.update(quota_metadata(payload, self._key))


async def run_quota_diagnostic(
    case: DecisionCase,
    settings: DecisionSettings,
    output: Path,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    capture = QuotaCapture(settings.api_key)
    client = SystemOneClient(settings, transport=transport, response_hook=capture.observe)
    report: dict[str, Any] = {"diagnostic_only": True, "adoption_ready": False}
    with scoped_telemetry("decision_quota") as telemetry:
        try:
            result = await client.decide(case.decision_prompt or case.prompt, case.questions)
            report["rate_limits"] = result.rate_limits
            report["input_tokens"] = result.input_tokens
        except Exception as error:
            report["error"] = type(error).__name__
            if isinstance(error, DecisionUnavailableError):
                report["provider_status"] = error.status_code
                report["rate_limits"] = error.rate_limits
        report["usage"] = telemetry.snapshot()
    report["quota_metadata"] = capture.metadata
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    return report

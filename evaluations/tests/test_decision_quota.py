import json
from pathlib import Path

import httpx
import pytest
from co_scientist.platform.llm.decisions import DecisionSettings, Question

from evaluations.decision_cases import DecisionCase
from evaluations.decision_quota import QuotaCapture, quota_metadata, run_quota_diagnostic


def test_quota_metadata_exports_only_numeric_allowlist_and_recognized_units() -> None:
    result = quota_metadata(
        {
            "error": {
                "message": "PRIVATE TEXT: free tier allows 100,000 tokens per hour",
                "limit": 100000,
                "remaining": 8000,
                "secret": "PRIVATE KEY",
                "prompt": "PRIVATE RESEARCH",
            }
        },
        "synthetic-key",
    )
    assert result["numeric_fields"] == {"limit": 100000, "remaining": 8000}
    assert result["reported_quotas"] == [{"amount": 100000, "unit": "token", "window": "hour"}]
    assert "PRIVATE" not in json.dumps(result)


def test_quota_metadata_discards_secret_echoes_and_nonfinite_numbers() -> None:
    result = quota_metadata(
        {"message": "synthetic-key 1000 tokens per day", "limit": float("nan"), "remaining": True},
        "synthetic-key",
    )
    assert result == {"numeric_fields": {}, "reported_quotas": [], "recognized_terms": []}


@pytest.mark.asyncio
async def test_diagnostic_is_one_bounded_fake_request_without_oracle_or_raw_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COSCIENTIST_DB_PATH", str(tmp_path / "admission.db"))
    seen = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            429,
            headers={"Retry-After": "1"},
            json={"detail": "PRIVATE RESEARCH: 100000 tokens per hour"},
        )

    settings = DecisionSettings(api_key="synthetic-key", enabled=True)
    case = DecisionCase("id", "PRIVATE INPUT", {}, {"gate": Question("noul", "PRIVATE QUESTION")})
    output = tmp_path / "report.json"
    report = await run_quota_diagnostic(
        case, settings, output, transport=httpx.MockTransport(reply)
    )
    assert len(seen) == 1
    assert report["provider_status"] == 429
    assert report["quota_metadata"]["reported_quotas"][0]["window"] == "hour"
    assert report["usage"]["decision_quota::liquid/d1:free"]["calls"] == 1
    assert "PRIVATE" not in output.read_text()
    assert "synthetic-key" not in output.read_text()


@pytest.mark.asyncio
async def test_error_body_capture_is_bounded_and_does_not_export_truncated_content() -> None:
    capture = QuotaCapture("synthetic-key")
    await capture.observe(httpx.Response(429, content=b"PRIVATE" * 3000))
    assert capture.metadata == {"status": 429, "body_exceeded_diagnostic_bound": True}

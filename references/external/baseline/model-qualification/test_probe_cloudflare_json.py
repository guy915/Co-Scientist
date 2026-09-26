"""Offline contract tests for the bounded Cloudflare JSON probe."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace



FOLDER = Path(__file__).resolve().parent
ACCOUNT_ID = "a" * 32
TOKEN = "synthetic-cloudflare-token"


def _probe(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(FOLDER))
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    monkeypatch.setenv(
        "COSCIENTIST_CLOUDFLARE_WORKERS_FREE_ATTESTATION",
        f"{datetime.now(timezone.utc).date().isoformat()}:{ACCOUNT_ID}:workers-free",
    )
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(tmp_path / "qualification.json"))
    monkeypatch.setenv("QUALIFICATION_PREREG", str(tmp_path / "prereg.json"))
    monkeypatch.delenv("QUALIFICATION_PREREG_SHA256", raising=False)
    probe = importlib.import_module("probe_cloudflare_json")
    probe = importlib.reload(probe)
    prereg = probe._expected_prereg()
    prereg_bytes = (json.dumps(prereg, sort_keys=True, separators=(",", ":")) + "\n").encode()
    prereg_path = Path(str(tmp_path / "prereg.json"))
    prereg_path.write_bytes(prereg_bytes)
    monkeypatch.setenv(
        "QUALIFICATION_PREREG_SHA256", probe.sha256(prereg_bytes)
    )
    return probe


def _response(probe, content=None):
    return SimpleNamespace(
        model=probe.MODEL,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content or json.dumps(
                        {
                            "label": "supports",
                            "quote": "treatment X reduced cell viability by 30%",
                        }
                    )
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=42, completion_tokens=11, total_tokens=53),
    )


def test_live_probe_calls_public_json_boundary_once_with_pinned_options(
    monkeypatch, tmp_path
):
    probe = _probe(monkeypatch, tmp_path)
    from co_scientist import llm_request

    monkeypatch.setattr(llm_request, "_supports_json_schema_response_format", lambda _model: False)
    transport_calls = []
    public_calls = []
    actual_call = probe.call_llm_json

    async def completion(**kwargs):
        transport_calls.append(kwargs)
        return _response(probe)

    async def observed_json_call(*args, **kwargs):
        public_calls.append((args, kwargs))
        return await actual_call(*args, **kwargs)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    monkeypatch.setattr(probe, "call_llm_json", observed_json_call)

    assert probe.main() == 0
    assert len(public_calls) == 1
    assert len(transport_calls) == 1
    prompt, spec = public_calls[0][0]
    options = public_calls[0][1]["options"]
    assert prompt == probe.PROMPT
    assert spec.model_name == "openai/@cf/google/gemma-4-26b-a4b-it"
    assert spec.max_tokens <= 4096
    assert public_calls[0][1]["max_attempts"] == 1
    assert options.use_cache is False
    assert options.enable_thinking is False
    request = transport_calls[0]
    assert request["model"] == spec.model_name
    assert request["max_retries"] == 0
    assert request["max_tokens"] <= 4096
    assert request["drop_params"] is False
    assert request["response_format"] == {"type": "json_object"}
    assert request["api_base"].endswith("/accounts/" + ACCOUNT_ID + "/ai/v1")
    assert request["extra_body"]["options"]["rejectIfBusy"] is True
    artifact = json.loads(Path(str(tmp_path / "qualification.json")).read_text())
    assert artifact["passed"] is True
    assert artifact["physical_request_count"] == 1
    observed = artifact["request_observations"][0]
    assert observed["response_format"] == request["response_format"]
    assert observed["response_format_downgraded"] is True
    assert observed["max_retries"] == 0
    assert observed["rejectIfBusy"] is True
    assert observed["served_model"] == probe.MODEL
    assert observed["usage"] == {
        "prompt_tokens": 42,
        "completion_tokens": 11,
        "total_tokens": 53,
    }
    assert ACCOUNT_ID not in json.dumps(artifact)
    assert TOKEN not in json.dumps(artifact)


def test_raw_provider_json_must_explicitly_support_before_backfill(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path)
    from co_scientist import llm_request

    monkeypatch.setattr(llm_request, "_supports_json_schema_response_format", lambda _model: False)
    raw = json.dumps({"quote": "treatment X reduced cell viability by 30%"})

    async def completion(**_kwargs):
        return _response(probe, raw)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    assert probe.main() == 1
    artifact = json.loads(Path(str(tmp_path / "qualification.json")).read_text())
    assert artifact["response"]["label"] == "supports"
    assert artifact["request_observations"][0]["provider_content"] == raw
    assert artifact["passed"] is False


def test_second_transport_attempt_is_rejected_and_artifact_is_failed(
    monkeypatch, tmp_path
):
    probe = _probe(monkeypatch, tmp_path)
    forwarded = []

    async def completion(**kwargs):
        forwarded.append(kwargs)
        return _response(probe)

    async def try_twice(_prompt, _spec, **_kwargs):
        import litellm

        request = {
            "model": probe.MODEL,
            "messages": [{"role": "user", "content": probe.PROMPT}],
            "max_tokens": probe.MAX_TOKENS,
            "response_format": {"type": "json_object"},
            "api_base": "https://api.cloudflare.com/client/v4/accounts/"
            + ACCOUNT_ID
            + "/ai/v1",
            "extra_body": {"options": {"rejectIfBusy": True}},
        }
        await litellm.acompletion(**request)
        await litellm.acompletion(**request)
        return {"label": "supports", "quote": "treatment X reduced cell viability"}

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    monkeypatch.setattr(probe, "call_llm_json", try_twice)

    assert probe.main() == 1
    assert len(forwarded) == 1
    artifact = json.loads(Path(str(tmp_path / "qualification.json")).read_text())
    assert artifact["physical_request_count"] == 1
    assert artifact["error_type"] == "RuntimeError"
    assert "one-physical-call" in artifact["error"]
    assert artifact["passed"] is False


def test_missing_response_format_is_blocked_before_provider_transport(
    monkeypatch, tmp_path
):
    probe = _probe(monkeypatch, tmp_path)
    forwarded = []

    async def completion(**kwargs):
        forwarded.append(kwargs)
        return _response(probe)

    async def omit_format(_prompt, _spec, **_kwargs):
        import litellm

        return await litellm.acompletion(
            model=probe.MODEL,
            messages=[{"role": "user", "content": probe.PROMPT}],
            max_tokens=probe.MAX_TOKENS,
        )

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    monkeypatch.setattr(probe, "call_llm_json", omit_format)

    assert probe.main() == 1
    assert forwarded == []
    artifact = json.loads(Path(str(tmp_path / "qualification.json")).read_text())
    assert artifact["physical_request_count"] == 0
    assert artifact["request_observations"][0]["response_format"] is None
    assert artifact["request_observations"][0]["response_format_downgraded"] is False
    assert artifact["error_type"] == "RuntimeError"


def test_missing_current_attestation_is_rejected_without_a_provider_call(
    monkeypatch, tmp_path
):
    probe = _probe(monkeypatch, tmp_path)
    monkeypatch.delenv("COSCIENTIST_CLOUDFLARE_WORKERS_FREE_ATTESTATION")
    forwarded = []

    async def completion(**kwargs):
        forwarded.append(kwargs)
        return _response(probe)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    assert probe.main() == 1
    assert forwarded == []
    artifact = json.loads(Path(str(tmp_path / "qualification.json")).read_text())
    assert artifact["physical_request_count"] == 0
    assert artifact["error_type"] == "ValueError"
    assert "attestation" in artifact["error"].lower()


def test_provider_failure_artifact_redacts_token_and_account_id(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path)

    async def completion(**_kwargs):
        raise RuntimeError(f"failed for token={TOKEN} account={ACCOUNT_ID}")

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    assert probe.main() == 1
    artifact_text = Path(str(tmp_path / "qualification.json")).read_text()
    artifact = json.loads(artifact_text)
    assert artifact["passed"] is False
    assert artifact["physical_request_count"] == 1
    assert artifact["request_observations"][0]["error_type"] == "RuntimeError"
    assert "[redacted-token]" in artifact_text
    assert "[redacted-account]" in artifact_text
    assert TOKEN not in artifact_text
    assert ACCOUNT_ID not in artifact_text

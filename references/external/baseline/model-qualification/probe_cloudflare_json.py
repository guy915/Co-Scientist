"""Run one preregistered Cloudflare Workers AI JSON qualification call."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import importlib
import json
import os
import re
from pathlib import Path
from typing import Any

import litellm

from co_scientist import llm_call_budget, llm_free_policy
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
    extract_response_json,
)

MODEL = "openai/@cf/google/gemma-4-26b-a4b-it"
MAX_TOKENS, MAX_ATTEMPTS, TIMEOUT_SECONDS = 2048, 1, 45
PHYSICAL_CALL_CAP = 1
SDK_MAX_RETRIES = 0
PASSAGE = (
    "In this experiment, treatment X reduced cell viability by 30% relative to "
    "vehicle. This observation does not establish clinical benefit."
)
PROMPT = (
    "Classify whether the passage supports the claim. Return only JSON with "
    "label and a verbatim quote.\nClaim: Treatment X reduced cell viability "
    f"in this experiment.\nPassage: {PASSAGE}"
)
SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["supports", "contradicts", "insufficient"]},
        "quote": {"type": "string"},
    },
    "required": ["label", "quote"],
    "additionalProperties": False,
}
PASS_CRITERION = "label=supports and quote is a nonempty verbatim substring of the fixed passage"
SOURCE_MODULES = (
    "co_scientist.llm",
    "co_scientist.llm_call",
    "co_scientist.llm_tool_loop",
    "co_scientist.llm_json_retry",
    "co_scientist.llm_json_attempt",
    "co_scientist.llm_json",
    "co_scientist.llm_json_repair",
    "co_scientist.llm_request",
    "co_scientist.llm_request_schema",
    "co_scientist.llm_free_policy",
    "co_scientist.llm_call_budget",
    "co_scientist.llm_response",
    "co_scientist.llm_credentials",
    "co_scientist.llm_thinking",
    "co_scientist.llm_types",
)
PREREG = Path(__file__).resolve().with_name("cloudflare-json-probe-prereg-v1.json")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def protocol_hashes() -> dict[str, str]:
    return {
        "prompt_sha256": sha256(PROMPT.encode()),
        "schema_sha256": sha256(json.dumps(SCHEMA, sort_keys=True, separators=(",", ":")).encode()),
    }


def source_hashes() -> dict[str, str]:
    return {
        "probe_cloudflare_json.py": sha256(Path(__file__).read_bytes()),
        **{
            name: sha256(Path(importlib.import_module(name).__file__).resolve().read_bytes())
            for name in SOURCE_MODULES
        },
    }


def _expected_prereg() -> dict[str, Any]:
    return {
        "version": 1,
        "candidate": MODEL,
        "max_tokens": MAX_TOKENS,
        "max_attempts": MAX_ATTEMPTS,
        "sdk_max_retries": SDK_MAX_RETRIES,
        "physical_call_cap": PHYSICAL_CALL_CAP,
        "timeout_seconds": TIMEOUT_SECONDS,
        "cache_enabled": False,
        "thinking_enabled": False,
        "campaign_mode": True,
        "reject_if_busy": True,
        "response_format_required": True,
        "pass_criterion": PASS_CRITERION,
        "source_sha256": source_hashes(),
        **protocol_hashes(),
    }


def _load_prereg() -> tuple[dict[str, Any], str]:
    raw = Path(os.getenv("QUALIFICATION_PREREG", str(PREREG))).read_bytes()
    digest = sha256(raw)
    if os.getenv("QUALIFICATION_PREREG_SHA256") != digest:
        raise ValueError("qualification preregistration digest is missing or mismatched")
    prereg = json.loads(raw)
    if not isinstance(prereg, dict):
        raise ValueError("qualification preregistration must be a JSON object")
    for key, expected in _expected_prereg().items():
        if prereg.get(key) != expected:
            raise ValueError(f"qualification preregistration differs at {key}")
    return prereg, digest


def _attestation_date() -> str:
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    if (
        re.fullmatch(r"[a-fA-F0-9]{32}", account) is None
        or not os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        or os.getenv("COSCIENTIST_CLOUDFLARE_WORKERS_FREE_ATTESTATION")
        != f"{today}:{account}:workers-free"
    ):
        raise ValueError("current Cloudflare Workers Free attestation is required")
    return today


def _safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    value = json.loads(json.dumps(value, default=str))
    if isinstance(value, str):
        account, token = os.getenv("CLOUDFLARE_ACCOUNT_ID", ""), os.getenv("CLOUDFLARE_API_TOKEN", "")
        if token:
            value = value.replace(token, "[redacted-token]")
        if account:
            value = value.replace(account, "[redacted-account]")
        return re.sub(r"(?i)(accounts/)[a-f0-9]{32}", r"\1[redacted-account]", value)[:2000]
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    return value


def _get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _usage(response: Any) -> dict[str, int | None] | None:
    usage = _get(response, "usage")
    if usage is None:
        return None
    return {
        key: value if isinstance(value := _get(usage, key), int) and not isinstance(value, bool) else None
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }


def _serve_model_matches(model: Any) -> bool:
    return isinstance(model, str) and model in {MODEL, MODEL.removeprefix("openai/")}


def main() -> int:
    output = Path(os.environ["QUALIFICATION_OUTPUT"])
    record: dict[str, Any] = {
        "requested_model": MODEL,
        "prompt": PROMPT,
        "schema": SCHEMA,
        "pass_criterion": PASS_CRITERION,
        "max_attempts": MAX_ATTEMPTS,
        "sdk_max_retries": SDK_MAX_RETRIES,
        "max_tokens": MAX_TOKENS,
        "timeout_seconds": TIMEOUT_SECONDS,
        "cache_enabled": False,
        "thinking_enabled": False,
        "campaign_mode": True,
        "passed": False,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    artifact = output.open("x", encoding="utf-8")
    original = litellm.acompletion
    record["request_observations"] = []
    record["physical_request_count"] = 0
    raw_candidates = []

    async def observed_transport(**kwargs):
        response_format = _safe(kwargs.get("response_format"))
        native = (
            isinstance(response_format, dict)
            and response_format.get("type") == "json_schema"
            and isinstance(response_format.get("json_schema"), dict)
            and response_format["json_schema"].get("schema") == SCHEMA
        )
        downgraded = isinstance(response_format, dict) and response_format.get("type") == "json_object"
        body = kwargs.get("extra_body", {})
        options = body.get("options", {}) if isinstance(body, dict) else {}
        route = _safe(str(kwargs.get("api_base", "")))
        item = {
            "requested_model": _safe(str(kwargs.get("model", ""))),
            "route": route,
            "response_format": response_format,
            "response_format_downgraded": downgraded,
            "max_tokens": kwargs.get("max_tokens"),
            "temperature": kwargs.get("temperature"),
            "drop_params": kwargs.get("drop_params"),
            "max_retries": SDK_MAX_RETRIES,
            "rejectIfBusy": options.get("rejectIfBusy"),
            "dispatched": False,
        }
        record["request_observations"].append(item)
        if not (native or downgraded):
            item["error_type"] = "RuntimeError"
            item["error"] = "Cloudflare JSON response_format was omitted or dropped"
            raise RuntimeError(item["error"])
        if item["rejectIfBusy"] is not True:
            item["error_type"] = "RuntimeError"
            item["error"] = "Cloudflare request omitted rejectIfBusy=true"
            raise RuntimeError(item["error"])
        if record["physical_request_count"] >= PHYSICAL_CALL_CAP:
            item["error_type"] = "RuntimeError"
            item["error"] = "one-physical-call guard rejected an additional request"
            raise RuntimeError(item["error"])
        item["dispatched"] = True
        record["physical_request_count"] += 1
        try:
            # call_llm_json's attempt count does not disable SDK retries.
            kwargs["max_retries"] = SDK_MAX_RETRIES
            response = await original(**kwargs)
        except Exception as exc:
            item["error_type"], item["error"] = type(exc).__name__, _safe(str(exc))
            raise
        choice = response.choices[0] if getattr(response, "choices", None) else None
        served = _get(response, "model")
        raw_content = _get(_get(choice, "message"), "content")
        item["provider_content"] = _safe(raw_content) if isinstance(raw_content, str) else None
        raw_candidates.append(raw_content if isinstance(raw_content, str) else None)
        item.update(
            served_model=_safe(served) if isinstance(served, str) else None,
            usage=_usage(response),
            finish_reason=_get(choice, "finish_reason"),
        )
        return response

    try:
        record["source_sha256"] = source_hashes()
        record.update(protocol_hashes())
        _, record["prereg_sha256"] = _load_prereg()
        record["preregistration_file"] = Path(
            os.getenv("QUALIFICATION_PREREG", str(PREREG))
        ).name
        record["attestation_date"] = _attestation_date()
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
        os.environ["COSCIENTIST_REQUIRE_FREE_MODELS"] = "1"
        litellm.acompletion = observed_transport
        with llm_free_policy.scoped_campaign_mode(True):
            with llm_call_budget.scoped_llm_call_budget(f"cf-json:{output.resolve()}", PHYSICAL_CALL_CAP):
                result = asyncio.run(asyncio.wait_for(call_llm_json(
                    PROMPT,
                    CompletionSpec(MODEL, max_tokens=MAX_TOKENS, temperature=0, json_schema=SCHEMA),
                    max_attempts=MAX_ATTEMPTS,
                    options=LLMCallOptions(use_cache=False, enable_thinking=False),
                ), timeout=TIMEOUT_SECONDS))
        record["response"] = _safe(result)
        quote = result.get("quote") if isinstance(result, dict) else None
        if (
            not isinstance(result, dict)
            or result.get("label") != "supports"
            or not isinstance(quote, str)
            or not quote
            or quote not in PASSAGE
        ):
            raise ValueError("validated response did not satisfy the fixed support criterion")
        if len(raw_candidates) != 1 or not isinstance(raw_candidates[0], str):
            raise ValueError("provider did not return one raw JSON candidate")
        try:
            raw_result = json.loads(extract_response_json(raw_candidates[0]))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("raw provider content was not valid JSON") from exc
        raw_quote = raw_result.get("quote") if isinstance(raw_result, dict) else None
        if (
            not isinstance(raw_result, dict)
            or raw_result.get("label") != "supports"
            or not isinstance(raw_quote, str)
            or not raw_quote
            or raw_quote not in PASSAGE
        ):
            raise ValueError("raw provider JSON did not explicitly satisfy the support criterion")
        dispatched = [item for item in record["request_observations"] if item["dispatched"]]
        usage = dispatched[0].get("usage") if len(dispatched) == 1 else None
        if not _serve_model_matches(dispatched[0].get("served_model") if dispatched else None):
            raise ValueError("served model did not match the pinned Cloudflare candidate")
        if not isinstance(usage, dict) or any(not isinstance(usage.get(key), int) or usage[key] <= 0 for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
            raise ValueError("provider response did not include complete positive token usage")
        record["passed"] = True
    except Exception as exc:
        record["error_type"], record["error"] = type(exc).__name__, _safe(str(exc))
    finally:
        litellm.acompletion = original
        record["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        artifact.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
        artifact.close()
    print(json.dumps({"requested_model": MODEL, "passed": record["passed"], "physical_request_count": record["physical_request_count"], "error_type": record.get("error_type"), "artifact": str(output)}), flush=True)
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

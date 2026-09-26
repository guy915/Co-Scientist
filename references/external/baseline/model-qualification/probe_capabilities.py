"""Checkpointed live capability experiments; run with an isolated environment."""

import asyncio
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from evaluations._live_config import configure_live_environment

MODEL = configure_live_environment()
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json  # noqa: E402
from co_scientist.llm_tool_loop import ToolLoop, call_llm_with_tools  # noqa: E402
from co_scientist.llm_free_catalog import current_catalog, verify_model  # noqa: E402
from evaluations._usage_evidence import capture_usage  # noqa: E402
import litellm  # noqa: E402

_REQUESTS = []
_TRANSPORT = litellm.acompletion
_BOUNDED = os.getenv("QUALIFICATION_BOUNDED_PANEL") == "1"
_TOTAL_REQUESTS = 0
_ACTIVE_CASE = ""
_PINNED_MODEL = ""
_PINNED_REQUEST_CONTROLS = {}
_CASE_CALL_CAPS = {}
_GUARD_REJECTIONS = []

_CASES = ("json_off", "json_on", "plain_json", "tools", "streaming", "long_json")
_ROOT = Path(__file__).resolve().parents[4]
_ALLOWED_PROVIDER_EXTRAS = {"preferred_min_throughput": 25}


class QualificationGuardError(RuntimeError):
    """A bounded request would violate its preregistered routing or call cap."""


def _request_controls(kwargs):
    return {
        key: kwargs.get(key)
        for key in ("model", "max_tokens", "extra_body", "response_format", "stream")
    }


def _provider_route_error(actual, required):
    if not isinstance(actual, dict):
        return "physical request is missing preregistered provider route controls"
    if any(actual.get(key) != value for key, value in required.items()):
        return "physical request violates the preregistered provider route controls"
    if "order" in actual:
        return "physical request adds an unregistered provider route order"
    extras = set(actual) - set(required)
    if extras - set(_ALLOWED_PROVIDER_EXTRAS):
        return "physical request adds unregistered provider route controls"
    if any(
        actual[key] != value
        for key, value in _ALLOWED_PROVIDER_EXTRAS.items()
        if key in actual
    ):
        return "physical request changes the unpinned throughput preference"
    return None


def _request_guard_error(kwargs):
    if kwargs.get("model") != _PINNED_MODEL:
        return "physical request model differs from the preregistered candidate"
    extra_body = kwargs.get("extra_body")
    provider = extra_body.get("provider") if isinstance(extra_body, dict) else None
    return _provider_route_error(provider, _PINNED_REQUEST_CONTROLS)


async def observed_transport(**kwargs):
    global _TOTAL_REQUESTS
    if _BOUNDED:
        guard_error = _request_guard_error(kwargs)
        if guard_error:
            _GUARD_REJECTIONS.append(
                {"reason": guard_error, "request": _request_controls(kwargs)}
            )
            raise QualificationGuardError(guard_error)
        case_limit = 2 if _ACTIVE_CASE == "tools" else 1
        total_limit = int(os.getenv("QUALIFICATION_MAX_PHYSICAL_CALLS", "7"))
        preregistered_case_limit = _CASE_CALL_CAPS[_ACTIVE_CASE]
        if len(_REQUESTS) >= preregistered_case_limit:
            guard_error = f"preregistered physical-call cap reached for {_ACTIVE_CASE}"
            _GUARD_REJECTIONS.append(
                {"reason": guard_error, "request": _request_controls(kwargs)}
            )
            raise QualificationGuardError(guard_error)
        if len(_REQUESTS) >= case_limit or _TOTAL_REQUESTS >= total_limit:
            raise RuntimeError("qualification physical-call cap reached")
    # Capture non-secret controls before handing an admitted request to LiteLLM.
    _REQUESTS.append(_request_controls(kwargs))
    _TOTAL_REQUESTS += 1
    return await _TRANSPORT(**kwargs)


litellm.acompletion = observed_transport

PASSAGE = "Treatment X reduced cell viability by 30% relative to vehicle."
SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": ["supports", "contradicts", "insufficient"],
        },
        "quote": {"type": "string"},
    },
    "required": ["label", "quote"],
    "additionalProperties": False,
}


def sanitize_error(exc):
    message = str(exc)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return re.sub(r"user_[A-Za-z0-9]+", "[redacted-account]", message)[:2000]


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head_revision():
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=_ROOT, text=True
    ).strip()


def _selected_cases():
    raw = os.getenv("QUALIFICATION_CASES", "")
    if raw == "":
        return list(_CASES)
    requested = raw.split(",")
    allowed = set(_CASES) | {"long_json_on"}
    if any(case not in allowed for case in requested) or len(set(requested)) != len(
        requested
    ):
        raise ValueError("QUALIFICATION_CASES contains an unknown or repeated case")
    return [case for case in _CASES if case in requested] + (
        ["long_json_on"] if "long_json_on" in requested else []
    )


def _validate_bounded_prereg(selected, output):
    prereg_value = os.getenv("QUALIFICATION_PREREG")
    if not prereg_value:
        raise ValueError("QUALIFICATION_PREREG is required for a bounded panel")
    prereg_path = Path(prereg_value)
    if not prereg_path.is_absolute():
        prereg_path = _ROOT / prereg_path
    prereg_digest = os.getenv("QUALIFICATION_PREREG_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", prereg_digest):
        raise ValueError("QUALIFICATION_PREREG_SHA256 is required for a bounded panel")
    prereg_bytes = prereg_path.read_bytes()
    if hashlib.sha256(prereg_bytes).hexdigest() != prereg_digest:
        raise ValueError(
            "preregistration bytes differ from QUALIFICATION_PREREG_SHA256"
        )
    prereg = json.loads(prereg_bytes)

    candidate = prereg["candidate"]
    interface = prereg["interface_stage"]
    expected_cases = interface["cases_in_order"]
    requested_cases = os.getenv("QUALIFICATION_CASES", "")
    requested_cases = requested_cases.split(",") if requested_cases else list(_CASES)
    if candidate["model"] != MODEL:
        raise ValueError("MODEL_NAME differs from the preregistered candidate")
    if (
        expected_cases != list(_CASES)
        or selected != expected_cases
        or requested_cases != expected_cases
    ):
        raise ValueError("QUALIFICATION_CASES differs from the preregistered order")
    request_controls = candidate.get("request_controls")
    if not isinstance(request_controls, dict) or not request_controls:
        raise ValueError("preregistered candidate request controls are invalid")
    case_caps = interface.get("physical_call_caps_per_case")
    if (
        not isinstance(case_caps, dict)
        or set(case_caps) != set(_CASES)
        or any(type(cap) is not int or cap < 1 for cap in case_caps.values())
    ):
        raise ValueError("preregistered per-case physical-call caps are invalid")
    if interface["total_physical_call_cap"] != 7:
        raise ValueError("preregistered total physical-call cap must be seven")
    if int(os.getenv("QUALIFICATION_MAX_PHYSICAL_CALLS", "7")) != 7:
        raise ValueError("bounded panel physical-call cap must be seven")
    accepted_models = candidate.get("accepted_response_model_ids")
    if not isinstance(accepted_models, list) or MODEL not in accepted_models:
        raise ValueError("preregistered accepted response model ids are invalid")

    expected_output = Path(prereg["execution"]["artifact_patterns"]["interface"])
    if not expected_output.is_absolute():
        expected_output = _ROOT / expected_output
    if output.resolve() != expected_output.resolve():
        raise ValueError("QUALIFICATION_OUTPUT differs from the preregistered artifact")

    revision = os.environ.get("QUALIFICATION_REVISION")
    if not revision or revision != _head_revision():
        raise ValueError("QUALIFICATION_REVISION differs from git HEAD")

    source_hashes = prereg.get("source_sha256")
    probe_key = str(Path(__file__).resolve().relative_to(_ROOT))
    if not isinstance(source_hashes, dict) or probe_key not in source_hashes:
        raise ValueError("preregistration does not pin the capability probe")
    for relative, expected_hash in source_hashes.items():
        source = (_ROOT / relative).resolve()
        if _ROOT not in source.parents or not source.is_file():
            raise ValueError(
                f"pinned source is missing or outside the repository: {relative}"
            )
        if not isinstance(expected_hash, str) or _digest(source) != expected_hash:
            raise ValueError(f"pinned source/input hash differs: {relative}")

    return prereg


def _write_artifact(artifact, report):
    artifact.seek(0)
    artifact.truncate()
    artifact.write(json.dumps(report, indent=2) + "\n")
    artifact.flush()


def _validate_usage_evidence(result, accepted_models):
    evidence = result.get("usage_evidence")
    if not isinstance(evidence, dict) or not evidence.get("has_usage_records"):
        return "successful completion is missing usage telemetry"
    if evidence.get("recorded_deterministic_fallbacks"):
        return "successful completion used a deterministic fallback"
    model_usage = evidence.get("model_usage")
    if not isinstance(model_usage, dict):
        return "successful completion is missing per-model telemetry"

    successful_calls = 0
    recorded_calls = 0
    for key, row in model_usage.items():
        if not isinstance(row, dict):
            return "usage telemetry row is invalid"
        calls = row.get("calls")
        if type(calls) is not int or calls < 0:
            return "usage telemetry call count is invalid"
        errors = row.get("errors") or {}
        if not isinstance(errors, dict) or any(
            type(count) is not int or count < 0 for count in errors.values()
        ):
            return "usage telemetry failure counts are invalid"
        failed_calls = sum(errors.values())
        if failed_calls > calls:
            return "usage telemetry reports more failures than physical calls"
        completed = calls - failed_calls
        recorded_calls += calls
        successful_calls += completed
        if completed:
            observed = row.get("observed_model_calls")
            reported = row.get("reported_usage_calls")
            served_model = key.split("::", 1)[-1]
            if (
                served_model not in accepted_models
                or type(observed) is not int
                or observed < completed
            ):
                return "successful completion is missing accepted served-model evidence"
            if type(reported) is not int or reported < completed:
                return "successful completion is missing prompt/completion usage"
    if successful_calls == 0 or evidence.get("physical_calls") != recorded_calls:
        return "successful completion is missing physical-call telemetry"
    return None


def _validate_stream_evidence(result, accepted_models):
    models = result.get("stream_model_fields")
    if (
        not isinstance(models, list)
        or not models
        or any(model not in accepted_models for model in models)
    ):
        return "stream is missing an accepted served-model field"
    usage = result.get("reported_usage")
    if not isinstance(usage, list) or not any(
        isinstance(row, dict)
        and all(
            type(row.get(key)) is int and row[key] >= 0
            for key in ("prompt_tokens", "completion_tokens")
        )
        for row in usage
    ):
        return "stream is missing prompt/completion usage evidence"
    return None


def _validate_bounded_case(name, result, prereg):
    requests = result.get("physical_request_controls", [])
    rejections = result.get("qualification_guard_rejections", [])
    if rejections:
        return "QualificationGuardError", rejections[0]["reason"]
    candidate = prereg["candidate"]
    expected_controls = candidate["request_controls"]
    for request in requests:
        if request.get("model") != candidate["model"]:
            return (
                "QualificationGuardError",
                "physical request model differs from the preregistered candidate",
            )
        extra_body = request.get("extra_body")
        provider = extra_body.get("provider") if isinstance(extra_body, dict) else None
        route_error = _provider_route_error(provider, expected_controls)
        if route_error:
            return (
                "QualificationGuardError",
                route_error,
            )
    cap = prereg["interface_stage"]["physical_call_caps_per_case"][name]
    if len(requests) > cap:
        return (
            "QualificationGuardError",
            f"preregistered physical-call cap exceeded for {name}",
        )
    if result.get("error_type") or not result.get("passed"):
        return None
    accepted = prereg["candidate"]["accepted_response_model_ids"]
    evidence_error = (
        _validate_stream_evidence(result, accepted)
        if name == "streaming"
        else _validate_usage_evidence(result, accepted)
    )
    if evidence_error:
        return "MissingUsageEvidence", evidence_error
    if not requests:
        return (
            "MissingUsageEvidence",
            "successful case made no observed physical request",
        )
    if name != "streaming" and result["usage_evidence"].get("physical_calls") != len(
        requests
    ):
        return (
            "MissingUsageEvidence",
            "physical requests and usage telemetry do not match",
        )
    return None


async def structured(thinking=False, long=False):
    context = (
        "\n".join(
            f"Record {i}: unrelated buffer control observation." for i in range(2500)
        )
        if long
        else ""
    )
    prompt = (
        context
        + "\nClaim: Treatment X reduces cell viability.\nPassage: "
        + PASSAGE
        + "\nReturn JSON label and verbatim quote from Passage."
    )
    result = await call_llm_json(
        prompt,
        CompletionSpec(
            model_name=MODEL, max_tokens=6000, temperature=0, json_schema=SCHEMA
        ),
        max_attempts=1,
        options=LLMCallOptions(use_cache=False, enable_thinking=thinking),
    )
    return {
        "passed": result.get("label") == "supports"
        and bool(result.get("quote"))
        and result["quote"] in PASSAGE,
        "response": result,
        "prompt_characters": len(prompt),
        "thinking_requested": thinking,
        "max_tokens_requested": 6000,
    }


async def plain_json():
    result = await call_llm_json(
        "Claim: Treatment X reduces cell viability. Passage: "
        + PASSAGE
        + " Return a JSON object with label and a verbatim quote from the passage.",
        CompletionSpec(model_name=MODEL, max_tokens=6000, temperature=0),
        max_attempts=1,
        options=LLMCallOptions(use_cache=False, enable_thinking=False),
    )
    quote = result.get("quote")
    label = result.get("label")
    return {
        "passed": isinstance(label, str)
        and label.casefold() == "supports"
        and isinstance(quote, str)
        and quote in PASSAGE,
        "response": result,
    }


async def tools_case():
    invocations = []

    async def execute(call):
        name = call.function.name
        args = json.loads(call.function.arguments)
        invocations.append({"name": name, "arguments": args})
        if name != "lookup_measurement" or args != {"sample": "control-A"}:
            payload = {"error": "unknown measurement"}
        else:
            payload = {
                "sample": "control-A",
                "measurement": 137,
                "unit": "arbitrary units",
            }
        return {"role": "tool", "tool_call_id": call.id, "content": json.dumps(payload)}

    definition = {
        "type": "function",
        "function": {
            "name": "lookup_measurement",
            "description": "Read a public synthetic control measurement.",
            "parameters": {
                "type": "object",
                "properties": {"sample": {"type": "string"}},
                "required": ["sample"],
                "additionalProperties": False,
            },
        },
    }
    answer, _ = await call_llm_with_tools(
        "You must call lookup_measurement with sample control-A, then report its numeric measurement. Do not guess.",
        CompletionSpec(model_name=MODEL, max_tokens=6000, temperature=0),
        ToolLoop(tools=[definition], executor=execute, max_iterations=1),
        LLMCallOptions(use_cache=False, enable_thinking=False),
    )
    return {
        "passed": len(invocations) == 1
        and all(
            x["arguments"] == {"sample": "control-A"}
            and x["name"] == "lookup_measurement"
            for x in invocations
        )
        and "137" in answer,
        "invocations": invocations,
        "answer": answer,
    }


async def streaming():
    from app.llm_request import acompletion
    from app.llm_stream import stream_chunks
    from app.config import deepseek_thinking_kwargs, thinking_safe_max_tokens

    response = await acompletion(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": "State in one short sentence that a cell experiment alone does not prove clinical benefit.",
            }
        ],
        temperature=0.3,
        max_tokens=thinking_safe_max_tokens(MODEL, 6000),
        stream=True,
        stream_options={"include_usage": True},
        timeout=90,
        **deepseek_thinking_kwargs(MODEL),
    )
    parts = []
    models = set()
    finishes = []
    usage = []
    async for chunk in stream_chunks(response, stall_seconds=45, total_seconds=90):
        if getattr(chunk, "model", None):
            models.add(chunk.model)
        if getattr(chunk, "usage", None):
            usage.append(chunk.usage.model_dump())
        for choice in chunk.choices:
            if choice.finish_reason:
                finishes.append(choice.finish_reason)
            if getattr(choice.delta, "content", None):
                parts.append(choice.delta.content)
    return {
        "passed": bool(parts) and "stop" in finishes,
        "content_deltas": len(parts),
        "text": "".join(parts),
        "stream_model_fields": sorted(models),
        "finish_reasons": finishes,
        "reported_usage": usage,
        "model_identity_caveat": "SDK stream model fields; no independent provider receipt",
    }


async def main():
    global _ACTIVE_CASE, _PINNED_MODEL, _PINNED_REQUEST_CONTROLS
    global _CASE_CALL_CAPS, _GUARD_REJECTIONS
    cases = {
        "json_off": lambda: structured(),
        "json_on": lambda: structured(True),
        "plain_json": plain_json,
        "tools": tools_case,
        "streaming": streaming,
        "long_json": lambda: structured(False, True),
        "long_json_on": lambda: structured(True, True),
    }
    selected = _selected_cases()
    path = Path(os.environ["QUALIFICATION_OUTPUT"])
    prereg = _validate_bounded_prereg(selected, path) if _BOUNDED else None
    if prereg:
        _PINNED_MODEL = prereg["candidate"]["model"]
        _PINNED_REQUEST_CONTROLS = prereg["candidate"]["request_controls"]
        _CASE_CALL_CAPS = prereg["interface_stage"]["physical_call_caps_per_case"]
    report = {
        "requested_model": MODEL,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_commit": os.environ["QUALIFICATION_REVISION"],
        "probe_sha256": _digest(Path(__file__)),
        "cases": [],
    }
    if prereg:
        prereg_path = Path(os.environ["QUALIFICATION_PREREG"])
        if not prereg_path.is_absolute():
            prereg_path = _ROOT / prereg_path
        report["preregistration_sha256"] = _digest(prereg_path)
    with path.open("x") as artifact:
        for name in selected:
            _ACTIVE_CASE = name
            result = {"case": name}
            _REQUESTS.clear()
            _GUARD_REJECTIONS.clear()
            evidence = {}
            try:
                verify_model(MODEL.removeprefix("openrouter/"), current_catalog())
                with capture_usage(name, live=True) as evidence:
                    result.update(await asyncio.wait_for(cases[name](), timeout=100))
            except Exception as exc:
                result.update(
                    passed=False,
                    error_type=type(exc).__name__,
                    error=sanitize_error(exc),
                )
            result.update(evidence)
            result["physical_request_controls"] = list(_REQUESTS)
            if _GUARD_REJECTIONS:
                result["qualification_guard_rejections"] = list(_GUARD_REJECTIONS)
            if prereg:
                guard_error = _validate_bounded_case(name, result, prereg)
                if guard_error:
                    result.update(
                        passed=False,
                        error_type=guard_error[0],
                        error=guard_error[1],
                    )
            report["cases"].append(result)
            _write_artifact(artifact, report)
            print(name, result.get("passed"), result.get("error_type"), flush=True)
            if result.get("error_type") or (_BOUNDED and not result.get("passed")):
                break
    return (
        1
        if any(
            case.get("error_type") or (_BOUNDED and not case.get("passed"))
            for case in report["cases"]
        )
        else 0
    )


if __name__ == "__main__":
    try:
        status = asyncio.run(main())
    except Exception as exc:
        print(f"qualification preflight failed: {sanitize_error(exc)}", file=sys.stderr)
        status = 1
    sys.exit(status)

"""Bounded compatibility screen for the preregistered Groq Free route."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
PREREG = "references/external/baseline/model-qualification/groq-free-qualification-prereg-v1.json"
RUNNER = "references/external/baseline/model-qualification/probe_groq_free.py"
MODEL = "groq/openai/gpt-oss-120b"
API_BASE = "https://api.groq.com/openai/v1"
CASES = ("schema", "tools", "streaming", "long_prompt")
CAPS = {"schema": 1, "tools": 2, "streaming": 1, "long_prompt": 1}
TOTAL_CAP = 5
BUDGETS = {"schema": 768, "tools": 768, "streaming": 512, "long_prompt": 768}
TIMEOUT = 80
_ALLOWED = {
    "model",
    "messages",
    "max_tokens",
    "temperature",
    "drop_params",
    "timeout",
    "api_key",
    "api_base",
    "response_format",
    "tools",
    "tool_choice",
    "stream",
    "stream_options",
}
_REDACTIONS = (
    re.compile(r"(?i)gsk_[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"user_[A-Za-z0-9]+"),
)


class ProbeFailure(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sanitize(value: object) -> str:
    text = str(value)
    for pattern in _REDACTIONS:
        text = pattern.sub("[redacted]", text)
    return text[:1200]


def _head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _preflight() -> dict[str, Any]:
    output_value = os.environ.get("QUALIFICATION_OUTPUT", "")
    if not output_value:
        raise ProbeFailure("QUALIFICATION_OUTPUT is required")
    output = Path(output_value).expanduser().resolve()
    if output.exists():
        raise ProbeFailure("qualification output already exists")
    if not output.parent.is_dir():
        raise ProbeFailure("qualification output directory does not exist")

    prereg_value = os.environ.get("QUALIFICATION_PREREG", "")
    if not prereg_value:
        raise ProbeFailure("QUALIFICATION_PREREG is required")
    prereg_path = Path(prereg_value)
    if not prereg_path.is_absolute():
        prereg_path = ROOT / prereg_path
    if prereg_path.resolve() != (ROOT / PREREG).resolve():
        raise ProbeFailure("qualification protocol path is not the pinned file")
    expected_sha = os.environ.get("QUALIFICATION_PREREG_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ProbeFailure("QUALIFICATION_PREREG_SHA256 is invalid")
    raw = prereg_path.read_bytes()
    if _sha(raw) != expected_sha:
        raise ProbeFailure("protocol bytes differ from QUALIFICATION_PREREG_SHA256")
    protocol = json.loads(raw)
    candidate, interface = protocol.get("candidate", {}), protocol.get("interface", {})
    caps = interface.get("physical_call_caps", {})
    models = candidate.get("accepted_response_model_ids")
    if protocol.get("version") != 1:
        raise ProbeFailure("unsupported qualification protocol version")
    if candidate.get("model") != MODEL or os.environ.get("MODEL_NAME") != MODEL:
        raise ProbeFailure("MODEL_NAME differs from the preregistered Groq model")
    if candidate.get("api_base") != API_BASE:
        raise ProbeFailure("preregistered Groq API base differs")
    if (
        not isinstance(models, list)
        or MODEL not in models
        or not all(isinstance(m, str) for m in models)
    ):
        raise ProbeFailure("accepted response model ids are invalid")
    if (
        candidate.get("no_fallback") is not True
        or candidate.get("no_paid_tools") is not True
    ):
        raise ProbeFailure("protocol does not prohibit fallback and paid tools")
    if (
        interface.get("runner") != RUNNER
        or interface.get("cases_in_order") != list(CASES)
        or not isinstance(caps, dict)
        or set(caps) != set(CAPS)
        or any(type(n) is not int for n in caps.values())
        or caps != CAPS
        or type(interface.get("total_physical_call_cap")) is not int
        or interface["total_physical_call_cap"] != TOTAL_CAP
        or interface.get("max_completion_tokens_by_case") != BUDGETS
        or type(interface.get("long_prompt_characters")) is not int
        or interface["long_prompt_characters"] != 8000
    ):
        raise ProbeFailure("interface protocol differs from the bounded runner")

    hashes = protocol.get("source_hashes")
    if not isinstance(hashes, dict) or RUNNER not in hashes:
        raise ProbeFailure("protocol does not pin the probe and its source inputs")
    for relative, expected in hashes.items():
        source = (ROOT / relative).resolve()
        if (
            ROOT not in source.parents
            or not source.is_file()
            or _sha(source.read_bytes()) != expected
        ):
            raise ProbeFailure(f"pinned source hash differs: {relative}")
    revision = os.environ.get("QUALIFICATION_REVISION", "")
    if not revision or revision != _head():
        raise ProbeFailure("QUALIFICATION_REVISION differs from git HEAD")
    return {
        "output": output,
        "protocol": protocol,
        "prereg_sha256": expected_sha,
        "revision": revision,
        "accepted_models": models,
    }


def _load_interfaces() -> Any:
    import litellm
    from app import llm_request
    from app.llm_stream import stream_chunks
    from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
    from co_scientist.llm_tool_loop import ToolLoop, call_llm_with_tools

    return SimpleNamespace(
        litellm=litellm,
        app_completion=llm_request.acompletion,
        stream_chunks=stream_chunks,
        CompletionSpec=CompletionSpec,
        LLMCallOptions=LLMCallOptions,
        call_llm_json=call_llm_json,
        ToolLoop=ToolLoop,
        call_llm_with_tools=call_llm_with_tools,
    )


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    for name in ("model_dump", "dict", "to_dict"):
        method = getattr(obj, name, None)
        if callable(method):
            try:
                value = method()
            except Exception:
                continue
            if isinstance(value, dict):
                return value
    return {}


def _usage(obj: Any) -> dict[str, int] | None:
    raw = _dict(obj)
    prompt = raw.get("prompt_tokens", raw.get("input_tokens"))
    completion = raw.get("completion_tokens", raw.get("output_tokens"))
    total = raw.get("total_tokens")
    if type(prompt) is not int or type(completion) is not int:
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total if type(total) is int else None,
    }


def _is_429(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    return (
        status == 429
        or "ratelimit" in type(exc).__name__.lower()
        or bool(re.search(r"\b429\b", str(exc)))
    )


class _TransportGuard:
    def __init__(self, litellm: Any):
        self.litellm, self.original = litellm, litellm.acompletion
        self.case, self.calls, self.blocked, self.rate_limited = "", [], [], False
        if getattr(litellm, "model_fallbacks", None) or getattr(
            litellm, "model_alias_map", None
        ):
            raise ProbeFailure("LiteLLM fallback or alias routing is configured")
        self.old_retries = getattr(litellm, "num_retries", None)
        litellm.num_retries = 0
        litellm.acompletion = self.acompletion

    async def acompletion(self, **kwargs: Any) -> Any:
        reason = None
        if self.rate_limited:
            reason = "stopped after provider rate limit"
        elif kwargs.get("model") != MODEL or kwargs.get("api_base") != API_BASE:
            reason = "request route differs from preregistration"
        elif kwargs.keys() - _ALLOWED:
            reason = "request contains an unqualified option"
        elif "stream_options" in kwargs and (
            kwargs.get("stream") is not True
            or kwargs["stream_options"] != {"include_usage": True}
        ):
            reason = "request contains unqualified stream options"
        elif (
            self.case not in BUDGETS
            or type(kwargs.get("max_tokens")) is not int
            or kwargs["max_tokens"] != BUDGETS[self.case]
        ):
            reason = "request token limit is outside the probe bound"
        elif (
            len(self.calls) >= TOTAL_CAP
            or sum(c["case"] == self.case for c in self.calls) >= CAPS[self.case]
        ):
            reason = "physical call cap would be exceeded"
        if reason:
            self.blocked.append({"case": self.case, "reason": reason})
            raise ProbeFailure(reason)

        messages = kwargs.get("messages", [])
        call = {
            "case": self.case,
            "requested_model": MODEL,
            "api_base": API_BASE,
            "max_tokens": kwargs["max_tokens"],
            "stream": kwargs.get("stream", False),
            "prompt_characters": sum(
                len(m.get("content") or "") for m in messages if isinstance(m, dict)
            ),
            "tool_count": len(kwargs.get("tools", [])),
            "status": "started",
        }
        self.calls.append(call)
        try:
            response = await self.original(**kwargs)
        except Exception as exc:
            call.update(
                status="failed", error_type=type(exc).__name__, error=_sanitize(exc)
            )
            if _is_429(exc):
                call.update(status_code=429, rate_limited=True)
                self.rate_limited = True
            raise
        if not kwargs.get("stream"):
            self.observe(call, response)
            call["status"] = "completed"
        return response

    @staticmethod
    def observe(call: dict[str, Any], response: Any) -> None:
        model = _get(response, "model")
        if isinstance(model, str) and model:
            call.setdefault("served_models", []).append(model)
        usage = _usage(_get(response, "usage"))
        if usage:
            call.setdefault("usage", []).append(usage)

    def restore(self) -> None:
        self.litellm.acompletion = self.original
        if self.old_retries is not None:
            self.litellm.num_retries = self.old_retries


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
SCHEMA_PROMPT = (
    "Return JSON with label and a verbatim quote. Claim: Treatment X reduced cell viability. "
    "Passage: Treatment X reduced cell viability by 30% relative to vehicle."
)


async def _schema(api: Any) -> dict[str, Any]:
    result = await api.call_llm_json(
        SCHEMA_PROMPT,
        api.CompletionSpec(
            model_name=MODEL,
            max_tokens=BUDGETS["schema"],
            temperature=0,
            json_schema=SCHEMA,
        ),
        max_attempts=1,
        options=api.LLMCallOptions(use_cache=False, enable_thinking=False),
    )
    return {
        "passed": result.get("label") == "supports"
        and isinstance(result.get("quote"), str)
        and bool(result["quote"])
        and result["quote"] in SCHEMA_PROMPT,
        "response": result,
    }


async def _tools(api: Any) -> dict[str, Any]:
    invoked = []

    async def execute(call: Any) -> dict[str, Any]:
        name = _get(_get(call, "function"), "name")
        args = json.loads(_get(_get(call, "function"), "arguments"))
        invoked.append({"name": name, "arguments": args})
        value = {"sample": "control-A", "measurement": 137, "unit": "synthetic units"}
        payload = (
            value
            if name == "read_control" and args == {"sample": "control-A"}
            else {"error": "unknown synthetic control"}
        )
        return {
            "role": "tool",
            "tool_call_id": _get(call, "id"),
            "content": json.dumps(payload),
        }

    tool = {
        "type": "function",
        "function": {
            "name": "read_control",
            "description": "Read one synthetic public control measurement.",
            "parameters": {
                "type": "object",
                "properties": {"sample": {"type": "string"}},
                "required": ["sample"],
                "additionalProperties": False,
            },
        },
    }
    answer, _ = await api.call_llm_with_tools(
        "Call read_control exactly once for control-A, then report its measurement.",
        api.CompletionSpec(
            model_name=MODEL, max_tokens=BUDGETS["tools"], temperature=0
        ),
        api.ToolLoop(
            tools=[tool], executor=execute, max_iterations=2, max_prompt_tokens=4096
        ),
        api.LLMCallOptions(use_cache=False, enable_thinking=False),
    )
    return {
        "passed": len(invoked) == 1
        and invoked[0] == {"name": "read_control", "arguments": {"sample": "control-A"}}
        and "137" in answer,
        "local_tool_invocations": invoked,
        "answer": _sanitize(answer),
    }


async def _streaming(api: Any, guard: _TransportGuard) -> dict[str, Any]:
    response = await api.app_completion(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": "In one short sentence, say a cell experiment alone does not prove clinical benefit.",
            }
        ],
        max_tokens=BUDGETS["streaming"],
        temperature=0,
        stream=True,
        stream_options={"include_usage": True},
        timeout=TIMEOUT,
    )
    call = guard.calls[-1]
    parts, finishes = [], []
    try:
        async for chunk in api.stream_chunks(
            response, stall_seconds=35, total_seconds=TIMEOUT
        ):
            guard.observe(call, chunk)
            choices = _get(chunk, "choices") or []
            if choices:
                delta = _get(choices[0], "delta")
                text = _get(delta, "content")
                if isinstance(text, str):
                    parts.append(text)
                finish = _get(choices[0], "finish_reason")
                if finish:
                    finishes.append(str(finish))
    except Exception as exc:
        call.update(
            status="failed", error_type=type(exc).__name__, error=_sanitize(exc)
        )
        if _is_429(exc):
            call.update(status_code=429, rate_limited=True)
            guard.rate_limited = True
        raise
    call["status"] = "completed"
    text = "".join(parts)
    return {
        "passed": bool(text.strip()) and "stop" in finishes,
        "answer": _sanitize(text),
        "finish_reasons": finishes,
    }


def _long_prompt_text() -> str:
    ending = (
        "Claim: control-A measured 137 synthetic units. Passage: The final control-A reading was 137 synthetic units. "
        "Return JSON with label supports and a verbatim quote from the passage."
    )
    row = "Synthetic buffer record: unrelated measurement remains stable at 23 units.\n"
    return (row * ((8000 - len(ending)) // len(row) + 1))[: 8000 - len(ending)] + ending


async def _long_prompt(api: Any) -> dict[str, Any]:
    prompt = _long_prompt_text()
    result = await api.call_llm_json(
        prompt,
        api.CompletionSpec(
            model_name=MODEL,
            max_tokens=BUDGETS["long_prompt"],
            temperature=0,
            json_schema=SCHEMA,
        ),
        max_attempts=1,
        options=api.LLMCallOptions(use_cache=False, enable_thinking=False),
    )
    return {
        "passed": len(prompt) == 8000
        and result.get("label") == "supports"
        and result.get("quote")
        == "The final control-A reading was 137 synthetic units.",
        "prompt_characters": len(prompt),
        "response": result,
    }


async def _run_cases(
    api: Any, guard: _TransportGuard, context: dict[str, Any], report: dict[str, Any]
) -> bool:
    runners = {
        "schema": lambda: _schema(api),
        "tools": lambda: _tools(api),
        "streaming": lambda: _streaming(api, guard),
        "long_prompt": lambda: _long_prompt(api),
    }
    for name in CASES:
        guard.case = name
        before = len(guard.calls)
        entry = {"case": name}
        try:
            result = await asyncio.wait_for(runners[name](), timeout=TIMEOUT + 5)
            entry.update(result)
            count = len(guard.calls) - before
            if not result.get("passed"):
                raise ProbeFailure(
                    "case response did not meet its preregistered criterion"
                )
            if count != CAPS[name]:
                raise ProbeFailure(
                    f"case made {count} physical calls; expected {CAPS[name]}"
                )
            for call in guard.calls[before:]:
                if call.get("status") != "completed":
                    raise ProbeFailure("physical response did not complete")
                models = call.get("served_models", [])
                if not models or any(
                    model not in context["accepted_models"] for model in models
                ):
                    raise ProbeFailure(
                        "physical response is missing accepted served-model evidence"
                    )
                if not call.get("usage"):
                    raise ProbeFailure(
                        "physical response is missing reported token usage"
                    )
            entry["passed"] = True
        except Exception as exc:
            entry.update(
                passed=False, error_type=type(exc).__name__, error=_sanitize(exc)
            )
        entry["physical_call_indexes"] = list(range(before, len(guard.calls)))
        report["cases"].append(entry)
        report["physical_calls"] = guard.calls
        report["blocked_attempts"] = guard.blocked
        report["physical_call_count"] = len(guard.calls)
        report["status"] = (
            "failed" if not entry["passed"] or guard.rate_limited else "running"
        )
        _write(report, context["output"])
        if not entry["passed"] or guard.rate_limited:
            return False
    report["status"] = "passed"
    return True


def _write(report: dict[str, Any], output: Path) -> None:
    fd, tmp = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, output)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    try:
        context = _preflight()
    except Exception as exc:
        print(
            json.dumps({"error_type": type(exc).__name__, "error": _sanitize(exc)}),
            file=sys.stderr,
        )
        return 2
    output = context["output"]
    try:
        output.open("x").close()
    except FileExistsError:
        print(
            json.dumps({"error": "qualification output already exists"}),
            file=sys.stderr,
        )
        return 2

    report = {
        "requested_model": MODEL,
        "api_base": API_BASE,
        "source_commit": context["revision"],
        "prereg_sha256": context["prereg_sha256"],
        "runner_sha256": _sha(Path(__file__).read_bytes()),
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "zero_cost_admission": "Groq Free/ZDR attestation enforced by project request policy",
        "status": "running",
        "cases": [],
        "physical_calls": [],
        "physical_call_count": 0,
    }
    try:
        os.environ.update(
            PYTHON_DOTENV_DISABLED="1",
            COSCIENTIST_REQUIRE_FREE_MODELS="1",
            COSCIENTIST_LLM_TIMEOUT_SECONDS=str(TIMEOUT),
        )
        api = _load_interfaces()
        guard = _TransportGuard(api.litellm)
        try:
            report["passed"] = asyncio.run(_run_cases(api, guard, context, report))
        finally:
            guard.restore()
    except Exception as exc:
        report.update(
            passed=False,
            status="failed",
            error_type=type(exc).__name__,
            error=_sanitize(exc),
        )
        _write(report, output)
        print(
            json.dumps({"passed": False, "error_type": report["error_type"]}),
            flush=True,
        )
        return 1
    report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    report["status"] = "passed" if report["passed"] else "failed"
    _write(report, output)
    print(
        json.dumps(
            {
                "status": report["status"],
                "physical_call_count": report["physical_call_count"],
                "artifact": str(output),
            }
        ),
        flush=True,
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

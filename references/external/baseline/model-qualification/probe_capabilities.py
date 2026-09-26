"""Checkpointed live capability experiments; run with an isolated environment."""

import asyncio
import datetime
import hashlib
import json
import os
import re
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


async def observed_transport(**kwargs):
    global _TOTAL_REQUESTS
    if _BOUNDED:
        case_limit = 2 if _ACTIVE_CASE == "tools" else 1
        total_limit = int(os.getenv("QUALIFICATION_MAX_PHYSICAL_CALLS", "7"))
        if len(_REQUESTS) >= case_limit or _TOTAL_REQUESTS >= total_limit:
            raise RuntimeError("qualification physical-call cap reached")
    # Observe only non-secret controls after the real admission seam.
    _REQUESTS.append(
        {
            key: kwargs.get(key)
            for key in (
                "model",
                "max_tokens",
                "extra_body",
                "response_format",
                "stream",
            )
        }
    )
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
    global _ACTIVE_CASE
    report = {
        "requested_model": MODEL,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_commit": os.environ["QUALIFICATION_REVISION"],
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": [],
    }
    path = Path(os.environ["QUALIFICATION_OUTPUT"])
    cases = [
        ("json_off", lambda: structured()),
        ("json_on", lambda: structured(True)),
        ("plain_json", plain_json),
        ("tools", tools_case),
        ("streaming", streaming),
        ("long_json", lambda: structured(False, True)),
    ]
    selected = os.getenv("QUALIFICATION_CASES", "").split(",")
    if "long_json_on" in selected:
        cases.append(("long_json_on", lambda: structured(True, True)))
    for name, run in cases:
        if selected != [""] and name not in selected:
            continue
        _ACTIVE_CASE = name
        result = {"case": name}
        _REQUESTS.clear()
        evidence = {}
        try:
            verify_model(MODEL.removeprefix("openrouter/"), current_catalog())
            with capture_usage(name, live=True) as evidence:
                result.update(await asyncio.wait_for(run(), timeout=100))
        except Exception as exc:
            result.update(
                passed=False, error_type=type(exc).__name__, error=sanitize_error(exc)
            )
        result.update(evidence)
        result["physical_request_controls"] = list(_REQUESTS)
        report["cases"].append(result)
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(name, result["passed"], result.get("error_type"), flush=True)
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
    sys.exit(asyncio.run(main()))

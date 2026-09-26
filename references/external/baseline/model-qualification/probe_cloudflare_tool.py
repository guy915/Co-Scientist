"""Run one preregistered Cloudflare Workers AI tool round trip."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import litellm
import probe_cloudflare_json as cloudflare_json

from co_scientist import llm_call_budget, llm_free_policy
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm_with_tools,
)

MODEL = "openai/@cf/google/gemma-4-26b-a4b-it"
SERVED_MODEL = "@cf/google/gemma-4-26b-a4b-it"
MAX_TOKENS = 1024
MAX_TOOL_ITERATIONS = 1
MAX_PROMPT_TOKENS = 4096
PHYSICAL_CALL_CAP = 2
SDK_MAX_RETRIES = 0
SDK_NUM_RETRIES = 0
LITELLM_VERSION = version("litellm")
TIMEOUT_SECONDS = 90
TOOL_NAME = "lookup_public_measurement"
TOOL_ARGUMENTS = {"sample_id": "control-A"}
TOOL_RESULT = {
    "sample_id": "control-A",
    "measurement": 137,
    "unit": "arbitrary units",
}
PROMPT = (
    "Use lookup_public_measurement with sample_id control-A. The tool is the "
    "only source of the measurement. After it returns, report the value and "
    "unit with this exact sentence: 'The control-A measurement was 137 "
    "arbitrary units.' Do not guess or alter its value."
)
EXPECTED_ANSWER = "The control-A measurement was 137 arbitrary units."
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Read a fixed public synthetic control measurement.",
        "parameters": {
            "type": "object",
            "properties": {"sample_id": {"type": "string", "enum": ["control-A"]}},
            "required": ["sample_id"],
            "additionalProperties": False,
        },
    },
}
PASS_CRITERION = (
    "Exactly one tool invocation uses lookup_public_measurement with "
    "sample_id=control-A; the tool result is 137 arbitrary units; the final "
    f"answer exactly matches: {EXPECTED_ANSWER!r}."
)
SOURCE_MODULES = (
    "co_scientist.cache",
    "co_scientist.llm",
    "co_scientist.llm_call",
    "co_scientist.llm_call_budget",
    "co_scientist.llm_credentials",
    "co_scientist.llm_free_policy",
    "co_scientist.llm_request",
    "co_scientist.llm_request_schema",
    "co_scientist.llm_response",
    "co_scientist.llm_telemetry",
    "co_scientist.llm_thinking",
    "co_scientist.llm_tool_iteration",
    "co_scientist.llm_tool_loop",
    "co_scientist.llm_tool_loop_run",
    "co_scientist.llm_tool_policy",
    "co_scientist.llm_tool_transcript",
    "co_scientist.llm_types",
)
ROOT = Path(__file__).resolve().parents[4]


class QualificationGuardError(RuntimeError):
    """A request or response violated the frozen qualification protocol."""


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def head_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _source_paths() -> dict[str, Path]:
    names = {
        name: Path(importlib.import_module(name).__file__).resolve()
        for name in SOURCE_MODULES
    }
    paths = {
        "engine/pyproject.toml": ROOT / "engine/pyproject.toml",
        "app/pyproject.toml": ROOT / "app/pyproject.toml",
        "references/external/baseline/model-qualification/probe_cloudflare_tool.py": Path(
            __file__
        ).resolve(),
        "references/external/baseline/model-qualification/probe_cloudflare_json.py": Path(
            cloudflare_json.__file__
        ).resolve(),
    }
    paths.update({str(path.relative_to(ROOT)): path for path in names.values()})
    return paths


def source_hashes() -> dict[str, str]:
    paths = _source_paths()
    hashes: dict[str, str] = {}
    for relative, path in sorted(paths.items()):
        if not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError(
                f"pinned source is missing or outside the repository: {relative}"
            )
        hashes[relative] = sha256(path.read_bytes())
    return hashes


def _dirty_source_paths(paths: dict[str, Path]) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *sorted(paths),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("could not verify pinned source working-tree state")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _commit_source_hashes(source_commit: str, paths: dict[str, Path]) -> dict[str, str]:
    try:
        return {
            relative: sha256(
                subprocess.check_output(
                    ["git", "show", f"{source_commit}:{relative}"],
                    cwd=ROOT,
                    stderr=subprocess.DEVNULL,
                )
            )
            for relative in sorted(paths)
        }
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            "preregistration source commit is missing a pinned source blob"
        ) from exc


def _verified_source_hashes(source_commit: str) -> dict[str, str]:
    paths = _source_paths()
    dirty = _dirty_source_paths(paths)
    if dirty:
        raise ValueError(
            "pinned behavior-bearing source files have dirty or uncommitted changes"
        )
    working_hashes = source_hashes()
    if _commit_source_hashes(source_commit, paths) != working_hashes:
        raise ValueError(
            "pinned source file hashes do not match the frozen source commit"
        )
    return working_hashes


def input_hashes() -> dict[str, str]:
    return {
        "prompt_sha256": sha256(PROMPT.encode("utf-8")),
        "tool_schema_sha256": sha256(canonical_json(TOOL_SCHEMA)),
        "tool_result_sha256": sha256(canonical_json(TOOL_RESULT)),
    }


def request_config() -> dict[str, Any]:
    return {
        "model": MODEL,
        "accepted_served_models": [MODEL, SERVED_MODEL],
        "max_tokens": MAX_TOKENS,
        "max_tool_iterations": MAX_TOOL_ITERATIONS,
        "max_prompt_tokens": MAX_PROMPT_TOKENS,
        "physical_call_cap": PHYSICAL_CALL_CAP,
        "sdk_max_retries": SDK_MAX_RETRIES,
        "sdk_num_retries": SDK_NUM_RETRIES,
        "litellm_version": LITELLM_VERSION,
        "timeout_seconds": TIMEOUT_SECONDS,
        "cache_enabled": False,
        "thinking_policy": "engine tool-loop default, pinned by source hashes",
        "campaign_mode": True,
        "reject_if_busy": True,
        "drop_params": False,
        "fallbacks_allowed": False,
        "aliases_allowed": False,
        "pass_criterion": PASS_CRITERION,
    }


def expected_prereg(
    account_id_sha256: str | None = None, *, source_commit: str | None = None
) -> dict[str, Any]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    if account_id_sha256 is None:
        if re.fullmatch(r"[a-fA-F0-9]{32}", account_id) is None:
            raise ValueError(
                "a valid Cloudflare account ID is required to freeze this preregistration"
            )
        account_id_sha256 = sha256(account_id.encode("ascii"))
    config = request_config()
    inputs = input_hashes()
    frozen_source_commit = source_commit or head_revision()
    return {
        "version": 1,
        "status": "frozen",
        "protocol": "M11-OPS-02c3 Cloudflare bounded tool round trip",
        "eligibility_checked_utc_date": dt.datetime.now(dt.timezone.utc)
        .date()
        .isoformat(),
        "candidate": {
            "model": MODEL,
            "accepted_served_models": [MODEL, SERVED_MODEL],
            "account_id_sha256": account_id_sha256,
            "endpoint_template": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
            "plan_attestation": "{utc_date}:{account_id}:workers-free",
        },
        "request_config": config,
        "request_config_sha256": sha256(canonical_json(config)),
        "fixed_input_sha256": inputs,
        "source_commit": frozen_source_commit,
        "source_sha256": _verified_source_hashes(frozen_source_commit),
        "zero_spend_basis": (
            "Current-day operator attestation of Workers Free; Cloudflare's "
            "daily free Neurons ceiling is a hard-fail boundary. No remaining-"
            "Neurons meter is asserted; stop on busy, quota, or ambiguous errors."
        ),
        "stop_rule": (
            "One tool round trip only, at most two physical requests, no SDK "
            "max_retries or num_retries, and no fallback. Stop on the first error, wrong tool call, wrong "
            "served model, missing usage, or failed answer criterion."
        ),
        "scope_limit": (
            "Public synthetic tool compatibility only; this does not qualify "
            "streaming, long-context/output, scientific quality, zero retention, "
            "full-run quota, or a production default."
        ),
    }


_safe = cloudflare_json._safe
_get = cloudflare_json._get
_usage = cloudflare_json._usage
_served_model_matches = cloudflare_json._serve_model_matches


def _load_prereg(account: str) -> tuple[dict[str, Any], str]:
    path_value = os.getenv("QUALIFICATION_PREREG", "")
    if not path_value:
        raise ValueError("QUALIFICATION_PREREG is required")
    raw = Path(path_value).read_bytes()
    digest = sha256(raw)
    if os.getenv("QUALIFICATION_PREREG_SHA256") != digest:
        raise ValueError(
            "qualification preregistration digest is missing or mismatched"
        )
    prereg = json.loads(raw)
    if not isinstance(prereg, dict):
        raise ValueError("qualification preregistration must be a JSON object")
    source_commit = prereg.get("source_commit")
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or not _is_ancestor(source_commit)
    ):
        raise ValueError(
            "preregistration source commit is not an ancestor of this checkout"
        )
    expected = expected_prereg(
        sha256(account.encode("ascii")), source_commit=source_commit
    )
    if prereg != expected:
        raise ValueError(
            "qualification preregistration differs from current source, account, or inputs"
        )
    return prereg, digest


def _is_ancestor(source_commit: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _matches_tool_call(call: Any) -> bool:
    function = _get(call, "function")
    try:
        arguments = json.loads(_get(function, "arguments"))
    except (TypeError, json.JSONDecodeError):
        return False
    return _get(function, "name") == TOOL_NAME and arguments == TOOL_ARGUMENTS


def _write_artifact(stream, record: dict[str, Any]) -> None:
    stream.seek(0)
    stream.truncate()
    stream.write(json.dumps(_safe(record), indent=2, sort_keys=True) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def main() -> int:
    output = Path(os.environ["QUALIFICATION_OUTPUT"])
    record: dict[str, Any] = {
        "requested_model": MODEL,
        "request_config_sha256": sha256(canonical_json(request_config())),
        "fixed_input_sha256": input_hashes(),
        "pass_criterion": PASS_CRITERION,
        "physical_call_cap": PHYSICAL_CALL_CAP,
        "sdk_max_retries": SDK_MAX_RETRIES,
        "sdk_num_retries": SDK_NUM_RETRIES,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "passed": False,
        "physical_request_count": 0,
        "request_observations": [],
        "tool_invocations": [],
    }
    with output.open("x", encoding="utf-8") as artifact:
        _write_artifact(artifact, record)
        original = litellm.acompletion
        try:
            today = cloudflare_json._attestation_date()
            account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
            prereg, prereg_digest = _load_prereg(account)
            if prereg["eligibility_checked_utc_date"] != today:
                raise ValueError("Cloudflare Workers Free preregistration is stale")
            if litellm.model_fallbacks or litellm.model_alias_map:
                raise ValueError(
                    "Cloudflare tool qualification forbids SDK fallbacks and aliases"
                )
            record.update(
                preregistration_sha256=prereg_digest,
                source_commit=prereg["source_commit"],
                execution_commit=head_revision(),
                attestation_date=today,
                account_id_sha256=prereg["candidate"]["account_id_sha256"],
                python_version=sys.version.split()[0],
                litellm_version=LITELLM_VERSION,
            )
            os.environ["PYTHON_DOTENV_DISABLED"] = "1"
            os.environ["COSCIENTIST_REQUIRE_FREE_MODELS"] = "1"
            os.environ["COSCIENTIST_LLM_TIMEOUT_SECONDS"] = str(TIMEOUT_SECONDS)
            roundtrip_state = "start"

            async def observed_transport(**kwargs):
                nonlocal roundtrip_state
                item = {
                    "requested_model": str(kwargs.get("model", "")),
                    "api_base": kwargs.get("api_base"),
                    "request_sha256": sha256(
                        canonical_json(kwargs.get("messages", []))
                    ),
                    "tool_count": len(kwargs.get("tools") or []),
                    "max_tokens": kwargs.get("max_tokens"),
                    "max_retries": kwargs.get("max_retries"),
                    "num_retries": kwargs.get("num_retries"),
                    "drop_params": kwargs.get("drop_params"),
                    "temperature": kwargs.get("temperature"),
                    "timeout": kwargs.get("timeout"),
                    "rejectIfBusy": (
                        kwargs.get("extra_body", {})
                        .get("options", {})
                        .get("rejectIfBusy")
                        if isinstance(kwargs.get("extra_body"), dict)
                        else None
                    ),
                    "dispatched": False,
                }
                record["request_observations"].append(item)
                request_number = record["physical_request_count"]
                if request_number == 0 and roundtrip_state != "start":
                    item["error"] = (
                        "first-error stop rejected an additional provider request"
                    )
                    _write_artifact(artifact, record)
                    raise QualificationGuardError(item["error"])
                if request_number == 1 and roundtrip_state != "tool_completed":
                    item["error"] = (
                        "only the expected tool result may authorize the second request"
                    )
                    _write_artifact(artifact, record)
                    raise QualificationGuardError(item["error"])
                expected_base = (
                    f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1"
                )
                actual_tools = kwargs.get("tools")
                tool_shape_matches = (
                    actual_tools == [TOOL_SCHEMA]
                    if request_number == 0
                    else not actual_tools
                )
                if (
                    kwargs.get("model") != MODEL
                    or kwargs.get("api_base") != expected_base
                    or kwargs.get("max_tokens") != MAX_TOKENS
                    or not tool_shape_matches
                    or kwargs.get("max_retries") not in (None, SDK_MAX_RETRIES)
                    or kwargs.get("num_retries") not in (None, SDK_NUM_RETRIES)
                    or kwargs.get("drop_params") is not False
                    or kwargs.get("temperature") != 0
                    or kwargs.get("timeout") != TIMEOUT_SECONDS
                    or item["rejectIfBusy"] is not True
                ):
                    roundtrip_state = "failed"
                    item["error"] = (
                        "physical request differed from the frozen Cloudflare route"
                    )
                    _write_artifact(artifact, record)
                    raise QualificationGuardError(
                        "physical request differed from the frozen Cloudflare route"
                    )
                if request_number >= PHYSICAL_CALL_CAP:
                    roundtrip_state = "failed"
                    item["error"] = (
                        "Cloudflare tool case exceeded its two-request physical cap"
                    )
                    _write_artifact(artifact, record)
                    raise QualificationGuardError(
                        "Cloudflare tool case exceeded its two-request physical cap"
                    )
                body = kwargs.get("extra_body", {})
                if not isinstance(body, dict) or body.keys() - {"options"}:
                    roundtrip_state = "failed"
                    item["error"] = "physical request added unpinned provider options"
                    _write_artifact(artifact, record)
                    raise QualificationGuardError(
                        "physical request added unpinned provider options"
                    )
                # LiteLLM consumes `num_retries` in its async wrapper, while
                # `max_retries` controls the provider client's own retry loop.
                kwargs["max_retries"] = SDK_MAX_RETRIES
                kwargs["num_retries"] = SDK_NUM_RETRIES
                item["max_retries"] = SDK_MAX_RETRIES
                item["num_retries"] = SDK_NUM_RETRIES
                item["dispatched"] = True
                record["physical_request_count"] += 1
                _write_artifact(artifact, record)
                try:
                    response = await original(**kwargs)
                except Exception as exc:
                    roundtrip_state = "failed"
                    item["error_type"] = type(exc).__name__
                    item["error"] = _safe(str(exc))
                    _write_artifact(artifact, record)
                    raise
                served_model = _get(response, "model")
                usage = _usage(response)
                if isinstance(usage, dict) and any(
                    not isinstance(usage.get(key), int)
                    or isinstance(usage[key], bool)
                    or usage[key] <= 0
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                ):
                    usage = None
                choice = (
                    response.choices[0] if getattr(response, "choices", None) else None
                )
                message = _get(choice, "message")
                item.update(
                    served_model=served_model
                    if isinstance(served_model, str)
                    else None,
                    usage=usage,
                    finish_reason=_get(choice, "finish_reason"),
                )
                if not _served_model_matches(served_model) or usage is None:
                    roundtrip_state = "failed"
                    item["error_type"] = "QualificationGuardError"
                    item["error"] = (
                        "provider response did not include the pinned model and positive token usage"
                    )
                    _write_artifact(artifact, record)
                    raise QualificationGuardError(item["error"])
                if request_number == 0:
                    tool_calls = _get(message, "tool_calls") or []
                    if (
                        len(tool_calls) != 1
                        or _get(choice, "finish_reason") != "tool_calls"
                        or not _matches_tool_call(tool_calls[0])
                    ):
                        roundtrip_state = "failed"
                        item["error_type"] = "QualificationGuardError"
                        item["error"] = (
                            "first response did not request the exact preregistered tool"
                        )
                        _write_artifact(artifact, record)
                        raise QualificationGuardError(item["error"])
                    roundtrip_state = "awaiting_tool"
                else:
                    answer = _get(message, "content")
                    if (
                        _get(message, "tool_calls")
                        or answer != EXPECTED_ANSWER
                        or _get(choice, "finish_reason") != "stop"
                    ):
                        roundtrip_state = "failed"
                        item["error_type"] = "QualificationGuardError"
                        item["error"] = (
                            "second response did not meet the fixed answer criterion"
                        )
                        _write_artifact(artifact, record)
                        raise QualificationGuardError(item["error"])
                    roundtrip_state = "complete"
                _write_artifact(artifact, record)
                return response

            litellm.acompletion = observed_transport

            async def execute(call):
                nonlocal roundtrip_state
                function = _get(call, "function")
                name = _get(function, "name")
                raw_arguments = _get(function, "arguments")
                try:
                    arguments = json.loads(raw_arguments)
                except (TypeError, json.JSONDecodeError) as exc:
                    roundtrip_state = "failed"
                    raise QualificationGuardError(
                        "tool arguments were not valid JSON"
                    ) from exc
                invocation = {"name": name, "arguments": arguments}
                record["tool_invocations"].append(invocation)
                _write_artifact(artifact, record)
                if invocation != {"name": TOOL_NAME, "arguments": TOOL_ARGUMENTS}:
                    roundtrip_state = "failed"
                    raise QualificationGuardError(
                        "model requested an unexpected tool or arguments"
                    )
                if roundtrip_state != "awaiting_tool":
                    roundtrip_state = "failed"
                    raise QualificationGuardError(
                        "tool execution occurred outside the pinned round trip"
                    )
                roundtrip_state = "tool_completed"
                return {
                    "role": "tool",
                    "tool_call_id": _get(call, "id"),
                    "content": json.dumps(TOOL_RESULT, sort_keys=True),
                }

            with llm_free_policy.scoped_campaign_mode(True):
                with llm_call_budget.scoped_llm_call_budget(
                    f"cloudflare-c3-tool:{output.resolve()}", PHYSICAL_CALL_CAP
                ):
                    answer, _history = asyncio.run(
                        asyncio.wait_for(
                            call_llm_with_tools(
                                PROMPT,
                                CompletionSpec(
                                    MODEL, max_tokens=MAX_TOKENS, temperature=0
                                ),
                                ToolLoop(
                                    tools=[TOOL_SCHEMA],
                                    executor=execute,
                                    max_iterations=MAX_TOOL_ITERATIONS,
                                    max_prompt_tokens=MAX_PROMPT_TOKENS,
                                ),
                                LLMCallOptions(use_cache=False),
                            ),
                            timeout=TIMEOUT_SECONDS,
                        )
                    )
            record["answer"] = answer
            if (
                record["tool_invocations"]
                != [{"name": TOOL_NAME, "arguments": TOOL_ARGUMENTS}]
                or answer != EXPECTED_ANSWER
                or record["physical_request_count"] != PHYSICAL_CALL_CAP
            ):
                raise ValueError("completed tool round trip failed the fixed criterion")
            record["passed"] = True
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            record["error"] = _safe(str(exc))
        finally:
            litellm.acompletion = original
            record["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            _write_artifact(artifact, record)
    print(
        json.dumps(
            {
                "requested_model": MODEL,
                "passed": record["passed"],
                "physical_request_count": record["physical_request_count"],
                "error_type": record.get("error_type"),
                "artifact": str(output),
            }
        ),
        flush=True,
    )
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

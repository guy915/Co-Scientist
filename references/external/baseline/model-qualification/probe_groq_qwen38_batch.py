"""One public Groq Qwen3.8 27B assay through the product batch assessor.

This adapts the bounded one-call assay in c7d2cbac. The preregistration stays
draft until the source revision and current Free/ZDR admission are reviewed.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import litellm

from app import claim_verifier_batch, claims_batch
from app.claim_verifier_batch import _BATCH_DRAFT_SCHEMA, make_llm_batch_assessor
from app.claims import EvidencePassage, assess_claims_batch
from co_scientist import llm_free_policy
from co_scientist.cache import scoped_cache_override
from co_scientist.llm_call_budget import current_run_call_count, scoped_llm_call_budget

FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parents[3]
PROTOCOL_PATH = FOLDER / "groq-qwen38-scientific-prereg-v1.json"
PROTOCOL_RELATIVE = "references/external/baseline/model-qualification/groq-qwen38-scientific-prereg-v1.json"
PREFLIGHT_PATH = FOLDER / "batch-schema-preflight109.json"
PREFLIGHT_RELATIVE = str(PREFLIGHT_PATH.relative_to(ROOT))
MODEL = "groq/qwen/qwen3.8-27b"
API_BASE = "https://api.groq.com/openai/v1"
SERVED_MODELS = ("qwen/qwen3.8-27b",)
IDS = (
    "same_scope_part_of_result",
    "matching_scope_full_support",
    "changed_population",
    "matching_scope_contradiction",
)
LABELS = ("partial", "supports", "insufficient", "contradicts")
METHODS = ("model_primary", "model_primary", "model_primary", "lexical_founded")
CONTRADICTION_ANCHOR = (
    "Treatment S did not increase migration of adult human fibroblasts after 24 hours"
)
MAX_ATTEMPTS, SDK_RETRIES, CALL_CAP, MAX_TOKENS = 1, 0, 1, 12000
SOURCE_PATHS = (
    "references/external/baseline/model-qualification/probe_groq_qwen38_batch.py",
    "references/external/baseline/model-qualification/batch-schema-preflight109.json",
    "references/external/baseline/model-qualification/partial-support-scope-controls.json",
    "app/app/claim_verifier_batch.py",
    "app/app/claims_batch.py",
    "app/app/claim_verifier_opposition.py",
    "app/app/claims_span.py",
    "app/app/credentials.py",
    "engine/src/co_scientist/cache.py",
    "engine/src/co_scientist/llm.py",
    "engine/src/co_scientist/llm_call.py",
    "engine/src/co_scientist/llm_call_budget.py",
    "engine/src/co_scientist/llm_json_retry.py",
    "engine/src/co_scientist/llm_request.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    value = json.loads(json.dumps(value, default=str))
    if isinstance(value, str):
        for name in (
            "GROQ_API_KEY",
            "OPENAI_API_KEY",
        ):
            if secret := os.getenv(name):
                value = value.replace(secret, "[redacted]")
        value = re.sub(
            r"\buser_[A-Za-z0-9]+\b|\bgsk_[A-Za-z0-9_-]+\b", "[redacted]", value
        )
        return re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+", r"\1[redacted]", value)[
            :4000
        ]
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    return value


def _verify_clean_worktree(output: Path) -> None:
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
        cwd=ROOT,
    )
    allowed = set()
    resolved_output = output.resolve()
    if resolved_output.is_relative_to(ROOT):
        relative = resolved_output.relative_to(ROOT).as_posix()
        allowed.add(f"?? {relative}".encode() + b"\0")
    if any(entry + b"\0" not in allowed for entry in status.split(b"\0") if entry):
        raise ValueError("qualification checkout is not clean")


def _load_protocol() -> dict[str, Any]:
    raw = PROTOCOL_PATH.read_bytes()
    protocol = json.loads(raw)
    if os.getenv("QUALIFICATION_PREREG_SHA256") != hashlib.sha256(raw).hexdigest():
        raise ValueError(
            "qualification preregistration digest is missing or mismatched"
        )
    if protocol.get("status") != "frozen":
        raise ValueError("qualification preregistration is not frozen")
    candidate, request, science = (
        protocol.get("candidate", {}),
        protocol.get("request", {}),
        protocol.get("scientific_trial", {}),
    )
    expected = (
        candidate.get("model") == MODEL,
        candidate.get("api_base") == API_BASE,
        candidate.get("accepted_response_model_ids") == list(SERVED_MODELS),
        candidate.get("no_fallback") is True,
        candidate.get("no_paid_tools") is True,
        [
            request.get(k)
            for k in ("max_attempts", "sdk_retries", "physical_call_cap", "max_tokens")
        ]
        == [1, 0, 1, MAX_TOKENS],
        request.get("cache_enabled") is False,
        request.get("temperature") == 0,
        request.get("first_error_stop") is True,
        request.get("fallback_or_alias_routing") is False,
        science.get("input_manifest") == PREFLIGHT_RELATIVE,
        science.get("boundary")
        == "app.claim_verifier_batch.make_llm_batch_assessor via app.claims.assess_claims_batch",
        science.get("trial_count") == 1,
        science.get("expected_ids") == list(IDS),
        science.get("expected_labels") == list(LABELS),
        science.get("expected_verification_methods") == list(METHODS),
        science.get("physical_call_cap") == CALL_CAP,
    )
    if not all(expected):
        raise ValueError("qualification route or assay differs from preregistration")
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    source_commit = protocol.get("source_commit_before_probe")
    if (
        not isinstance(source_commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
        or os.getenv("QUALIFICATION_REVISION") != source_commit
        or subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_commit, head],
            cwd=ROOT,
            check=False,
            capture_output=True,
        ).returncode
        != 0
    ):
        raise ValueError(
            "qualification source revision differs from frozen preregistration"
        )
    changed_paths = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            "--no-renames",
            f"{source_commit}..{head}",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    unexpected_paths = sorted(set(changed_paths) - {"PLAN.md", PROTOCOL_RELATIVE})
    if unexpected_paths:
        raise ValueError(
            "committed files changed after qualification source revision: "
            + ", ".join(unexpected_paths)
        )
    hashes = protocol.get("source_hashes", {})
    if not isinstance(hashes, dict) or set(hashes) != set(SOURCE_PATHS):
        raise ValueError("qualification source hashes are incomplete")
    actual = {}
    for relative in SOURCE_PATHS:
        path = (ROOT / relative).resolve(strict=True)
        actual[relative] = digest(path)
        if not path.is_relative_to(ROOT) or actual[relative] != hashes[relative]:
            raise ValueError(f"qualification source hash differs: {relative}")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_commit": source_commit,
        "execution_commit": head,
        "source_hashes": actual,
    }


def load_frozen_panel() -> tuple[dict[str, Any], dict[str, Any]]:
    preflight = json.loads(PREFLIGHT_PATH.read_text())
    source_path = FOLDER / preflight["source_dataset"]
    if digest(source_path) != preflight["source_sha256"]:
        raise ValueError("public four-claim dataset differs from its frozen manifest")
    schema_hash = hashlib.sha256(
        json.dumps(_BATCH_DRAFT_SCHEMA, sort_keys=True).encode()
    ).hexdigest()
    if schema_hash != preflight["schema_sha256"]:
        raise ValueError("batch assessor schema differs from frozen manifest")
    source = json.loads(source_path.read_text())
    by_id = {item["id"]: item for item in source["items"]}
    if (
        len(by_id) != len(source["items"])
        or preflight.get("selected_ids") != list(IDS)
        or preflight.get("expected_labels") != list(LABELS)
    ):
        raise ValueError("public four-claim panel or expected labels changed")
    items = [by_id[item_id] for item_id in IDS]
    if any(len(item.get("passages", [])) != 1 for item in items):
        raise ValueError("public assay passage set changed")
    return {"items": items}, preflight


def _attested_today() -> str:
    key = os.getenv("GROQ_API_KEY", "")
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    expected = f"{today}:{hashlib.sha256(key.encode()).hexdigest()}" if key else ""
    if not expected or os.getenv("COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION") != expected:
        raise ValueError("current Groq Free/ZDR attestation is missing or stale")
    return today


def run_batch(
    dataset: dict[str, Any], assessor: Any, assessor_id: str, record: dict[str, Any]
) -> dict[str, Any]:
    items = dataset["items"]
    claims = [item["claim"] for item in items]
    passages = [
        EvidencePassage(item["id"], item["passages"][0], source="public_control")
        for item in items
    ]

    def observed(claim_batch, passage_batch):
        record["batch_invocations"].append(
            {"claims": len(claim_batch), "passages": len(passage_batch)}
        )
        return assessor(claim_batch, passage_batch)

    results = assess_claims_batch(
        claims, passages, batch_assessor=observed, assessor_id=assessor_id
    )
    return {
        "checks": [
            {
                "id": item["id"],
                "label": result.label.value,
                "verification_method": result.verification_method,
                "supporting_spans": [
                    span.to_dict() for span in result.supporting_passages
                ],
                "contradicting_spans": [
                    span.to_dict() for span in result.contradicting_passages
                ],
            }
            for item, result in zip(items, results)
        ]
    }


def _usage(value: Any) -> dict[str, Any] | None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return (
        {
            key: value.get(key)
            if isinstance(value, dict)
            else getattr(value, key, None)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        if value is not None
        else None
    )


def _observe_transport(record: dict[str, Any]):
    original = litellm.acompletion

    async def observed(**kwargs):
        row = {
            "requested_model": kwargs.get("model"),
            "api_base": kwargs.get("api_base"),
            "max_tokens": kwargs.get("max_tokens"),
            "temperature": kwargs.get("temperature"),
            "max_retries": SDK_RETRIES,
            "prompt_sha256": hashlib.sha256(
                json.dumps(kwargs.get("messages"), sort_keys=True).encode()
            ).hexdigest(),
            "transport_invoked": False,
        }
        record["physical_attempts"].append(row)
        if (
            len(record["physical_attempts"]) > CALL_CAP
            or row["requested_model"] != MODEL
            or row["api_base"] != API_BASE
        ):
            row["blocked_before_transport"] = True
            raise RuntimeError("one-call guard rejected an unpinned Groq request")
        row["transport_invoked"] = True
        kwargs["max_retries"] = SDK_RETRIES
        try:
            response = await original(**kwargs)
        except Exception as exc:
            row.update(error_type=type(exc).__name__, error=_safe(str(exc)))
            raise
        choice = response.choices[0] if getattr(response, "choices", None) else None
        row.update(
            response_model=getattr(response, "model", None),
            usage=_usage(getattr(response, "usage", None)),
            finish_reason=getattr(choice, "finish_reason", None),
            provider_content=_safe(
                getattr(getattr(choice, "message", None), "content", None)
            ),
        )
        return response

    return original, observed


@contextlib.contextmanager
def _one_attempt(record: dict[str, Any]):
    original = claim_verifier_batch.call_llm_json

    async def once(*args, **kwargs):
        response = await original(*args, **(kwargs | {"max_attempts": MAX_ATTEMPTS}))
        record["raw_verdicts"] = response.get("verdicts")
        return response

    claim_verifier_batch.call_llm_json = once
    try:
        yield
    finally:
        claim_verifier_batch.call_llm_json = original


@contextlib.contextmanager
def _no_fallbacks(record: dict[str, Any]):
    original_call, original_fallback = (
        claim_verifier_batch._call_llm_batch_entailment,
        claims_batch._fallback_assessment,
    )

    def primary(*args, **kwargs):
        result = original_call(*args, **kwargs)
        if result is None:
            raise RuntimeError(
                "primary assessor failed; deterministic fallback blocked"
            )
        return result

    def fallback(*args, **kwargs):
        record["fallback_blocked"] = True
        raise RuntimeError("deterministic fallback blocked by one-call assay")

    (
        claim_verifier_batch._call_llm_batch_entailment,
        claims_batch._fallback_assessment,
    ) = primary, fallback
    try:
        yield
    finally:
        (
            claim_verifier_batch._call_llm_batch_entailment,
            claims_batch._fallback_assessment,
        ) = original_call, original_fallback


@contextlib.contextmanager
def _no_sdk_retries():
    missing = object()
    before = {
        name: getattr(litellm, name, missing) for name in ("num_retries", "max_retries")
    }
    litellm.num_retries = litellm.max_retries = SDK_RETRIES
    try:
        yield
    finally:
        for name, value in before.items():
            if value is missing:
                delattr(litellm, name)
            else:
                setattr(litellm, name, value)


def _check_result(dataset: dict[str, Any], record: dict[str, Any]) -> list[str]:
    failures = []
    attempts, checks = (
        record.get("physical_attempts", []),
        (record.get("report") or {}).get("checks", []),
    )
    if record.get("batch_invocations") != [{"claims": 4, "passages": 4}]:
        failures.append("all claims were not judged together in one batch")
    if record.get("logical_call_count") != 1 or record.get("fallback_blocked"):
        failures.append("assessor attempted a retry, fallback, or second verification")
    if len(attempts) != 1 or not attempts[0].get("transport_invoked"):
        failures.append("trial did not make exactly one physical provider call")
    else:
        attempt = attempts[0]
        if (
            attempt.get("requested_model"),
            attempt.get("api_base"),
            attempt.get("max_tokens"),
            attempt.get("temperature"),
        ) != (MODEL, API_BASE, MAX_TOKENS, 0):
            failures.append(
                "physical request differed from the pinned model, route, or budget"
            )
        if attempt.get("response_model") not in SERVED_MODELS:
            failures.append("served-model evidence is missing or mismatched")
        usage = attempt.get("usage")
        if not isinstance(usage, dict) or any(
            type(usage.get(k)) is not int or usage[k] <= 0
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        ):
            failures.append("provider token usage evidence is missing or incomplete")
        if attempt.get("error_type"):
            failures.append("provider returned an error")
    try:
        provider_json = json.loads(attempts[0]["provider_content"])
        provider_verdicts = provider_json.get("verdicts")
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        provider_verdicts = None
    parsed_verdicts = record.get("raw_verdicts")
    if (
        not isinstance(provider_verdicts, list)
        or [x.get("index") for x in provider_verdicts if isinstance(x, dict)]
        != [1, 2, 3, 4]
        or [x.get("label") for x in provider_verdicts if isinstance(x, dict)]
        != list(LABELS)
        or not isinstance(parsed_verdicts, list)
        or [x.get("label") for x in parsed_verdicts if isinstance(x, dict)]
        != list(LABELS)
    ):
        failures.append("raw model verdicts do not contain the exact ordered labels")
    if (
        len(checks) != 4
        or [x.get("id") for x in checks] != list(IDS)
        or [x.get("label") for x in checks] != list(LABELS)
    ):
        failures.append(
            "actual-interface labels differ from the exact ordered sequence"
        )
    if len(checks) == 4:
        for item, check, method in zip(dataset["items"], checks, METHODS):
            if check.get("verification_method") != method:
                failures.append(f"{item['id']} has an unaccepted verification method")
                continue
            key = (
                "contradicting_spans"
                if check["label"] == "contradicts"
                else "supporting_spans"
            )
            opposite = (
                "supporting_spans"
                if check["label"] == "contradicts"
                else "contradicting_spans"
            )
            if check.get(opposite):
                failures.append(f"{item['id']} has an opposite-polarity source span")
            spans = check.get(key, [])
            if check["label"] == "insufficient":
                if check.get("supporting_spans") or check.get("contradicting_spans"):
                    failures.append(
                        f"{item['id']} has a span for an insufficient claim"
                    )
                continue
            passage = item["passages"][0]
            if len(spans) != 1:
                failures.append(f"{item['id']} lacks one located source quote")
                continue
            span = spans[0]
            quote, start, end = span.get("quote"), span.get("start"), span.get("end")
            if (
                not isinstance(quote, str)
                or type(start) is not int
                or type(end) is not int
                or not (0 <= start < end <= len(passage))
                or passage[start:end] != quote
            ):
                failures.append(
                    f"{item['id']} quote is not an exact located source span"
                )
            elif check["label"] == "contradicts" and CONTRADICTION_ANCHOR not in quote:
                failures.append(
                    f"{item['id']} contradiction quote omits its subject and conditions"
                )
    return failures


def main() -> int:
    output_text = os.getenv("QUALIFICATION_OUTPUT", "")
    if not output_text:
        print(json.dumps({"error": "QUALIFICATION_OUTPUT is required"}))
        return 1
    output = Path(output_text).expanduser()
    try:
        artifact = os.fdopen(
            os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
            "w",
            encoding="utf-8",
        )
    except FileExistsError:
        print(json.dumps({"error": "qualification output already exists"}))
        return 1
    except OSError as exc:
        print(json.dumps({"error_type": type(exc).__name__}))
        return 1
    run_id = f"groq-qwen38-qualification:{output.resolve()}"
    counter = [0]
    record = {
        "requested_model": MODEL,
        "status": "failed",
        "passed": False,
        "max_attempts": MAX_ATTEMPTS,
        "sdk_retries": SDK_RETRIES,
        "physical_call_cap": CALL_CAP,
        "physical_attempts": [],
        "physical_call_count": 0,
        "logical_call_count": 0,
        "fallback_blocked": False,
        "batch_invocations": [],
        "raw_verdicts": None,
        "report": None,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    try:
        _verify_clean_worktree(output)
        identity = _load_protocol()
        record["preregistration"] = identity
        record["attested_utc_date"] = _attested_today()
        dataset, preflight = load_frozen_panel()
        record["frozen_inputs"] = {
            "manifest": PREFLIGHT_RELATIVE,
            "dataset_sha256": preflight["source_sha256"],
            "schema_sha256": preflight["schema_sha256"],
            "selected_ids": list(IDS),
            "expected_labels": list(LABELS),
        }
        if litellm.model_fallbacks or litellm.model_alias_map:
            raise ValueError("SDK fallback or alias routing is configured")
        original, observed = _observe_transport(record)
        with (
            scoped_cache_override(False),
            scoped_llm_call_budget(run_id, CALL_CAP),
            llm_free_policy.scoped_campaign_mode(True),
            _one_attempt(record),
            _no_fallbacks(record),
            _no_sdk_retries(),
        ):
            litellm.acompletion = observed
            try:
                assessor, assessor_id = make_llm_batch_assessor(
                    MODEL, call_counter=counter
                )
                if assessor_id != f"llm:{MODEL}":
                    raise ValueError("batch assessor provenance differs from candidate")
                record["assessor_id"] = assessor_id
                record["report"] = run_batch(dataset, assessor, assessor_id, record)
            finally:
                litellm.acompletion = original
        record["logical_call_count"] = counter[0]
        record["acceptance_failures"] = _check_result(dataset, record)
        record["passed"] = not record["acceptance_failures"]
        record["status"] = "passed" if record["passed"] else "failed"
    except Exception as exc:
        record["error_type"], record["error"] = type(exc).__name__, _safe(str(exc))
    finally:
        record["logical_call_count"] = counter[0]
        record["physical_call_count"] = sum(
            bool(row.get("transport_invoked")) for row in record["physical_attempts"]
        )
        if record.get("preregistration"):
            record["provider_request_budget_count"] = current_run_call_count(run_id)
        record["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        artifact.write(json.dumps(_safe(record), indent=2, sort_keys=True) + "\n")
        artifact.close()
    print(
        json.dumps(
            {
                "requested_model": MODEL,
                "status": record["status"],
                "passed": record["passed"],
                "physical_call_count": record["physical_call_count"],
                "error_type": record.get("error_type"),
                "artifact": str(output),
            }
        ),
        flush=True,
    )
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

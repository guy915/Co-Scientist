"""One preregistered Groq Free four-claim batch trial, without retries."""

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

# The preregistration requires a protected-file-injected key, never dotenv.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import litellm

from app import claim_verifier_batch
from app.claim_verifier_batch import _BATCH_DRAFT_SCHEMA, make_llm_batch_assessor
from app.claims import EvidencePassage, assess_claims_batch
from co_scientist.llm_call_budget import current_run_call_count, scoped_llm_call_budget

FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parents[3]
PROTOCOL_PATH = FOLDER / "groq-free-qualification-prereg-v1.json"
PREFLIGHT_PATH = FOLDER / "batch-schema-preflight109.json"
MODEL = "groq/openai/gpt-oss-120b"
API_BASE = "https://api.groq.com/openai/v1"
ACCEPTED_MODEL_IDS = (MODEL, "openai/gpt-oss-120b", "gpt-oss-120b")
ACCEPTED_MODELS = set(ACCEPTED_MODEL_IDS)
INTERFACE_CASES = ("schema", "tools", "streaming", "long_prompt")
ATTESTATION_ENV = "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION"
_PHYSICAL_ATTEMPTS: list[dict[str, Any]] = []


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_error(exc: Exception) -> str:
    message = re.sub(r"\buser_[A-Za-z0-9]+\b", "[redacted-account]", str(exc))
    message = re.sub(r"\bgsk_[A-Za-z0-9_-]+\b", "[redacted-key]", message)
    return re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+", r"\1[redacted-key]", message)[
        :2000
    ]


def _protocol() -> tuple[dict[str, Any], dict[str, Any]]:
    protocol_sha256 = digest(PROTOCOL_PATH)
    if (
        not os.getenv("QUALIFICATION_PREREG_SHA256")
        or protocol_sha256 != os.environ["QUALIFICATION_PREREG_SHA256"]
    ):
        raise ValueError("qualification protocol digest differs from preregistration")
    protocol = json.loads(PROTOCOL_PATH.read_text())
    candidate = protocol["candidate"]
    science = protocol["scientific_prerequisite"]
    if (
        candidate.get("model") != MODEL
        or candidate.get("api_base") != API_BASE
        or candidate.get("accepted_response_model_ids") != list(ACCEPTED_MODEL_IDS)
        or candidate.get("no_fallback") is not True
        or candidate.get("no_paid_tools") is not True
        or science.get("input_manifest") != str(PREFLIGHT_PATH.relative_to(ROOT))
        or science.get("boundary")
        != "app.claim_verifier_batch.make_llm_batch_assessor via app.claims.assess_claims_batch"
        or science.get("trials") != 3
        or science.get("physical_call_cap_per_trial") != 1
    ):
        raise ValueError("qualification route or trial differs from preregistration")
    sources = {}
    for relative, expected in protocol["source_hashes"].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError(f"qualification source missing: {relative}")
        sources[relative] = digest(path)
        if sources[relative] != expected:
            raise ValueError(f"qualification source hash differs: {relative}")
    if not sources:
        raise ValueError("qualification protocol has no source hashes")
    return protocol, {
        "sha256": protocol_sha256,
        "preregistered_source_commit": protocol.get("source_commit_before_probe"),
        "source_hashes": sources,
    }


def _interface_evidence(protocol: dict[str, Any]) -> dict[str, Any]:
    path = (
        Path(os.environ["QUALIFICATION_INTERFACE_ARTIFACT"])
        .expanduser()
        .resolve(strict=True)
    )
    evidence = json.loads(path.read_text())
    cases = evidence.get("cases")
    interface = protocol["interface"]
    pin = protocol["scientific_prerequisite"].get("interface_evidence_pin", {})
    runner_relative = interface["runner"]
    runner_path = (ROOT / runner_relative).resolve(strict=True)
    pinned_runner_sha256 = protocol["source_hashes"].get(runner_relative)
    expected_indexes = ([0], [1, 2], [3], [4])
    expected_call_cases = ["schema", "tools", "tools", "streaming", "long_prompt"]
    physical_calls = evidence.get("physical_calls")
    if (
        evidence.get("status") != "passed"
        or evidence.get("passed") is not True
        or evidence.get("requested_model") != MODEL
        or evidence.get("api_base") != API_BASE
        or not isinstance(pin, dict)
        or digest(path) != pin.get("artifact_sha256")
        or evidence.get("source_commit") != pin.get("source_commit")
        or evidence.get("prereg_sha256") != pin.get("prereg_sha256")
        or not isinstance(pinned_runner_sha256, str)
        or digest(runner_path) != pinned_runner_sha256
        or evidence.get("runner_sha256") != pinned_runner_sha256
        or not isinstance(cases, list)
        or [case.get("case") for case in cases] != list(INTERFACE_CASES)
        or not all(case.get("passed") is True for case in cases)
        or [case.get("physical_call_indexes") for case in cases]
        != list(expected_indexes)
        or not isinstance(physical_calls, list)
        or len(physical_calls) != 5
        or type(evidence.get("physical_call_count")) is not int
        or evidence["physical_call_count"] != 5
        or len(physical_calls) != interface["total_physical_call_cap"]
        or [call.get("case") for call in physical_calls] != expected_call_cases
        or evidence.get("blocked_attempts") != []
    ):
        raise ValueError("retained Groq interface evidence is missing or failed")
    for call in physical_calls:
        served_models = call.get("served_models")
        usages = call.get("usage")
        if (
            call.get("requested_model") != MODEL
            or call.get("api_base") != API_BASE
            or call.get("status") != "completed"
            or (
                call.get("rate_limited") is not None
                and call.get("rate_limited") is not False
            )
            or call.get("status_code") in (429, "429")
            or not isinstance(served_models, list)
            or not served_models
            or any(model not in ACCEPTED_MODELS for model in served_models)
            or not isinstance(usages, list)
            or not usages
            or not any(
                isinstance(usage, dict)
                and type(usage.get("prompt_tokens")) is int
                and usage["prompt_tokens"] >= 0
                and type(usage.get("completion_tokens")) is int
                and usage["completion_tokens"] >= 0
                and (
                    usage.get("total_tokens") is None
                    or (
                        type(usage.get("total_tokens")) is int
                        and usage["total_tokens"] >= 0
                    )
                )
                for usage in usages
            )
        ):
            raise ValueError("retained Groq interface evidence is missing or failed")
    return {"path": str(path), "sha256": digest(path)}


def _attested_today() -> str:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    if not re.fullmatch(rf"{today}:[0-9a-f]{{64}}", os.getenv(ATTESTATION_ENV, "")):
        raise ValueError(
            "current Groq Free/ZDR date and effective-key attestation is missing or stale"
        )
    return today


def load_frozen_panel() -> tuple[dict[str, Any], dict[str, Any]]:
    preflight = json.loads(PREFLIGHT_PATH.read_text())
    dataset_path = FOLDER / preflight["source_dataset"]
    if digest(dataset_path) != preflight["source_sha256"]:
        raise ValueError("Frozen batch dataset differs from preflight")
    if (
        hashlib.sha256(
            json.dumps(_BATCH_DRAFT_SCHEMA, sort_keys=True).encode()
        ).hexdigest()
        != preflight["schema_sha256"]
    ):
        raise ValueError("Batch assessor schema differs from preflight")
    source = json.loads(dataset_path.read_text())
    by_id = {item["id"]: item for item in source["items"]}
    items = [by_id[item_id] for item_id in preflight["selected_ids"]]
    expected = ["partial", "supports", "insufficient", "contradicts"]
    if (
        len(by_id) != len(source["items"])
        or len(items) != 4
        or preflight["expected_labels"] != expected
        or [item["allowed_labels"] for item in items] != [[label] for label in expected]
    ):
        raise ValueError("Frozen batch panel ids or labels differ from preflight")
    return {"items": items}, preflight


def run_batch(
    dataset: dict[str, Any], assessor: Any, assessor_id: str, record: dict[str, Any]
) -> dict[str, Any]:
    items = dataset["items"]
    claims = [item["claim"] for item in items]
    passages = [
        EvidencePassage(
            evidence_id=item["id"], text=item["passages"][0], source="frozen_control"
        )
        for item in items
    ]

    def observed_assessor(batch_claims, batch_passages):
        record["batch_invocations"].append(
            {"claims": len(batch_claims), "passages": len(batch_passages)}
        )
        return assessor(batch_claims, batch_passages)

    results = assess_claims_batch(
        claims, passages, batch_assessor=observed_assessor, assessor_id=assessor_id
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


def _usage(usage: Any) -> dict[str, Any] | None:
    if hasattr(usage, "model_dump"):
        return usage.model_dump(mode="json")
    if isinstance(usage, dict):
        return usage
    return None


def _observe_transport(record: dict[str, Any]):
    original = litellm.acompletion
    _PHYSICAL_ATTEMPTS.clear()

    async def observed(**kwargs):
        attempt = {
            "requested_model": kwargs.get("model"),
            "api_base": kwargs.get("api_base"),
            "max_tokens": kwargs.get("max_tokens"),
            "prompt_sha256": hashlib.sha256(
                json.dumps(kwargs.get("messages"), sort_keys=True).encode()
            ).hexdigest(),
        }
        _PHYSICAL_ATTEMPTS.append(attempt)
        if (
            len(_PHYSICAL_ATTEMPTS) > 1
            or attempt["requested_model"] != MODEL
            or attempt["api_base"] != API_BASE
        ):
            attempt["blocked_before_transport"] = True
            raise RuntimeError("Groq request exceeded the one-call pinned route")
        attempt["transport_invoked"] = True
        try:
            response = await original(**kwargs)
        except Exception as exc:
            attempt["error_type"] = type(exc).__name__
            attempt["error"] = _safe_error(exc)
            raise
        attempt["response_model"] = getattr(response, "model", None)
        attempt["usage"] = _usage(getattr(response, "usage", None))
        choices = getattr(response, "choices", None) or []
        attempt["finish_reason"] = (
            getattr(choices[0], "finish_reason", None) if choices else None
        )
        return response

    record["physical_attempts"] = _PHYSICAL_ATTEMPTS
    return original, observed


@contextlib.contextmanager
def _one_attempt(record: dict[str, Any]):
    original = claim_verifier_batch.call_llm_json

    async def call_once(*args, **kwargs):
        kwargs["max_attempts"] = 1
        response = await original(*args, **kwargs)
        record["raw_verdicts"] = response.get("verdicts")
        return response

    claim_verifier_batch.call_llm_json = call_once
    try:
        yield
    finally:
        claim_verifier_batch.call_llm_json = original


@contextlib.contextmanager
def _no_transport_retries():
    missing = object()
    original = getattr(litellm, "num_retries", missing)
    litellm.num_retries = 0
    try:
        yield
    finally:
        if original is missing:
            delattr(litellm, "num_retries")
        else:
            litellm.num_retries = original


def _check_result(
    dataset: dict[str, Any], preflight: dict[str, Any], record: dict[str, Any]
) -> list[str]:
    failures = []
    checks = (record.get("report") or {}).get("checks", [])
    attempts = record.get("physical_attempts", [])
    invocations = record["batch_invocations"]
    if len(invocations) != 1 or invocations[0].get("claims") != 4:
        failures.append("claims were not sent together in one batch")
    if (
        len(checks) != 4
        or [check["id"] for check in checks] != preflight["selected_ids"]
    ):
        failures.append("checks are missing or out of frozen manifest order")
    elif [check["label"] for check in checks] != preflight["expected_labels"]:
        failures.append("labels differ from the exact preregistered sequence")
    if len(attempts) != 1 or not attempts[0].get("transport_invoked"):
        failures.append("trial did not make exactly one physical provider attempt")
    elif attempts[0].get("response_model") not in ACCEPTED_MODELS:
        failures.append("served model is missing or outside accepted response ids")
    usage = attempts[0].get("usage") if attempts else None
    if not isinstance(usage, dict) or any(
        type(usage.get(key)) is not int or usage[key] < 0
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    ):
        failures.append("provider token usage evidence is missing")
    if len(checks) == 4:
        for source, check in zip(dataset["items"], checks):
            allowed_methods = {"model_primary"}
            if check["label"] == "contradicts":
                allowed_methods.add("lexical_founded")
            if check["verification_method"] not in allowed_methods:
                failures.append(
                    f"{source['id']} did not retain a model-primary verdict"
                )
            spans = check["supporting_spans"] + check["contradicting_spans"]
            needed = (
                "contradicting_spans"
                if check["label"] == "contradicts"
                else "supporting_spans"
            )
            if (
                check["label"] in {"partial", "supports", "contradicts"}
                and not check[needed]
            ):
                failures.append(f"{source['id']} lacks its located citation")
            for span in spans:
                if (
                    not span["quote"]
                    or len(span["quote"]) > 200
                    or not any(
                        span["quote"] in passage for passage in source["passages"]
                    )
                ):
                    failures.append(
                        f"{source['id']} has an unlocated or oversized span"
                    )
    return failures


def main() -> int:
    output_text = os.getenv("QUALIFICATION_OUTPUT", "")
    if not output_text:
        print(json.dumps({"error": "QUALIFICATION_OUTPUT is required"}))
        return 1
    output = Path(output_text).expanduser()
    try:
        artifact = output.open("x")
    except FileExistsError:
        print(json.dumps({"error": "qualification output already exists"}))
        return 1
    except OSError as exc:
        print(json.dumps({"error_type": type(exc).__name__, "error": _safe_error(exc)}))
        return 1

    record: dict[str, Any] = {
        "trial": None,
        "source_commit": None,
        "requested_model": MODEL,
        "probe_sha256": digest(Path(__file__)),
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "physical_attempts": _PHYSICAL_ATTEMPTS,
        "physical_attempt_count": 0,
        "provider_request_budget_count": 0,
        "batch_invocations": [],
        "raw_verdicts": None,
        "report": None,
        "max_attempts": 1,
        "physical_call_cap": 1,
        "status": "failed",
        "passed": False,
    }
    try:
        trial = int(os.environ["QUALIFICATION_TRIAL"])
        if trial not in {1, 2, 3}:
            raise ValueError("QUALIFICATION_TRIAL must be 1, 2, or 3")
        record["trial"] = trial
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        record["source_commit"] = head
        if os.getenv("QUALIFICATION_REVISION") != head:
            raise ValueError("QUALIFICATION_REVISION differs from current git HEAD")
        protocol, identity = _protocol()
        record["preregistration"] = identity
        record["interface_evidence"] = _interface_evidence(protocol)
        record["attested_utc_date"] = _attested_today()
        dataset, preflight = load_frozen_panel()
        record["frozen_inputs"] = {
            "dataset": preflight["source_dataset"],
            "dataset_sha256": preflight["source_sha256"],
            "schema_sha256": preflight["schema_sha256"],
            "selected_ids": preflight["selected_ids"],
            "expected_labels": preflight["expected_labels"],
        }

        run_id = f"qualification:{output.resolve()}"
        original, observed = _observe_transport(record)
        with (
            scoped_llm_call_budget(run_id, 1),
            _one_attempt(record),
            _no_transport_retries(),
        ):
            litellm.acompletion = observed
            try:
                assessor, assessor_id = make_llm_batch_assessor(MODEL)
                if assessor_id != f"llm:{MODEL}":
                    raise ValueError("batch assessor provenance differs from candidate")
                record["assessor_id"] = assessor_id
                record["report"] = run_batch(dataset, assessor, assessor_id, record)
            finally:
                litellm.acompletion = original
        record["acceptance_failures"] = _check_result(dataset, preflight, record)
        record["passed"] = not record["acceptance_failures"]
        record["status"] = "passed" if record["passed"] else "failed"
    except Exception as exc:
        record["error_type"] = type(exc).__name__
        record["error"] = _safe_error(exc)
    finally:
        record["physical_attempt_count"] = sum(
            bool(attempt.get("transport_invoked")) for attempt in _PHYSICAL_ATTEMPTS
        )
        if record["source_commit"]:
            record["provider_request_budget_count"] = current_run_call_count(
                f"qualification:{output.resolve()}"
            )
        record["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        artifact.write(json.dumps(record, indent=2, default=str) + "\n")
        artifact.close()
    print(
        json.dumps(
            {
                "trial": record["trial"],
                "status": record["status"],
                "physical_attempt_count": record["physical_attempt_count"],
                "artifact": str(output),
                "error_type": record.get("error_type"),
            }
        )
    )
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

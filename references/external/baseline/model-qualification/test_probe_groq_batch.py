"""Offline gates for the single-call Groq scientific prerequisite probe."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


FOLDER = Path(__file__).resolve().parent
MODEL = "groq/openai/gpt-oss-120b"


def _probe(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.syspath_prepend(str(FOLDER))
    return sys.modules.get("probe_groq_batch") or importlib.import_module(
        "probe_groq_batch"
    )


def _environment(monkeypatch, probe, tmp_path: Path) -> Path:
    output = tmp_path / "trial.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    monkeypatch.setenv("QUALIFICATION_TRIAL", "1")
    prereg_sha256 = probe.digest(probe.PROTOCOL_PATH)
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", prereg_sha256)
    monkeypatch.setenv(
        "QUALIFICATION_REVISION",
        subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    )
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setenv("COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION", f"{today}:{'a' * 64}")
    interface = tmp_path / "interface.json"
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    protocol = json.loads(probe.PROTOCOL_PATH.read_text())
    interface_runner = protocol["interface"]["runner"]
    calls = []
    case_names = ("schema", "tools", "streaming", "long_prompt")
    for name, indexes in zip(case_names, ([0], [1, 2], [3], [4])):
        for _ in indexes:
            calls.append(
                {
                    "case": name,
                    "requested_model": MODEL,
                    "api_base": probe.API_BASE,
                    "status": "completed",
                    "served_models": ["openai/gpt-oss-120b"],
                    "usage": [
                        {
                            "prompt_tokens": 10,
                            "completion_tokens": 10,
                            "total_tokens": 20,
                        }
                    ],
                    "rate_limited": False,
                }
            )
    interface.write_text(
        json.dumps(
            {
                "requested_model": MODEL,
                "api_base": probe.API_BASE,
                "source_commit": source_commit,
                "prereg_sha256": prereg_sha256,
                "runner_sha256": probe.digest(probe.ROOT / interface_runner),
                "status": "passed",
                "passed": True,
                "cases": [
                    {"case": name, "passed": True, "physical_call_indexes": indexes}
                    for name, indexes in zip(case_names, ([0], [1, 2], [3], [4]))
                ],
                "physical_calls": calls,
                "blocked_attempts": [],
                "physical_call_count": 5,
            }
        )
    )
    monkeypatch.setenv("QUALIFICATION_INTERFACE_ARTIFACT", str(interface))
    return output


def _dynamic_protocol(probe):
    protocol = json.loads(probe.PROTOCOL_PATH.read_text())
    for relative in protocol["source_hashes"]:
        protocol["source_hashes"][relative] = probe.digest(probe.ROOT / relative)
    return protocol


def test_protocol_digest_drift_fails_before_any_provider_call(
    monkeypatch, tmp_path
) -> None:
    probe = _probe(monkeypatch)
    output = _environment(monkeypatch, probe, tmp_path)
    changed = json.loads(probe.PROTOCOL_PATH.read_text())
    changed["purpose"] = "changed after preregistration"
    protocol = tmp_path / "changed-protocol.json"
    protocol.write_text(json.dumps(changed))
    monkeypatch.setattr(probe, "PROTOCOL_PATH", protocol)

    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert record["error_type"] == "ValueError"
    assert "protocol digest" in record["error"].lower()
    assert record["physical_attempt_count"] == 0


def test_existing_output_is_never_overwritten(monkeypatch, tmp_path) -> None:
    probe = _probe(monkeypatch)
    output = tmp_path / "trial.json"
    output.write_text("keep this evidence\n")
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))

    assert probe.main() == 1
    assert output.read_text() == "keep this evidence\n"


def test_minimal_interface_pass_without_physical_evidence_is_rejected(
    monkeypatch, tmp_path
) -> None:
    probe = _probe(monkeypatch)
    output = _environment(monkeypatch, probe, tmp_path)
    interface = Path(str(tmp_path / "interface.json"))
    prereg_sha256 = probe.digest(probe.PROTOCOL_PATH)
    interface.write_text(
        json.dumps(
            {
                "requested_model": MODEL,
                "prereg_sha256": prereg_sha256,
                "status": "passed",
                "cases": [
                    {"case": name, "passed": True}
                    for name in ("schema", "tools", "streaming", "long_prompt")
                ],
                "physical_call_count": 0,
            }
        )
    )
    protocol = _dynamic_protocol(probe)
    monkeypatch.setattr(
        probe,
        "_protocol",
        lambda: (protocol, {"sha256": prereg_sha256, "source_hashes": {}}),
    )
    entered_batch = []
    monkeypatch.setattr(
        probe,
        "make_llm_batch_assessor",
        lambda _model: entered_batch.append(True),
    )

    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert "interface evidence" in record["error"].lower()
    assert entered_batch == []
    assert record["physical_attempt_count"] == 0


@pytest.mark.parametrize(
    "invalid_evidence",
    [
        "api_base",
        "source_commit",
        "runner_sha256",
        "case_indexes",
        "physical_calls",
        "served_models",
        "usage",
        "rate_limit",
        "rate_limit_shape",
    ],
)
def test_interface_gate_rejects_incomplete_or_unpinned_call_records(
    monkeypatch, tmp_path, invalid_evidence
) -> None:
    probe = _probe(monkeypatch)
    output = _environment(monkeypatch, probe, tmp_path)
    interface = tmp_path / "interface.json"
    evidence = json.loads(interface.read_text())
    if invalid_evidence == "api_base":
        evidence["api_base"] = "https://example.invalid/v1"
    elif invalid_evidence == "source_commit":
        evidence["source_commit"] = "0" * 40
    elif invalid_evidence == "runner_sha256":
        evidence["runner_sha256"] = "0" * 64
    elif invalid_evidence == "case_indexes":
        evidence["cases"][1]["physical_call_indexes"] = [1]
    elif invalid_evidence == "physical_calls":
        evidence["physical_calls"].pop()
    elif invalid_evidence == "served_models":
        evidence["physical_calls"][0]["served_models"] = []
    elif invalid_evidence == "usage":
        evidence["physical_calls"][0]["usage"] = []
    elif invalid_evidence == "rate_limit_shape":
        evidence["physical_calls"][0]["rate_limited"] = 0
    else:
        evidence["physical_calls"][0].update(status_code=429, rate_limited=True)
    interface.write_text(json.dumps(evidence))
    protocol = _dynamic_protocol(probe)
    monkeypatch.setattr(
        probe,
        "_protocol",
        lambda: (protocol, {"sha256": probe.digest(probe.PROTOCOL_PATH)}),
    )
    entered_batch = []
    monkeypatch.setattr(
        probe,
        "make_llm_batch_assessor",
        lambda _model: entered_batch.append(True),
    )

    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert "interface evidence" in record["error"].lower()
    assert entered_batch == []
    assert record["physical_attempt_count"] == 0


def test_transport_retries_are_disabled_and_restored(monkeypatch, tmp_path) -> None:
    probe = _probe(monkeypatch)
    _environment(monkeypatch, probe, tmp_path)
    protocol = _dynamic_protocol(probe)
    monkeypatch.setattr(
        probe,
        "_protocol",
        lambda: (protocol, {"sha256": probe.digest(probe.PROTOCOL_PATH)}),
    )
    monkeypatch.setattr(probe.litellm, "num_retries", 7, raising=False)
    observed = []

    def assessor(_claims, _passages):
        observed.append(probe.litellm.num_retries)
        raise RuntimeError("synthetic failure before transport")

    monkeypatch.setattr(
        probe,
        "make_llm_batch_assessor",
        lambda model: (assessor, f"llm:{model}"),
    )

    assert probe.main() == 1
    assert observed == [0]
    assert probe.litellm.num_retries == 7


def test_budget_stops_second_provider_request_and_records_partial_attempts(
    monkeypatch, tmp_path
) -> None:
    probe = _probe(monkeypatch)
    output = _environment(monkeypatch, probe, tmp_path)
    protocol = _dynamic_protocol(probe)
    monkeypatch.setattr(
        probe,
        "_protocol",
        lambda: (protocol, {"sha256": probe.digest(probe.PROTOCOL_PATH)}),
    )

    from co_scientist.llm_call_budget import record_provider_request

    def assessor(_claims, _passages):
        record_provider_request()
        record_provider_request()

    monkeypatch.setattr(
        probe,
        "make_llm_batch_assessor",
        lambda model: (assessor, f"llm:{model}"),
    )

    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert record["error_type"] == "LLMCallBudgetExceededError"
    assert record["provider_request_budget_count"] == 2
    assert record["physical_attempt_count"] == 0
    assert record["report"] is None


def test_single_attempt_adapter_uses_production_batch_boundary(monkeypatch) -> None:
    probe = _probe(monkeypatch)
    dataset, preflight = probe.load_frozen_panel()
    texts = [item["passages"][0] for item in dataset["items"]]
    response = {
        "verdicts": [
            {
                "index": 1,
                "label": "partial",
                "supporting": [{"passage": 1, "quote": texts[0]}],
                "contradicting": [],
            },
            {
                "index": 2,
                "label": "supports",
                "supporting": [{"passage": 2, "quote": texts[1]}],
                "contradicting": [],
            },
            {
                "index": 3,
                "label": "insufficient",
                "supporting": [],
                "contradicting": [],
            },
            {
                "index": 4,
                "label": "contradicts",
                "supporting": [],
                "contradicting": [{"passage": 4, "quote": texts[3]}],
            },
        ]
    }
    calls = []

    async def completion(*_args, **kwargs):
        calls.append(kwargs["max_attempts"])
        return response

    monkeypatch.setattr(probe.claim_verifier_batch, "call_llm_json", completion)
    assessor, assessor_id = probe.make_llm_batch_assessor(MODEL)
    record = {"batch_invocations": [], "raw_drafts": [], "raw_verdicts": None}

    with probe._one_attempt(record):
        report = probe.run_batch(dataset, assessor, assessor_id, record)

    assert calls == [1]
    assert record["raw_verdicts"] == response["verdicts"]
    assert record["batch_invocations"][0]["claims"] == 4
    assert [check["label"] for check in report["checks"]] == preflight[
        "expected_labels"
    ]
    assert report["checks"][3]["contradicting_spans"][0]["quote"] == texts[3]

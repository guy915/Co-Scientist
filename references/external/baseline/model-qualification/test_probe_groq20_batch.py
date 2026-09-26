"""Offline safety and acceptance tests for the Groq 20B screen."""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

FOLDER = Path(__file__).resolve().parent
MODEL = "groq/openai/gpt-oss-20b"


def _probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.syspath_prepend(str(FOLDER))
    sys.modules.pop("probe_groq20_batch", None)
    return importlib.import_module("probe_groq20_batch")


def _frozen_protocol(probe, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    protocol = json.loads(probe.PROTOCOL_PATH.read_text())
    protocol["status"] = "frozen"
    protocol["source_commit_before_probe"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=probe.ROOT, text=True
    ).strip()
    protocol["source_hashes"] = {
        relative: probe.digest(probe.ROOT / relative) for relative in probe.SOURCE_PATHS
    }
    path = tmp_path / "frozen-protocol.json"
    path.write_text(json.dumps(protocol, indent=2) + "\n")
    monkeypatch.setattr(probe, "PROTOCOL_PATH", path)
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", probe.digest(path))
    monkeypatch.setenv("QUALIFICATION_REVISION", protocol["source_commit_before_probe"])
    return path


def _install_current_attestation(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    key = "offline-only-groq-key"
    monkeypatch.setenv("GROQ_API_KEY", key)
    today = datetime.now(timezone.utc).date().isoformat()
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    monkeypatch.setenv(
        "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION", f"{today}:{fingerprint}"
    )


def _completion(reply: dict[str, object], *, model: str = "openai/gpt-oss-20b"):
    return SimpleNamespace(
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=120, completion_tokens=80, total_tokens=200
        ),
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(reply)),
            )
        ],
    )


def _reply_from_prompt(probe, messages) -> dict[str, object]:
    prompt = messages[-1]["content"]
    preflight = json.loads(probe.PREFLIGHT_PATH.read_text())
    source = json.loads((probe.FOLDER / preflight["source_dataset"]).read_text())
    by_id = {item["id"]: item for item in source["items"]}
    items = [by_id[item_id] for item_id in preflight["selected_ids"]]
    verdicts = []
    for index, item in enumerate(items, start=1):
        passage = item["passages"][0]
        match = re.search(rf"(?m)^\[(\d+)\] {re.escape(passage)}$", prompt)
        assert match, (
            f"fixed evidence passage missing from actual request: {item['id']}"
        )
        quote = (
            passage.split(";", 1)[0]
            if item["allowed_labels"][0] == "partial"
            else passage
        )
        if item["allowed_labels"][0] == "contradicts":
            quote = probe.CONTRADICTION_ANCHOR
        citation = {"passage": int(match.group(1)), "quote": quote}
        verdicts.append(
            {
                "index": index,
                "label": item["allowed_labels"][0],
                "supporting": [citation]
                if item["allowed_labels"][0] in {"partial", "supports"}
                else [],
                "contradicting": [citation]
                if item["allowed_labels"][0] == "contradicts"
                else [],
            }
        )
    return {"verdicts": verdicts}


def test_draft_protocol_fails_closed_without_any_provider_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    monkeypatch.setattr(probe, "_verify_clean_worktree", lambda output: None)
    output = tmp_path / "trial.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", probe.digest(probe.PROTOCOL_PATH))
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        raise AssertionError("draft preregistration must not reach transport")

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert calls == []
    assert record["physical_call_count"] == 0
    assert record["status"] == "failed"
    assert record["error_type"] == "ValueError"
    assert "not frozen" in record["error"].lower()
    saved = output.read_bytes()
    assert probe.main() == 1
    assert output.read_bytes() == saved


def test_dirty_checkout_stops_before_provider_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    _frozen_protocol(probe, monkeypatch, tmp_path)
    _install_current_attestation(monkeypatch)
    output = tmp_path / "dirty.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    sentinel = probe.ROOT / f".groq20-dirty-{tmp_path.name}"
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        return _completion(_reply_from_prompt(probe, kwargs["messages"]))

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    try:
        sentinel.write_text("uncommitted assay input\n")
        assert probe.main() == 1
    finally:
        sentinel.unlink(missing_ok=True)
    record = json.loads(output.read_text())
    assert calls == []
    assert record["physical_call_count"] == 0
    assert "checkout is not clean" in record["error"].lower()


def test_frozen_protocol_accepts_source_commit_ancestor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    path = _frozen_protocol(probe, monkeypatch, tmp_path)
    protocol = json.loads(path.read_text())
    parent = subprocess.check_output(
        ["git", "rev-parse", "HEAD^"], cwd=probe.ROOT, text=True
    ).strip()
    protocol["source_commit_before_probe"] = parent
    path.write_text(json.dumps(protocol) + "\n")
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", probe.digest(path))
    monkeypatch.setenv("QUALIFICATION_REVISION", parent)
    assert probe._load_protocol()["source_commit"] == parent


def test_scientific_gate_accepts_guarded_contradiction_method_not_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _probe(monkeypatch)
    dataset, preflight = probe.load_frozen_panel()
    checks = []
    for item, label in zip(dataset["items"], preflight["expected_labels"]):
        spans = []
        if label in {"partial", "supports", "contradicts"}:
            passage = item["passages"][0]
            quote = passage.split(";", 1)[0] if label == "partial" else passage
            if label == "contradicts":
                quote = probe.CONTRADICTION_ANCHOR
            spans = [{"quote": quote, "start": 0, "end": len(quote)}]
        checks.append(
            {
                "id": item["id"],
                "label": label,
                "verification_method": (
                    "lexical_founded" if label == "contradicts" else "model_primary"
                ),
                "supporting_spans": spans if label in {"partial", "supports"} else [],
                "contradicting_spans": spans if label == "contradicts" else [],
            }
        )
    record = {
        "report": {"checks": checks},
        "batch_invocations": [{"claims": 4, "passages": 4}],
        "logical_call_count": 1,
        "physical_attempts": [
            {
                "transport_invoked": True,
                "requested_model": probe.MODEL,
                "api_base": probe.API_BASE,
                "max_tokens": probe.MAX_TOKENS,
                "response_model": "openai/gpt-oss-20b",
                "provider_content": json.dumps(
                    {
                        "verdicts": [
                            {"index": index, "label": label}
                            for index, label in enumerate(
                                preflight["expected_labels"], start=1
                            )
                        ]
                    }
                ),
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 80,
                    "total_tokens": 200,
                },
            }
        ],
        "raw_verdicts": [
            {"index": index, "label": label}
            for index, label in enumerate(preflight["expected_labels"], start=1)
        ],
    }
    assert probe._check_result(dataset, record) == []
    checks[0]["contradicting_spans"] = [checks[0]["supporting_spans"][0]]
    assert any("opposite" in error for error in probe._check_result(dataset, record))
    checks[0]["contradicting_spans"] = []
    checks[0]["supporting_spans"][0]["start"] = 1
    assert any(
        "exact located source span" in error
        for error in probe._check_result(dataset, record)
    )
    checks[0]["supporting_spans"][0]["start"] = 0
    checks[-1]["verification_method"] = "model_primary"
    assert any(
        "verification method" in error for error in probe._check_result(dataset, record)
    )


def test_main_uses_one_actual_batch_request_and_records_exact_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    _frozen_protocol(probe, monkeypatch, tmp_path)
    monkeypatch.setattr(probe, "_verify_clean_worktree", lambda output: None)
    _install_current_attestation(monkeypatch)
    output = tmp_path / "success.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    sent = []

    async def completion(**kwargs):
        sent.append(kwargs)
        return _completion(_reply_from_prompt(probe, kwargs["messages"]))

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    assert probe.main() == 0
    record = json.loads(output.read_text())
    assert record["passed"] is True
    assert record["physical_call_count"] == 1
    assert record["logical_call_count"] == 1
    assert len(sent) == 1
    assert sent[0]["model"] == MODEL
    assert sent[0]["api_base"] == probe.API_BASE
    assert sent[0]["max_retries"] == 0
    assert record["report"]["checks"][-1]["verification_method"] == "lexical_founded"
    assert (
        record["report"]["checks"][0]["supporting_spans"][0]["quote"]
        == probe.load_frozen_panel()[0]["items"][0]["passages"][0].split(";", 1)[0]
    )
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o600


def test_first_transport_error_is_retained_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    _frozen_protocol(probe, monkeypatch, tmp_path)
    monkeypatch.setattr(probe, "_verify_clean_worktree", lambda output: None)
    _install_current_attestation(monkeypatch)
    output = tmp_path / "failed.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("api_key=offline-only-groq-key offline synthetic failure")

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert len(calls) == record["physical_call_count"] == 1
    assert record["physical_attempts"][0]["error_type"] == "RuntimeError"
    assert record["passed"] is False
    artifact_text = output.read_text()
    assert "offline-only-groq-key" not in artifact_text
    assert "[redacted]" in artifact_text

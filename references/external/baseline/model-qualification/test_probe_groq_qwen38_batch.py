"""Offline public-runner tests for the Groq Qwen3.8 27B qualification assay."""

from __future__ import annotations

import importlib
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

FOLDER = Path(__file__).resolve().parent


def _probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.syspath_prepend(str(FOLDER))
    sys.modules.pop("probe_groq_qwen38_batch", None)
    return importlib.import_module("probe_groq_qwen38_batch")


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _synthetic_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Offline Qualification Test")
    _git(repo, "config", "user.email", "offline@example.invalid")
    (repo / "PLAN.md").write_text("source plan\n")
    (repo / "runtime.py").write_text("runtime = 'source'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "source")
    return repo, _git(repo, "rev-parse", "HEAD")


def _write_frozen_protocol(
    probe,
    repo: Path,
    source_commit: str,
    source_paths: tuple[str, ...],
    *,
    runtime_hashes: dict[str, str] | None = None,
) -> Path:
    protocol = json.loads(probe.PROTOCOL_PATH.read_text())
    protocol["status"] = "frozen"
    protocol["source_commit_before_probe"] = source_commit
    protocol["source_hashes"] = runtime_hashes or {
        relative: probe.digest(repo / relative) for relative in source_paths
    }
    path = repo / probe.PROTOCOL_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(protocol, indent=2) + "\n")
    return path


def _install_frozen_protocol(
    probe, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
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
    key = "offline-only-groq-key"
    monkeypatch.setenv("GROQ_API_KEY", key)
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setenv(
        "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION",
        f"{today}:{hashlib.sha256(key.encode()).hexdigest()}",
    )


def test_frozen_protocol_rejects_paid_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    path = _install_frozen_protocol(probe, monkeypatch, tmp_path)
    protocol = json.loads(path.read_text())
    protocol["candidate"]["no_paid_tools"] = False
    path.write_text(json.dumps(protocol) + "\n")
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", probe.digest(path))
    with pytest.raises(ValueError, match="route or assay differs"):
        probe._load_protocol()


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
        assert match, f"fixed evidence passage missing: {item['id']}"
        label = item["allowed_labels"][0]
        quote = passage.split(";", 1)[0] if label == "partial" else passage
        if label == "contradicts":
            quote = probe.CONTRADICTION_ANCHOR
        citation = {"passage": int(match.group(1)), "quote": quote}
        verdicts.append(
            {
                "index": index,
                "label": label,
                "supporting": [citation] if label in {"partial", "supports"} else [],
                "contradicting": [citation] if label == "contradicts" else [],
            }
        )
    return {"verdicts": verdicts}


def _completion(reply: dict[str, object], model: str = "qwen/qwen3.8-27b"):
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


def test_draft_protocol_stops_at_public_runner_before_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    monkeypatch.setattr(probe, "_verify_clean_worktree", lambda output: None)
    output = tmp_path / "draft.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", probe.digest(probe.PROTOCOL_PATH))
    transport_calls = []

    async def completion(**kwargs):
        transport_calls.append(kwargs)
        raise AssertionError("draft protocol must stop before provider transport")

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert transport_calls == []
    assert record["physical_call_count"] == 0
    assert record["status"] == "failed"
    assert record["error_type"] == "ValueError"
    assert "not frozen" in record["error"].lower()
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o600


def test_dirty_checkout_stops_before_provider_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    repo, _ = _synthetic_repo(tmp_path)
    monkeypatch.setattr(probe, "ROOT", repo)
    (repo / "dirty.txt").write_text("uncommitted runtime state\n")
    output = tmp_path / "dirty.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    transport_calls = []

    async def completion(**kwargs):
        transport_calls.append(kwargs)
        raise AssertionError("dirty checkout must stop before provider transport")

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert transport_calls == []
    assert record["physical_call_count"] == 0
    assert "checkout is not clean" in record["error"].lower()


def test_source_commit_can_precede_plan_and_protocol_only_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    repo, source_commit = _synthetic_repo(tmp_path)
    relative_source = ("runtime.py",)
    monkeypatch.setattr(probe, "ROOT", repo)
    monkeypatch.setattr(probe, "SOURCE_PATHS", relative_source)
    (repo / "PLAN.md").write_text("reviewed source plan\n")
    path = _write_frozen_protocol(probe, repo, source_commit, relative_source)
    _git(repo, "add", "PLAN.md", probe.PROTOCOL_RELATIVE)
    _git(repo, "commit", "--quiet", "-m", "freeze protocol")
    monkeypatch.setattr(probe, "PROTOCOL_PATH", path)
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", probe.digest(path))
    monkeypatch.setenv("QUALIFICATION_REVISION", source_commit)

    identity = probe._load_protocol()

    assert identity["source_commit"] == source_commit
    assert identity["execution_commit"] == _git(repo, "rev-parse", "HEAD")


def test_committed_runtime_dependency_after_source_commit_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    repo, source_commit = _synthetic_repo(tmp_path)
    relative_source = ("runtime.py",)
    source_hashes = {"runtime.py": probe.digest(repo / "runtime.py")}
    monkeypatch.setattr(probe, "ROOT", repo)
    monkeypatch.setattr(probe, "SOURCE_PATHS", relative_source)
    (repo / "PLAN.md").write_text("reviewed source plan\n")
    path = _write_frozen_protocol(
        probe,
        repo,
        source_commit,
        relative_source,
        runtime_hashes=source_hashes,
    )
    (repo / "runtime.py").write_text("runtime = 'changed after source'\n")
    _git(repo, "add", "PLAN.md", "runtime.py", probe.PROTOCOL_RELATIVE)
    _git(repo, "commit", "--quiet", "-m", "forbidden runtime change")
    monkeypatch.setattr(probe, "PROTOCOL_PATH", path)
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", probe.digest(path))
    monkeypatch.setenv("QUALIFICATION_REVISION", source_commit)
    output = tmp_path / "runtime-change.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    transport_calls = []

    async def completion(**kwargs):
        transport_calls.append(kwargs)
        raise AssertionError("runtime descendant must stop before transport")

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert transport_calls == []
    assert record["physical_call_count"] == 0
    assert (
        "committed files changed after qualification source revision" in record["error"]
    )
    assert "runtime.py" in record["error"]


def test_public_runner_makes_one_pinned_batch_call_with_source_quotes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    _install_frozen_protocol(probe, monkeypatch, tmp_path)
    _install_current_attestation(monkeypatch)
    monkeypatch.setattr(probe, "_verify_clean_worktree", lambda output: None)
    output = tmp_path / "one-call.json"
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
    assert record["batch_invocations"] == [{"claims": 4, "passages": 4}]
    assert len(sent) == 1
    assert sent[0]["model"] == "groq/qwen/qwen3.8-27b"
    assert sent[0]["api_base"] == "https://api.groq.com/openai/v1"
    assert sent[0]["max_retries"] == 0
    attempt = record["physical_attempts"][0]
    assert attempt["response_model"] == "qwen/qwen3.8-27b"
    assert attempt["usage"] == {
        "prompt_tokens": 120,
        "completion_tokens": 80,
        "total_tokens": 200,
    }
    assert record["report"]["checks"][0]["supporting_spans"][0]["quote"].startswith(
        "In adult human hepatocytes, compound R reduced lipid accumulation"
    )
    assert record["report"]["checks"][-1]["verification_method"] == "lexical_founded"
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o600


def test_missing_free_zdr_attestation_stops_before_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    probe = _probe(monkeypatch)
    _install_frozen_protocol(probe, monkeypatch, tmp_path)
    monkeypatch.setattr(probe, "_verify_clean_worktree", lambda output: None)
    monkeypatch.setenv("GROQ_API_KEY", "offline-only-groq-key")
    monkeypatch.delenv("COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION", raising=False)
    output = tmp_path / "missing-attestation.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        raise AssertionError("unattested request must stop before transport")

    monkeypatch.setattr(probe.litellm, "acompletion", completion)
    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert calls == []
    assert record["physical_call_count"] == 0
    assert "current Groq Free/ZDR attestation" in record["error"]

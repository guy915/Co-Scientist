"""Offline contract tests for the bounded Cloudflare tool probe."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


FOLDER = Path(__file__).resolve().parent
ACCOUNT_ID = "a" * 32
TOKEN = "synthetic-cloudflare-token"


def _probe(monkeypatch, tmp_path, *, validate_sources=False):
    monkeypatch.syspath_prepend(str(FOLDER))
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    monkeypatch.setenv(
        "COSCIENTIST_CLOUDFLARE_WORKERS_FREE_ATTESTATION",
        f"{datetime.now(timezone.utc).date().isoformat()}:{ACCOUNT_ID}:workers-free",
    )
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(tmp_path / "tool.json"))
    monkeypatch.setenv("QUALIFICATION_PREREG", str(tmp_path / "prereg.json"))
    monkeypatch.delenv("QUALIFICATION_PREREG_SHA256", raising=False)
    probe = importlib.import_module("probe_cloudflare_tool")
    probe = importlib.reload(probe)
    verify_source_tree = probe._verified_source_hashes
    monkeypatch.setattr(
        probe, "_verified_source_hashes", lambda _commit: probe.source_hashes()
    )
    prereg = probe.expected_prereg()
    if validate_sources:
        monkeypatch.setattr(probe, "_verified_source_hashes", verify_source_tree)
    prereg_bytes = (
        json.dumps(prereg, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    prereg_path = Path(str(tmp_path / "prereg.json"))
    prereg_path.write_bytes(prereg_bytes)
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", probe.sha256(prereg_bytes))
    monkeypatch.setenv("QUALIFICATION_REVISION", probe.head_revision())
    return probe


def _tool_call_response(probe):
    return SimpleNamespace(
        model=probe.SERVED_MODEL,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(
                                name=probe.TOOL_NAME,
                                arguments=json.dumps(probe.TOOL_ARGUMENTS),
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=42, completion_tokens=10, total_tokens=52),
    )


def _final_response(probe, answer=None):
    if answer is None:
        answer = probe.EXPECTED_ANSWER
    return SimpleNamespace(
        model=probe.SERVED_MODEL,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    content=answer,
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=58, completion_tokens=12, total_tokens=70),
    )


def test_tool_round_trip_uses_two_pinned_physical_requests(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path)
    from co_scientist import llm_free_policy

    monkeypatch.setattr(llm_free_policy.litellm, "model_fallbacks", [])
    monkeypatch.setattr(llm_free_policy.litellm, "model_alias_map", {})
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        return _tool_call_response(probe) if len(calls) == 1 else _final_response(probe)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 0
    assert len(calls) == 2
    assert probe.request_config()["sdk_num_retries"] == 0
    assert probe.request_config()["sdk_max_retries"] == 0
    for request in calls:
        assert request["model"] == probe.MODEL
        assert request["max_retries"] == 0
        assert request["num_retries"] == 0
        assert request["drop_params"] is False
        assert request["api_base"].endswith(f"/accounts/{ACCOUNT_ID}/ai/v1")
        assert request["extra_body"]["options"]["rejectIfBusy"] is True
    artifact = json.loads((tmp_path / "tool.json").read_text())
    assert artifact["passed"] is True
    assert artifact["physical_request_count"] == 2
    assert artifact["tool_invocations"] == [
        {"name": probe.TOOL_NAME, "arguments": probe.TOOL_ARGUMENTS}
    ]
    assert [item["served_model"] for item in artifact["request_observations"]] == [
        probe.SERVED_MODEL,
        probe.SERVED_MODEL,
    ]
    assert [item["usage"] for item in artifact["request_observations"]] == [
        {"prompt_tokens": 42, "completion_tokens": 10, "total_tokens": 52},
        {"prompt_tokens": 58, "completion_tokens": 12, "total_tokens": 70},
    ]
    serialized = json.dumps(artifact)
    assert ACCOUNT_ID not in serialized
    assert TOKEN not in serialized


def test_first_transport_error_stops_without_a_second_request(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path)
    calls = []

    async def completion(**_kwargs):
        calls.append(True)
        raise TimeoutError(
            f"request failed for https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/v1 {TOKEN}"
        )

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 1
    assert calls == [True]
    artifact = json.loads((tmp_path / "tool.json").read_text())
    assert artifact["passed"] is False
    assert artifact["physical_request_count"] == 1
    serialized = json.dumps(artifact)
    assert ACCOUNT_ID not in serialized
    assert TOKEN not in serialized


def test_missing_usage_or_wrong_served_model_fails_completed_round_trip(
    monkeypatch, tmp_path
):
    probe = _probe(monkeypatch, tmp_path)
    responses = [_tool_call_response(probe), _final_response(probe)]
    responses[1].model = "@cf/other/model"
    responses[1].usage = None

    async def completion(**_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 1
    artifact = json.loads((tmp_path / "tool.json").read_text())
    assert artifact["passed"] is False
    assert artifact["physical_request_count"] == 2
    assert artifact["request_observations"][1]["error"] == (
        "provider response did not include the pinned model and positive token usage"
    )


def test_third_physical_request_is_blocked_before_transport(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path)
    calls = []

    async def completion(**_kwargs):
        calls.append(True)
        return _tool_call_response(probe)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 1
    assert len(calls) == 2
    artifact = json.loads((tmp_path / "tool.json").read_text())
    assert artifact["physical_request_count"] == 2
    assert artifact["passed"] is False
    assert artifact["error_type"]


@pytest.mark.parametrize(
    "answer",
    [
        "The control-A measurement was 1137 arbitrary units.",
        "The control-A measurement was not 137 arbitrary units.",
    ],
)
def test_final_answer_requires_exact_positive_measurement(
    monkeypatch, tmp_path, answer
):
    probe = _probe(monkeypatch, tmp_path)
    responses = [_tool_call_response(probe), _final_response(probe, answer)]

    async def completion(**_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 1
    artifact = json.loads((tmp_path / "tool.json").read_text())
    assert artifact["passed"] is False
    assert artifact["request_observations"][1]["error"] == (
        "second response did not meet the fixed answer criterion"
    )


def test_expected_prereg_rejects_dirty_behavior_source(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path, validate_sources=True)
    monkeypatch.setattr(
        probe,
        "_dirty_source_paths",
        lambda _paths: ["engine/src/co_scientist/llm.py"],
    )

    with pytest.raises(ValueError, match="dirty or uncommitted"):
        probe.expected_prereg()


def test_expected_prereg_pins_source_commit_blobs(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path, validate_sources=True)
    monkeypatch.setattr(probe, "_dirty_source_paths", lambda _paths: [])
    monkeypatch.setattr(
        probe,
        "_commit_source_hashes",
        lambda _commit, paths: {name: "0" * 64 for name in paths},
    )

    with pytest.raises(ValueError, match="do not match the frozen source commit"):
        probe.expected_prereg(source_commit="a" * 40)


def test_descendant_execution_requires_unchanged_commit_blobs(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path, validate_sources=True)
    seen = []
    monkeypatch.setattr(probe, "_dirty_source_paths", lambda _paths: [])
    monkeypatch.setattr(
        probe,
        "_commit_source_hashes",
        lambda commit, paths: seen.append(commit) or probe.source_hashes(),
    )
    probe.expected_prereg(source_commit="a" * 40)
    assert seen == ["a" * 40]


def test_frozen_prereg_binds_account_and_rejects_stale_attestation(
    monkeypatch, tmp_path
):
    probe = _probe(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "COSCIENTIST_CLOUDFLARE_WORKERS_FREE_ATTESTATION",
        f"2020-01-01:{ACCOUNT_ID}:workers-free",
    )
    calls = []

    async def completion(**_kwargs):
        calls.append(True)
        return _tool_call_response(probe)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 1
    assert calls == []
    artifact = json.loads((tmp_path / "tool.json").read_text())
    assert (
        artifact["error"] == "current Cloudflare Workers Free attestation is required"
    )


def test_frozen_prereg_remains_valid_after_its_commit(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path, validate_sources=True)
    monkeypatch.setattr(probe, "head_revision", lambda: "later-commit")
    monkeypatch.setattr(probe, "_is_ancestor", lambda _base: True)
    monkeypatch.setattr(probe, "_dirty_source_paths", lambda _paths: [])
    monkeypatch.setattr(
        probe,
        "_commit_source_hashes",
        lambda _commit, _paths: probe.source_hashes(),
    )
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        return _tool_call_response(probe) if len(calls) == 1 else _final_response(probe)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 0
    artifact = json.loads((tmp_path / "tool.json").read_text())
    assert artifact["source_commit"] != artifact["execution_commit"]
    assert len(calls) == 2


def test_sdk_fallbacks_are_rejected_before_transport(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path)
    from co_scientist import llm_free_policy

    monkeypatch.setattr(llm_free_policy.litellm, "model_fallbacks", ["other-model"])
    calls = []

    async def completion(**_kwargs):
        calls.append(True)
        return _tool_call_response(probe)

    monkeypatch.setattr(probe.litellm, "acompletion", completion)

    assert probe.main() == 1
    assert calls == []
    artifact = json.loads((tmp_path / "tool.json").read_text())
    assert (
        artifact["error"]
        == "Cloudflare tool qualification forbids SDK fallbacks and aliases"
    )


def test_artifact_path_is_exclusive(monkeypatch, tmp_path):
    probe = _probe(monkeypatch, tmp_path)
    Path(str(tmp_path / "tool.json")).write_text("keep")

    with pytest.raises(FileExistsError):
        probe.main()
    assert (tmp_path / "tool.json").read_text() == "keep"

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


FOLDER = Path(__file__).resolve().parent
SCRIPT = FOLDER / "probe_groq_free.py"
PREREG = FOLDER / "groq-free-qualification-prereg-v1.json"
SPEC = importlib.util.spec_from_file_location("probe_groq_free", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


def _set_env(monkeypatch, output: Path, *, model="groq/openai/gpt-oss-120b"):
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    monkeypatch.setenv("QUALIFICATION_PREREG", str(PREREG))
    monkeypatch.setenv(
        "QUALIFICATION_PREREG_SHA256",
        hashlib.sha256(PREREG.read_bytes()).hexdigest(),
    )
    monkeypatch.setenv(
        "QUALIFICATION_REVISION", "da2bf544243ee71caa424d7841e649b4e326a5e4"
    )
    monkeypatch.setenv("MODEL_NAME", model)


@pytest.mark.parametrize(
    "failure", ["wrong_model", "wrong_protocol_digest", "existing_output"]
)
def test_preflight_failures_never_load_provider_interfaces(
    monkeypatch, tmp_path, failure
):
    output = tmp_path / "attempt.json"
    _set_env(monkeypatch, output)
    if failure == "wrong_model":
        monkeypatch.setenv("MODEL_NAME", "groq/openai/other-model")
    elif failure == "wrong_protocol_digest":
        monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", "0" * 64)
    else:
        output.write_text("existing artifact")

    loaded = []
    monkeypatch.setattr(probe, "_load_interfaces", lambda: loaded.append(True))

    assert probe.main() != 0
    assert loaded == []
    if failure != "existing_output":
        assert not output.exists()


def test_first_failed_case_is_saved_and_stops_the_ordered_suite(monkeypatch, tmp_path):
    output = tmp_path / "attempt.json"
    protocol = json.loads(PREREG.read_text())
    context = {
        "output": output,
        "protocol": protocol,
        "prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
        "revision": "da2bf544243ee71caa424d7841e649b4e326a5e4",
    }
    monkeypatch.setattr(probe, "_preflight", lambda: context)

    calls = []

    async def fail_schema(*_args, **kwargs):
        calls.append(("schema", kwargs.get("max_attempts")))
        raise RuntimeError("schema request failed")

    async def unexpected(*_args, **_kwargs):
        calls.append(("later_case", None))
        raise AssertionError("later cases must not run")

    interfaces = SimpleNamespace(
        call_llm_json=fail_schema,
        CompletionSpec=lambda **values: SimpleNamespace(**values),
        LLMCallOptions=lambda **values: SimpleNamespace(**values),
        ToolLoop=object,
        call_llm_with_tools=unexpected,
        app_completion=unexpected,
        stream_chunks=unexpected,
        litellm=SimpleNamespace(
            acompletion=unexpected, model_fallbacks=[], model_alias_map={}
        ),
    )
    monkeypatch.setattr(probe, "_load_interfaces", lambda: interfaces)

    assert probe.main() == 1
    artifact = json.loads(output.read_text())
    assert calls == [("schema", 1)]
    assert [case["case"] for case in artifact["cases"]] == ["schema"]
    assert artifact["status"] == "failed"
    assert artifact["cases"][0]["passed"] is False
    assert artifact["cases"][0]["error_type"] == "RuntimeError"


def test_schema_case_rejects_empty_quote():
    async def answer(*_args, **_kwargs):
        return {"label": "supports", "quote": ""}

    api = SimpleNamespace(
        call_llm_json=answer,
        CompletionSpec=lambda **values: SimpleNamespace(**values),
        LLMCallOptions=lambda **values: SimpleNamespace(**values),
    )
    import asyncio

    assert asyncio.run(probe._schema(api))["passed"] is False


def test_long_prompt_case_builds_its_fixed_public_input():
    async def answer(prompt, *_args, **_kwargs):
        assert len(prompt) == 8000
        return {
            "label": "supports",
            "quote": "The final control-A reading was 137 synthetic units.",
        }

    api = SimpleNamespace(
        call_llm_json=answer,
        CompletionSpec=lambda **values: SimpleNamespace(**values),
        LLMCallOptions=lambda **values: SimpleNamespace(**values),
    )
    import asyncio

    assert asyncio.run(probe._long_prompt(api))["passed"] is True

"""Offline CLI-boundary checks for qualification probe terminal errors."""

from __future__ import annotations

import contextlib
import json
import runpy
import sys
import types
from pathlib import Path

import pytest


FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parents[3]


def _module(name: str, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _env(monkeypatch, output: Path, **extra):
    values = {
        "MODEL_NAME": "openrouter/test-model",
        "OPENROUTER_API_KEY": "test-key",
        "QUALIFICATION_OUTPUT": str(output),
        "QUALIFICATION_REVISION": "test-revision",
        "QUALIFICATION_TRIAL": "1",
    }
    values.update(extra)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _run(monkeypatch, script: Path, modules: dict[str, types.ModuleType]):
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(script), run_name="__main__")
    return exc_info.value.code


def _capability_modules(
    monkeypatch, calls, *, failure=None, low_quality=False, eligibility_failure=None
):
    async def call_llm_json(*_args, **_kwargs):
        calls.append("json")
        if failure is not None:
            raise failure
        if low_quality:
            return {"label": "contradicts", "quote": "unrelated"}
        return {
            "label": "supports",
            "quote": "Treatment X reduced cell viability by 30% relative to vehicle.",
        }

    @contextlib.contextmanager
    def capture_usage(*_args, **_kwargs):
        yield {"physical_calls": 1}

    def verify_model(*_args):
        if eligibility_failure is not None:
            raise eligibility_failure

    return {
        "evaluations._live_config": _module(
            "evaluations._live_config",
            configure_live_environment=lambda: "openrouter/test-model",
        ),
        "co_scientist.llm": _module(
            "co_scientist.llm",
            CompletionSpec=lambda **kwargs: types.SimpleNamespace(**kwargs),
            LLMCallOptions=lambda **kwargs: types.SimpleNamespace(**kwargs),
            call_llm_json=call_llm_json,
        ),
        "co_scientist.llm_tool_loop": _module(
            "co_scientist.llm_tool_loop",
            ToolLoop=object,
            call_llm_with_tools=None,
        ),
        "co_scientist.llm_free_catalog": _module(
            "co_scientist.llm_free_catalog",
            current_catalog=lambda: {"test-model": {}},
            verify_model=verify_model,
        ),
        "evaluations._usage_evidence": _module(
            "evaluations._usage_evidence", capture_usage=capture_usage
        ),
        "litellm": _module("litellm", acompletion=None),
    }


def test_capabilities_low_quality_is_recorded_and_exits_zero(monkeypatch, tmp_path):
    output = tmp_path / "capabilities.json"
    calls = []
    _env(monkeypatch, output, QUALIFICATION_CASES="json_off")

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls, low_quality=True),
    )

    record = json.loads(output.read_text())
    assert status == 0
    assert calls == ["json"]
    assert len(record["cases"]) == 1
    assert record["cases"][0]["passed"] is False
    assert "error_type" not in record["cases"][0]


def test_bounded_capabilities_stop_on_low_quality(monkeypatch, tmp_path):
    output = tmp_path / "bounded-low-quality.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on",
        QUALIFICATION_BOUNDED_PANEL="1",
    )

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls, low_quality=True),
    )

    record = json.loads(output.read_text())
    assert status == 1
    assert calls == ["json"]
    assert len(record["cases"]) == 1
    assert record["cases"][0]["passed"] is False


def test_bounded_capabilities_allow_one_json_physical_call(monkeypatch, tmp_path):
    output = tmp_path / "bounded-physical.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off",
        QUALIFICATION_BOUNDED_PANEL="1",
    )
    modules = _capability_modules(monkeypatch, calls)

    async def transport(**_kwargs):
        calls.append("transport")
        return object()

    async def double_call(*_args, **_kwargs):
        import litellm

        await litellm.acompletion(model="openrouter/test-model")
        await litellm.acompletion(model="openrouter/test-model")
        return {
            "label": "supports",
            "quote": "Treatment X reduced cell viability by 30% relative to vehicle.",
        }

    modules["litellm"].acompletion = transport
    modules["co_scientist.llm"].call_llm_json = double_call
    status = _run(monkeypatch, FOLDER / "probe_capabilities.py", modules)

    record = json.loads(output.read_text())
    assert status == 1
    assert calls == ["transport"]
    assert record["cases"][0]["error_type"] == "RuntimeError"
    assert len(record["cases"][0]["physical_request_controls"]) == 1


def test_plain_json_accepts_case_variant_when_prompt_has_no_enum(monkeypatch, tmp_path):
    output = tmp_path / "plain-json-case.json"
    calls = []
    _env(monkeypatch, output, QUALIFICATION_CASES="plain_json", QUALIFICATION_BOUNDED_PANEL="1")
    modules = _capability_modules(monkeypatch, calls)

    async def case_variant(*_args, **_kwargs):
        calls.append("json")
        return {
            "label": "Supports",
            "quote": "Treatment X reduced cell viability by 30% relative to vehicle.",
        }

    modules["co_scientist.llm"].call_llm_json = case_variant
    status = _run(monkeypatch, FOLDER / "probe_capabilities.py", modules)

    assert status == 0
    assert calls == ["json"]
    assert json.loads(output.read_text())["cases"][0]["passed"] is True


def test_capabilities_terminal_error_is_retained_and_stops_later_cases(
    monkeypatch, tmp_path
):
    output = tmp_path / "capabilities-error.json"
    calls = []
    _env(monkeypatch, output, QUALIFICATION_CASES="json_off,json_on")

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls, failure=RuntimeError("route 404")),
    )

    record = json.loads(output.read_text())
    assert status == 1
    assert calls == ["json"]
    assert len(record["cases"]) == 1
    assert record["cases"][0]["error_type"] == "RuntimeError"
    assert "route 404" in record["cases"][0]["error"]


def test_capabilities_eligibility_error_is_retained_before_provider_call(
    monkeypatch, tmp_path
):
    output = tmp_path / "capabilities-eligibility-error.json"
    calls = []
    _env(monkeypatch, output, QUALIFICATION_CASES="json_off")

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(
            monkeypatch,
            calls,
            eligibility_failure=RuntimeError("catalog route unavailable"),
        ),
    )

    record = json.loads(output.read_text())
    assert status == 1
    assert calls == []
    assert len(record["cases"]) == 1
    assert record["cases"][0]["error_type"] == "RuntimeError"
    assert "catalog route unavailable" in record["cases"][0]["error"]


def test_capabilities_tool_probe_allows_only_one_tool_round_trip(monkeypatch, tmp_path):
    output = tmp_path / "tool-probe.json"
    calls = []
    _env(monkeypatch, output, QUALIFICATION_CASES="tools")
    modules = _capability_modules(monkeypatch, calls)

    async def call_with_tools(_prompt, _spec, loop, _options):
        assert loop.max_iterations == 1
        call = types.SimpleNamespace(
            id="call-1",
            function=types.SimpleNamespace(
                name="lookup_measurement",
                arguments='{"sample":"control-A"}',
            ),
        )
        await loop.executor(call)
        return "137", []

    modules["co_scientist.llm_tool_loop"] = _module(
        "co_scientist.llm_tool_loop",
        ToolLoop=lambda **kwargs: types.SimpleNamespace(**kwargs),
        call_llm_with_tools=call_with_tools,
    )
    assert _run(monkeypatch, FOLDER / "probe_capabilities.py", modules) == 0
    assert json.loads(output.read_text())["cases"][0]["passed"] is True


def _citation_modules(
    *, report=None, failure=None, source_error=None, eligibility_failure=None
):
    def run(**_kwargs):
        if failure is not None:
            raise failure
        return report

    def imported_sources(*_args):
        if source_error is not None:
            raise source_error
        return {}

    def verify_model(*_args):
        if eligibility_failure is not None:
            raise eligibility_failure

    return {
        "evaluations": _module("evaluations", __path__=[]),
        "litellm": _module("litellm", acompletion=None),
        "evaluations.citation_eval": _module(
            "evaluations.citation_eval",
            _build_llm_assessor=lambda: None,
            run=run,
        ),
        "qualification_sources": _module(
            "qualification_sources", imported_sources=imported_sources
        ),
        "co_scientist.llm_free_catalog": _module(
            "co_scientist.llm_free_catalog",
            current_catalog=lambda: {"test-model": {}},
            verify_model=verify_model,
        ),
    }


def test_citation_completed_low_quality_report_is_retained_and_exits_zero(
    monkeypatch, tmp_path
):
    output = tmp_path / "citation-low-quality.json"
    _env(monkeypatch, output, QUALIFICATION_ROOT=str(ROOT))
    report = {
        "metrics": {"accuracy": 0.1},
        "production_gates": {"passed": False},
    }

    status = _run(
        monkeypatch,
        FOLDER / "probe_citation_panel.py",
        _citation_modules(report=report),
    )

    record = json.loads(output.read_text())
    assert status == 0
    assert "error_type" not in record
    assert record["report"] == report


def test_citation_execution_error_is_retained_and_exits_nonzero(monkeypatch, tmp_path):
    output = tmp_path / "citation-error.json"
    _env(monkeypatch, output, QUALIFICATION_ROOT=str(ROOT))

    status = _run(
        monkeypatch,
        FOLDER / "probe_citation_panel.py",
        _citation_modules(failure=RuntimeError("provider route failed")),
    )

    record = json.loads(output.read_text())
    assert status == 1
    assert record["error_type"] == "RuntimeError"
    assert "provider route failed" in record["error"]


def test_citation_eligibility_error_is_retained_without_a_key(monkeypatch, tmp_path):
    output = tmp_path / "citation-eligibility-error.json"
    _env(monkeypatch, output, QUALIFICATION_ROOT=str(ROOT))
    monkeypatch.delenv("OPENROUTER_API_KEY")

    status = _run(
        monkeypatch,
        FOLDER / "probe_citation_panel.py",
        _citation_modules(
            eligibility_failure=RuntimeError("catalog route unavailable")
        ),
    )

    record = json.loads(output.read_text())
    assert status == 1
    assert record["error_type"] == "RuntimeError"
    assert "catalog route unavailable" in record["error"]


def test_citation_postrun_sourceguard_error_is_retained_and_exits_nonzero(
    monkeypatch, tmp_path
):
    output = tmp_path / "citation-sourceguard-error.json"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "arms": {
                    "baseline": {
                        "subtree_revisions": {"app": "test-revision"},
                        "verified_sources": {},
                    }
                }
            }
        )
    )
    _env(
        monkeypatch,
        output,
        QUALIFICATION_ROOT=str(ROOT),
        QUALIFICATION_MANIFEST=str(manifest),
        QUALIFICATION_ARM="baseline",
    )
    report = {
        "metrics": {"accuracy": 1.0},
        "production_gates": {"passed": True},
    }

    status = _run(
        monkeypatch,
        FOLDER / "probe_citation_panel.py",
        _citation_modules(
            report=report, source_error=RuntimeError("source guard drift")
        ),
    )

    record = json.loads(output.read_text())
    assert status == 1
    assert record["error_type"] == "RuntimeError"
    assert "source guard drift" in record["error"]
    assert record["report"] == report

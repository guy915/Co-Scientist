"""Offline CLI-boundary checks for qualification probe terminal errors."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib
import json
import os
import runpy
import subprocess
import sys
import types
from pathlib import Path

import pytest


FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parents[3]
REQUEST_CONTROLS = {
    "only": ["novita"],
    "zdr": True,
    "data_collection": "deny",
    "require_parameters": True,
    "max_price": {"prompt": 0, "completion": 0, "request": 0},
    "allow_fallbacks": False,
}
OBSERVED_PROVIDER_CONTROLS = {
    **REQUEST_CONTROLS,
    "preferred_min_throughput": 25,
}


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
        "QUALIFICATION_REVISION": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "QUALIFICATION_TRIAL": "1",
    }
    values.update(extra)
    if values.get("QUALIFICATION_BOUNDED_PANEL") == "1":
        prereg = _write_prereg(output)
        values.setdefault("QUALIFICATION_PREREG", str(prereg))
        values.setdefault("QUALIFICATION_PREREG_SHA256", _sha256(prereg))
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_prereg(output: Path) -> Path:
    model = "openrouter/test-model"
    cases = ["json_off", "json_on", "plain_json", "tools", "streaming", "long_json"]
    probe_path = FOLDER / "probe_capabilities.py"
    prereg = output.with_suffix(".prereg.json")
    prereg.write_text(
        json.dumps(
            {
                "candidate": {
                    "model": model,
                    "accepted_response_model_ids": [model, "test-model"],
                    "request_controls": REQUEST_CONTROLS,
                },
                "source_sha256": {
                    str(probe_path.relative_to(ROOT)): _sha256(probe_path),
                    "references/external/baseline/model-qualification/historical-negative-controls.json": (
                        _sha256(FOLDER / "historical-negative-controls.json")
                    ),
                },
                "execution": {"artifact_patterns": {"interface": str(output)}},
                "interface_stage": {
                    "cases_in_order": cases,
                    "environment": {
                        "QUALIFICATION_REVISION": "current committed HEAD at launch"
                    },
                    "physical_call_caps_per_case": {
                        "json_off": 1,
                        "json_on": 1,
                        "plain_json": 1,
                        "tools": 2,
                        "streaming": 1,
                        "long_json": 1,
                    },
                    "total_physical_call_cap": 7,
                },
            }
        )
        + "\n"
    )
    return prereg


def _run(monkeypatch, script: Path, modules: dict[str, types.ModuleType]):
    importlib.import_module(
        "co_scientist.llm_call_budget"
    )  # Preload before fake LiteLLM.

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(script), run_name="__main__")
    return exc_info.value.code


def _capability_modules(
    monkeypatch,
    calls,
    *,
    failure=None,
    low_quality=False,
    eligibility_failure=None,
    missing_usage=None,
    request_provider=None,
    tools_requests=1,
):
    async def call_llm_json(*_args, **_kwargs):
        calls.append("json")
        import litellm

        await litellm.acompletion(
            model="openrouter/test-model",
            max_tokens=6000,
            extra_body={
                "provider": (
                    request_provider
                    if request_provider is not None
                    else OBSERVED_PROVIDER_CONTROLS
                )
            },
        )
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
        evidence = {"physical_calls": 1}
        if not missing_usage:
            evidence["usage_evidence"] = {
                "model_usage": {
                    "json_off::openrouter/test-model": {
                        "calls": 1,
                        "observed_model_calls": int(missing_usage != "served_model"),
                        "reported_usage_calls": int(missing_usage != "token_usage"),
                        "requested_models": {"openrouter/test-model": 1},
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "errors": {},
                        "deterministic_fallbacks": {},
                    }
                },
                "physical_calls": 1,
                "observed_models": ["openrouter/test-model"],
                "unobserved_model_calls": 0,
                "unreported_usage_calls": 0,
                "recorded_deterministic_fallbacks": {},
                "has_usage_records": True,
            }
        yield evidence

    def verify_model(*_args):
        if eligibility_failure is not None:
            raise eligibility_failure

    async def synthetic_transport(**_kwargs):
        return types.SimpleNamespace(
            model="test-model",
            usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )

    async def call_with_tools(_prompt, _spec, loop, _options):
        import litellm

        for _ in range(tools_requests):
            await litellm.acompletion(
                model="openrouter/test-model",
                extra_body={"provider": OBSERVED_PROVIDER_CONTROLS},
            )
        call = types.SimpleNamespace(
            id="call-1",
            function=types.SimpleNamespace(
                name="lookup_measurement", arguments='{"sample":"control-A"}'
            ),
        )
        await loop.executor(call)
        return "137", []

    async def streaming_completion(**_kwargs):
        import litellm

        await litellm.acompletion(**_kwargs)
        return object()

    async def stream_chunks(_response, **_kwargs):
        yield types.SimpleNamespace(
            model="test-model",
            usage=types.SimpleNamespace(
                model_dump=lambda: {"prompt_tokens": 10, "completion_tokens": 5}
            ),
            choices=[
                types.SimpleNamespace(
                    finish_reason="stop",
                    delta=types.SimpleNamespace(
                        content="Clinical benefit is unproven."
                    ),
                )
            ],
        )

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
            ToolLoop=lambda **kwargs: types.SimpleNamespace(**kwargs),
            call_llm_with_tools=call_with_tools,
        ),
        "co_scientist.llm_free_catalog": _module(
            "co_scientist.llm_free_catalog",
            current_catalog=lambda: {"test-model": {}},
            verify_model=verify_model,
        ),
        "evaluations._usage_evidence": _module(
            "evaluations._usage_evidence", capture_usage=capture_usage
        ),
        "litellm": _module("litellm", acompletion=synthetic_transport),
        "app.llm_request": _module("app.llm_request", acompletion=streaming_completion),
        "app.llm_stream": _module("app.llm_stream", stream_chunks=stream_chunks),
        "app.config": _module(
            "app.config",
            deepseek_thinking_kwargs=lambda *_args, **_kwargs: {
                "extra_body": {"provider": OBSERVED_PROVIDER_CONTROLS}
            },
            thinking_safe_max_tokens=lambda _model, fallback: fallback,
        ),
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
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
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
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )
    modules = _capability_modules(monkeypatch, calls)

    async def transport(**_kwargs):
        calls.append("transport")
        return object()

    async def double_call(*_args, **_kwargs):
        import litellm

        await litellm.acompletion(
            model="openrouter/test-model",
            extra_body={"provider": OBSERVED_PROVIDER_CONTROLS},
        )
        await litellm.acompletion(
            model="openrouter/test-model",
            extra_body={"provider": OBSERVED_PROVIDER_CONTROLS},
        )
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
    assert record["cases"][0]["error_type"] == "QualificationGuardError"
    assert len(record["cases"][0]["physical_request_controls"]) == 1
    assert len(record["cases"][0]["qualification_guard_rejections"]) == 1


@pytest.mark.parametrize(
    "request_provider",
    [
        {"only": ["other-provider"]},
        {**OBSERVED_PROVIDER_CONTROLS, "order": ["novita"]},
    ],
)
def test_bounded_capabilities_stop_on_unregistered_provider_route(
    monkeypatch, tmp_path, request_provider
):
    output = tmp_path / "bounded-route.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )
    modules = _capability_modules(monkeypatch, calls, request_provider=request_provider)
    transport_calls = []
    transport = modules["litellm"].acompletion

    async def tracked_transport(**kwargs):
        transport_calls.append(kwargs)
        return await transport(**kwargs)

    modules["litellm"].acompletion = tracked_transport

    status = _run(monkeypatch, FOLDER / "probe_capabilities.py", modules)

    record = json.loads(output.read_text())
    assert status == 1
    assert calls == ["json"]
    assert transport_calls == []
    assert len(record["cases"]) == 1
    assert record["cases"][0]["error_type"] == "QualificationGuardError"
    assert "provider route" in record["cases"][0]["error"]
    assert len(record["cases"][0]["qualification_guard_rejections"]) == 1


def test_bounded_capabilities_allow_pinned_route_throughput_preference(
    monkeypatch, tmp_path
):
    output = tmp_path / "bounded-throughput.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls),
    )

    record = json.loads(output.read_text())
    assert status == 0
    assert [case["case"] for case in record["cases"]] == [
        "json_off",
        "json_on",
        "plain_json",
        "tools",
        "streaming",
        "long_json",
    ]
    assert all(case["passed"] for case in record["cases"])
    assert all(
        request["extra_body"]["provider"]["preferred_min_throughput"] == 25
        for case in record["cases"]
        for request in case["physical_request_controls"]
    )


def test_bounded_capabilities_stop_at_preregistered_per_case_cap(monkeypatch, tmp_path):
    output = tmp_path / "bounded-case-cap.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )
    prereg_path = Path(os.environ["QUALIFICATION_PREREG"])
    prereg = json.loads(prereg_path.read_text())
    prereg["interface_stage"]["physical_call_caps_per_case"]["tools"] = 1
    prereg_path.write_text(json.dumps(prereg))
    monkeypatch.setenv("QUALIFICATION_PREREG_SHA256", _sha256(prereg_path))
    modules = _capability_modules(monkeypatch, calls, tools_requests=2)
    transport_calls = []
    transport = modules["litellm"].acompletion

    async def tracked_transport(**kwargs):
        transport_calls.append(kwargs)
        return await transport(**kwargs)

    modules["litellm"].acompletion = tracked_transport

    status = _run(monkeypatch, FOLDER / "probe_capabilities.py", modules)

    record = json.loads(output.read_text())
    assert status == 1
    assert calls == ["json", "json", "json"]
    assert [case["case"] for case in record["cases"]] == [
        "json_off",
        "json_on",
        "plain_json",
        "tools",
    ]
    assert record["cases"][-1]["error_type"] == "QualificationGuardError"
    assert "physical-call cap" in record["cases"][-1]["error"]
    assert len(record["cases"][-1]["physical_request_controls"]) == 1
    assert len(record["cases"][-1]["qualification_guard_rejections"]) == 1
    assert len(transport_calls) == 4


def test_bounded_capabilities_reject_reversed_cases_before_transport(
    monkeypatch, tmp_path
):
    output = tmp_path / "bounded-reversed-cases.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="long_json,streaming,tools,plain_json,json_on,json_off",
        QUALIFICATION_BOUNDED_PANEL="1",
    )

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls),
    )

    assert status == 1
    assert calls == []
    assert not output.exists()


def test_plain_json_accepts_case_variant_when_prompt_has_no_enum(monkeypatch, tmp_path):
    output = tmp_path / "plain-json-case.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="plain_json",
    )
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


def test_unknown_capability_case_fails_before_transport(monkeypatch, tmp_path):
    output = tmp_path / "unknown-case.json"
    calls = []
    _env(monkeypatch, output, QUALIFICATION_CASES="json_off,not_a_case")

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls),
    )

    assert status == 1
    assert calls == []
    assert not output.exists()


def test_capabilities_refuse_existing_output_before_transport(monkeypatch, tmp_path):
    output = tmp_path / "existing-capabilities.json"
    output.write_text("original")
    calls = []
    _env(monkeypatch, output, QUALIFICATION_CASES="json_off")

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls),
    )

    assert status == 1
    assert calls == []
    assert output.read_text() == "original"


@pytest.mark.parametrize("missing_usage", [True, "served_model", "token_usage"])
def test_bounded_capabilities_missing_usage_evidence_stops_panel(
    monkeypatch, tmp_path, missing_usage
):
    output = tmp_path / "bounded-missing-usage.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls, missing_usage=missing_usage),
    )

    record = json.loads(output.read_text())
    assert status == 1
    assert calls == ["json"]
    assert len(record["cases"]) == 1
    assert record["cases"][0]["passed"] is False
    assert record["cases"][0]["error_type"] == "MissingUsageEvidence"


def test_bounded_capabilities_require_preregistration(monkeypatch, tmp_path):
    output = tmp_path / "bounded-no-prereg.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )
    monkeypatch.delenv("QUALIFICATION_PREREG")

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls),
    )

    assert status == 1
    assert calls == []
    assert not output.exists()


def test_bounded_capabilities_require_preregistration_digest(monkeypatch, tmp_path):
    output = tmp_path / "bounded-no-prereg-digest.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )
    monkeypatch.delenv("QUALIFICATION_PREREG_SHA256")

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls),
    )

    assert status == 1
    assert calls == []
    assert not output.exists()


def test_bounded_capabilities_reject_tampered_prereg_even_with_matching_model(
    monkeypatch, tmp_path
):
    output = tmp_path / "bounded-tampered-prereg.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )
    prereg_path = Path(os.environ["QUALIFICATION_PREREG"])
    prereg = json.loads(prereg_path.read_text())
    tampered_model = "openrouter/tampered-model"
    prereg["candidate"]["model"] = tampered_model
    prereg["candidate"]["accepted_response_model_ids"] = [
        tampered_model,
        "tampered-model",
    ]
    prereg_path.write_text(json.dumps(prereg))
    monkeypatch.setenv("MODEL_NAME", tampered_model)
    modules = _capability_modules(monkeypatch, calls)
    modules["evaluations._live_config"].configure_live_environment = lambda: (
        tampered_model
    )

    status = _run(monkeypatch, FOLDER / "probe_capabilities.py", modules)

    assert status == 1
    assert calls == []
    assert not output.exists()


@pytest.mark.parametrize("drift", ["probe", "input"])
def test_bounded_capabilities_reject_pinned_source_drift(monkeypatch, tmp_path, drift):
    output = tmp_path / f"bounded-source-drift-{drift}.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )
    prereg = Path(os.environ["QUALIFICATION_PREREG"])
    payload = json.loads(prereg.read_text())
    source = (
        "references/external/baseline/model-qualification/probe_capabilities.py"
        if drift == "probe"
        else "references/external/baseline/model-qualification/historical-negative-controls.json"
    )
    payload["source_sha256"][source] = "0" * 64
    prereg.write_text(json.dumps(payload))

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls),
    )

    assert status == 1
    assert calls == []
    assert not output.exists()


@pytest.mark.parametrize("drift", ["model", "case_order", "output", "revision"])
def test_bounded_capabilities_reject_preregistration_drift(
    monkeypatch, tmp_path, drift
):
    output = tmp_path / f"bounded-prereg-drift-{drift}.json"
    calls = []
    _env(
        monkeypatch,
        output,
        QUALIFICATION_CASES="json_off,json_on,plain_json,tools,streaming,long_json",
        QUALIFICATION_BOUNDED_PANEL="1",
    )
    prereg = Path(os.environ["QUALIFICATION_PREREG"])
    payload = json.loads(prereg.read_text())
    if drift == "model":
        payload["candidate"]["model"] = "openrouter/another-model"
    elif drift == "case_order":
        payload["interface_stage"]["cases_in_order"].reverse()
    elif drift == "output":
        payload["execution"]["artifact_patterns"]["interface"] = str(
            output.with_name("somewhere-else.json")
        )
    else:
        monkeypatch.setenv("QUALIFICATION_REVISION", "stale-revision")
    prereg.write_text(json.dumps(payload))

    status = _run(
        monkeypatch,
        FOLDER / "probe_capabilities.py",
        _capability_modules(monkeypatch, calls),
    )

    assert status == 1
    assert calls == []
    assert not output.exists()


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


def test_citation_refuses_existing_artifact_before_admission(monkeypatch, tmp_path):
    output = tmp_path / "citation-existing.json"
    output.write_text("original")
    _env(monkeypatch, output, QUALIFICATION_ROOT=str(ROOT))
    modules = _citation_modules(eligibility_failure=AssertionError("admission ran"))

    with pytest.raises(FileExistsError):
        _run(monkeypatch, FOLDER / "probe_citation_panel.py", modules)

    assert output.read_text() == "original"


def test_citation_stops_at_physical_request_ceiling(monkeypatch, tmp_path):
    from co_scientist.llm_call_budget import record_provider_request

    output = tmp_path / "citation-budget.json"
    _env(monkeypatch, output, QUALIFICATION_ROOT=str(ROOT))
    modules = _citation_modules()

    def run(**_kwargs):
        for _ in range(81):
            record_provider_request()

    modules["evaluations.citation_eval"].run = run
    assert _run(monkeypatch, FOLDER / "probe_citation_panel.py", modules) == 1
    assert json.loads(output.read_text())["error_type"] == "LLMCallBudgetExceededError"


def test_citation_records_failed_physical_attempt_without_secret(monkeypatch):
    importlib.import_module("co_scientist.llm_call_budget")
    modules = _citation_modules()

    async def failed_transport(**_kwargs):
        raise RuntimeError("route failed with test-key")

    modules["litellm"].acompletion = failed_transport
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    probe = runpy.run_path(
        str(FOLDER / "probe_citation_panel.py"), run_name="probe_test"
    )

    with pytest.raises(RuntimeError):
        asyncio.run(probe["observed_transport"](model="test-model", messages=[]))

    assert probe["_REQUESTS"][0]["error_type"] == "RuntimeError"
    assert probe["_REQUESTS"][0]["error"] == "route failed with [redacted]"


def test_usefulness_stops_at_physical_request_ceiling(monkeypatch, tmp_path):
    from co_scientist.llm_call_budget import record_provider_request

    output = tmp_path / "usefulness-budget.json"
    _env(monkeypatch, output, QUALIFICATION_PANEL="usefulness")

    def run_llm(*_args):
        for _ in range(21):
            record_provider_request()

    observer = _module(
        "probe_citation_panel",
        digest=lambda _path: "test-sha",
        litellm=types.SimpleNamespace(acompletion=None),
        observed_transport=lambda **_kwargs: None,
        _REQUESTS=[],
    )
    observer.__file__ = str(FOLDER / "probe_citation_panel.py")
    modules = {
        "evaluations._live_config": _module(
            "evaluations._live_config",
            configure_live_environment=lambda: "openrouter/test-model",
        ),
        "co_scientist.llm_free_catalog": _module(
            "co_scientist.llm_free_catalog",
            current_catalog=lambda: {"test-model": {}},
            verify_model=lambda *_args: None,
        ),
        "probe_citation_panel": observer,
        "evaluations.citation_usefulness_eval": _module(
            "evaluations.citation_usefulness_eval",
            load_dataset=lambda: {},
            run_llm=run_llm,
        ),
    }
    assert _run(monkeypatch, FOLDER / "probe_remaining_panel.py", modules) == 1
    assert json.loads(output.read_text())["error_type"] == "LLMCallBudgetExceededError"


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

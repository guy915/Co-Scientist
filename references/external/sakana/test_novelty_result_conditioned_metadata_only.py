"""Offline checks for the prospective metadata-only search study."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import novelty_result_conditioned_pilot as pilot
from test_novelty_result_conditioned_batch_pilot import (
    BatchTraceClient,
    _registry,
)
from test_novelty_result_conditioned_pilot import FakeMCPClient, MODEL

_MISSING = object()


def _bank(study_version: int) -> dict[str, Any]:
    registration = pilot._study_registration(study_version)
    return {
        "version": registration.fixture_bank_version,
        "status": registration.fixture_bank_status,
        "cases_in_fixed_order": [
            {
                "id": f"synthetic-{index}",
                "positive": {
                    "target_pmid": str(70000001 + index * 2),
                    "draft": f"positive synthetic draft {index}",
                },
                "distinct_control": {
                    "anchor_pmid": str(70000002 + index * 2),
                    "draft": f"control synthetic draft {index}",
                },
            }
            for index in range(pilot.PAIR_COUNT)
        ],
    }


def _install_runner_stubs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    study_version: int,
) -> dict[str, Any]:
    registration = pilot._study_registration(study_version)
    bank = _bank(study_version)
    protocol = {
        "model_name": MODEL,
        "mcp_build_id": "offline-build",
        "study_version": study_version,
        "protocol_version": registration.protocol_version,
        "fixture_bank_version": registration.fixture_bank_version,
        "fixture_bank_path": registration.fixture_bank_path,
        "fixture_bank_sha256": "offline-fixture-bank-hash",
        "query_output_format": registration.query_output_format,
    }
    if study_version == 8:
        protocol["search_parameters"] = {"include_fulltext": False}
    protocol_path = tmp_path / f"protocol-v{study_version}.json"
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    protocol_constant = (
        "PILOT_PREREG" if study_version == 1 else f"PILOT_PREREG_V{study_version}"
    )
    monkeypatch.setattr(pilot, protocol_constant, protocol_path)
    monkeypatch.setattr(pilot, "_load_pilot_protocol", lambda *_a, **_kw: protocol)
    monkeypatch.setattr(pilot, "_load_fixture_bank", lambda *_a, **_kw: bank)
    serving_process = {
        "pid": 123,
        "listener_address": "127.0.0.1:8123",
        "source_path": str(pilot.ROOT / "engine/mcp_server/server.py"),
        "mcp_tree": "offline-build",
        "metadata_batching": {"enabled": True},
    }
    monkeypatch.setattr(
        pilot,
        "_check_runtime",
        lambda *_a, cache_root, **_kw: (
            "http://127.0.0.1:8123/mcp",
            cache_root,
            "offline-build",
            serving_process,
        ),
    )
    monkeypatch.setattr(pilot, "_require_same_serving_process", lambda *_a, **_kw: None)

    async def generate_query(
        _prompt: str,
        *,
        event: dict[str, Any],
        model_name: str,
        **_kwargs: Any,
    ) -> str:
        event.update(
            {
                "served_model": model_name,
                "provider_calls": 1,
                "observed_model_calls": 1,
                "retries": 0,
                "cache_hits": 0,
                "telemetry": {},
            }
        )
        return "offline PubMed query"

    monkeypatch.setattr(pilot, "_generate_query", generate_query)
    return bank


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    study_version: int,
    client: Any,
) -> dict[str, Any]:
    bank = _install_runner_stubs(tmp_path, monkeypatch, study_version)
    cache_root = tmp_path / "empty-cache"
    cache_root.mkdir(exist_ok=True)
    return asyncio.run(
        pilot.run_pilot(
            bank,
            _registry(),
            client,
            cache_root,
            tmp_path / "result.json",
            tmp_path / "blind.json",
            expected_build_id="offline-build",
            model_name=MODEL,
            model_api_key="offline-test-key",
            study_version=study_version,
        )
    )


def test_study8_registration_is_distinct_and_keeps_the_study7_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration = pilot._study_registration(8)

    assert pilot._parse_args(["--study-version", "8"]).study_version == 8
    assert (
        registration.protocol_version,
        registration.fixture_bank_version,
        registration.fixture_bank_path,
        registration.requires_raw_trace,
        registration.requires_batch_metadata,
        registration.query_output_format,
    ) == (
        8,
        9,
        "references/external/sakana/novelty-fixture-bank-prereg-v9.json",
        True,
        True,
        pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
    )
    assert pilot._protocol_path(8) == pilot.PILOT_PREREG_V8
    assert pilot._study_registration(7).fixture_bank_version == 8
    assert (
        pilot._study_registration(7).query_output_format
        == registration.query_output_format
    )
    assert (pilot.MODEL_CALL_LIMIT, pilot.OUTER_MCP_CALL_LIMIT) == (24, 36)

    monkeypatch.setattr(pilot, "RESULT_DIR", tmp_path)
    result_path, blind_path = pilot._new_output_paths(8)
    assert result_path.name.startswith("novelty-result-conditioned-pilot-v8-")
    assert "cosci-m12-nov-04b4j3-v8-blind-" in blind_path.name


def test_study8_sends_metadata_only_parameter_through_public_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "empty-cache"
    cache_root.mkdir()
    client = BatchTraceClient(cache_root, response_pmc_id="12345")
    report = _run(tmp_path, monkeypatch, 8, client)

    assert report["status"] == "PILOT_COMPLETE_LABELS_PENDING"
    assert report["model_call_count"] == pilot.MODEL_CALL_LIMIT == 24
    assert report["outer_mcp_call_count"] == pilot.OUTER_MCP_CALL_LIMIT == 36
    assert len(client.calls) == pilot.OUTER_MCP_CALL_LIMIT
    assert all(
        tool_name == "pubmed_search_with_fulltext"
        and params["include_fulltext"] is False
        for tool_name, params in client.calls
    )
    assert all(
        list(params) == ["query", "max_papers", "slug", "run_id", "include_fulltext"]
        for _, params in client.calls
    )
    assert all(
        params["max_papers"] == pilot.MAX_PAPERS and params["slug"] == params["run_id"]
        for _, params in client.calls
    )
    assert report["query_output_format"] == pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT


@pytest.mark.parametrize("study_version", range(1, 8))
def test_historical_studies_keep_the_exact_default_transport_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    study_version: int,
) -> None:
    cache_root = tmp_path / "empty-cache"
    client = FakeMCPClient(cache_root, [], fail_on_call=1)
    _run(tmp_path, monkeypatch, study_version, client)

    assert len(client.calls) == 1
    tool_name, params = client.calls[0]
    assert tool_name == "pubmed_search_with_fulltext"
    assert list(params) == ["query", "max_papers", "slug", "run_id"]
    assert (
        params["query"]
        == _bank(study_version)["cases_in_fixed_order"][0]["positive"]["draft"]
    )
    assert params["max_papers"] == pilot.MAX_PAPERS
    assert params["slug"] == params["run_id"]


def _write_offline_study8_protocol(tmp_path: Path) -> tuple[Path, Path]:
    registration = pilot._study_registration(8)
    bank_path = tmp_path / "offline-bank-v9.json"
    bank_bytes = json.dumps(
        {
            "version": registration.fixture_bank_version,
            "status": pilot.OFFLINE_PREFLIGHT_BANK_STATUS,
            "cases_in_fixed_order": [],
        },
        sort_keys=True,
    ).encode()
    bank_path.write_bytes(bank_bytes)
    static_prompt, conditioned_prompt = pilot._query_prompt_templates(
        pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT
    )
    protocol = {
        "status": pilot.OFFLINE_PREFLIGHT_BANK_STATUS,
        "study_version": 8,
        "protocol_version": registration.protocol_version,
        "fixture_bank_version": registration.fixture_bank_version,
        "fixture_bank_path": registration.fixture_bank_path,
        "fixture_bank_sha256": hashlib.sha256(bank_bytes).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(pilot.__file__).read_bytes()).hexdigest(),
        "static_prompt_sha256": hashlib.sha256(static_prompt.encode()).hexdigest(),
        "conditioned_prompt_sha256": hashlib.sha256(
            conditioned_prompt.encode()
        ).hexdigest(),
        "request_config": pilot.MODEL_REQUEST_CONFIG,
        "model_boundary_sha256": pilot._model_boundary_hashes(8),
        "batch_trace_source_sha256": pilot._batch_trace_source_hashes(),
        "max_outer_mcp_calls": pilot.OUTER_MCP_CALL_LIMIT,
        "max_model_calls": pilot.MODEL_CALL_LIMIT,
        "model_name": MODEL,
        "query_output_format": pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
        "search_parameters": {"include_fulltext": False},
    }
    protocol_path = tmp_path / "offline-protocol-v8.json"
    protocol_path.write_text(json.dumps(protocol, sort_keys=True), encoding="utf-8")
    return protocol_path, bank_path


def test_study8_protocol_loader_accepts_the_frozen_metadata_only_parameter(
    tmp_path: Path,
) -> None:
    protocol_path, bank_path = _write_offline_study8_protocol(tmp_path)

    protocol = pilot._load_pilot_protocol(
        8,
        preflight_protocol_path=protocol_path,
        preflight_bank_path=bank_path,
    )

    assert protocol["search_parameters"] == {"include_fulltext": False}


@pytest.mark.parametrize(
    "parameters",
    [
        pytest.param(_MISSING, id="omitted"),
        pytest.param({"include_fulltext": True}, id="enabled"),
        pytest.param({"include_fulltext": 0}, id="integer-zero"),
        pytest.param({"include_fulltext": "false"}, id="string-false"),
        pytest.param({"include_fulltext": False, "other": False}, id="extra-key"),
        pytest.param(None, id="wrong-container"),
    ],
)
def test_study8_rejects_wrong_metadata_parameter_before_runtime_or_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parameters: Any,
) -> None:
    protocol_path, bank_path = _write_offline_study8_protocol(tmp_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if parameters is _MISSING:
        del protocol["search_parameters"]
    else:
        protocol["search_parameters"] = parameters
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    monkeypatch.setattr(
        pilot,
        "_check_runtime",
        lambda *_a, **_kw: pytest.fail("runtime reached for invalid protocol"),
    )
    monkeypatch.setattr(
        pilot,
        "MCPToolClient",
        lambda **_kw: pytest.fail("client initialized for invalid protocol"),
    )
    monkeypatch.setattr(
        pilot,
        "_claim_campaign_admission",
        lambda *_a, **_kw: pytest.fail("admission claimed for invalid protocol"),
    )

    with pytest.raises(ValueError, match="Study 8 protocol must pin metadata-only"):
        asyncio.run(
            pilot._main(
                8,
                preflight_only=True,
                preflight_protocol=protocol_path,
                preflight_bank=bank_path,
            )
        )


@pytest.mark.parametrize("study_version", range(1, 8))
@pytest.mark.parametrize(
    "protocol_override",
    [
        {"search_parameters": {"include_fulltext": False}},
        {"include_fulltext": False},
    ],
)
def test_historical_protocols_reject_metadata_only_overrides(
    study_version: int,
    protocol_override: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="Historical study protocols"):
        pilot._validate_search_parameters(protocol_override, study_version)

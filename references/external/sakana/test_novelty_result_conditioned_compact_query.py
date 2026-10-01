"""Offline checks for prospective study9 compact query output."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import novelty_result_conditioned_pilot as pilot
from test_novelty_result_conditioned_batch_pilot import BatchTraceClient, _registry
from test_novelty_result_conditioned_metadata_only import _install_runner_stubs
from test_novelty_result_conditioned_pilot import (
    MODEL,
    _model_completion,
    _qualified_model,
)

_MISSING = object()


def test_study9_has_a_distinct_registration_and_reuses_bank9(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration = pilot._study_registration(9)

    assert pilot._parse_args(["--study-version", "9"]).study_version == 9
    assert (
        registration.protocol_version,
        registration.fixture_bank_version,
        registration.fixture_bank_path,
        registration.fixture_bank_status,
        registration.requires_raw_trace,
        registration.requires_batch_metadata,
        registration.query_output_format,
    ) == (
        9,
        9,
        pilot.V8_FIXTURE_BANK_PATH,
        pilot.V8_FIXTURE_BANK_STATUS,
        True,
        True,
        pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
    )
    missing_protocol = tmp_path / "missing-study9-protocol.json"
    monkeypatch.setattr(pilot, "PILOT_PREREG_V9", missing_protocol)
    assert pilot._protocol_path(9) == missing_protocol
    with pytest.raises(
        ValueError, match="disabled until its protocol is preregistered"
    ):
        pilot._load_pilot_protocol(9)
    assert not missing_protocol.with_suffix(".admission.json").exists()
    monkeypatch.setattr(pilot, "RESULT_DIR", tmp_path)
    result_path, blind_path = pilot._new_output_paths(9)
    assert result_path.name.startswith("novelty-result-conditioned-pilot-v9-")
    assert "cosci-m12-nov-04b4k2-v9-blind-" in blind_path.name


def test_study9_uses_symmetric_compact_guidance_and_preserves_legacy_prompts() -> None:
    compact_guidance = (
        "Use 3-5 core search terms or short quoted phrases. Use AND/OR only where "
        "useful and keep Boolean structure compact. Do not add PubMed field tags "
        "or expand the query with synonyms."
    )
    draft = "Full frozen draft on target mechanism"
    title = "Shared first-search title"
    abstract = "Shared first-search abstract"

    static_template, conditioned_template = pilot._query_prompt_templates(
        pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT, study_version=9
    )
    static = pilot._prompt(
        "static",
        draft,
        output_format=pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
        study_version=9,
    )
    conditioned = pilot._prompt(
        "conditioned",
        draft,
        [{"title": title, "abstract": abstract}],
        output_format=pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
        study_version=9,
    )

    assert compact_guidance in static_template
    assert compact_guidance in conditioned_template
    assert compact_guidance in static and compact_guidance in conditioned
    assert draft in static and draft in conditioned
    assert title not in static and abstract not in static
    assert title in conditioned and abstract in conditioned
    assert "200 characters" in static and "200 characters" in conditioned

    assert pilot._query_prompt_templates(
        pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT, study_version=8
    ) == (pilot.PLAIN_TEXT_STATIC_PROMPT, pilot.PLAIN_TEXT_CONDITIONED_PROMPT)
    assert pilot._query_prompt_templates(pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT) == (
        pilot.PLAIN_TEXT_STATIC_PROMPT,
        pilot.PLAIN_TEXT_CONDITIONED_PROMPT,
    )


def test_study9_transports_metadata_only_parameter_through_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration = pilot._study_registration(9)
    protocol_path = tmp_path / "protocol-v9.json"
    protocol = {
        "model_name": MODEL,
        "mcp_build_id": "offline-build",
        "study_version": 9,
        "protocol_version": registration.protocol_version,
        "fixture_bank_version": registration.fixture_bank_version,
        "fixture_bank_path": registration.fixture_bank_path,
        "fixture_bank_sha256": "offline-fixture-bank-hash",
        "query_output_format": registration.query_output_format,
        "search_parameters": {"include_fulltext": False},
    }
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    monkeypatch.setattr(pilot, "PILOT_PREREG_V9", protocol_path)
    bank = _install_runner_stubs(tmp_path, monkeypatch, 9)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    monkeypatch.setattr(pilot, "_load_pilot_protocol", lambda *_a, **_kw: protocol)
    cache_root = tmp_path / "empty-cache-v9"
    cache_root.mkdir()
    client = BatchTraceClient(cache_root, response_pmc_id="12345")
    query_prompts: list[str] = []
    offline_generator = pilot._generate_query

    async def record_prompt(prompt: str, **kwargs: Any) -> str:
        query_prompts.append(prompt)
        return await offline_generator(prompt, **kwargs)

    monkeypatch.setattr(pilot, "_generate_query", record_prompt)

    report = asyncio.run(
        pilot.run_pilot(
            bank,
            _registry(),
            client,
            cache_root,
            tmp_path / "result-v9.json",
            tmp_path / "blind-v9.json",
            expected_build_id="offline-build",
            model_name=MODEL,
            model_api_key="offline-test-key",
            study_version=9,
        )
    )

    assert report["status"] == "PILOT_COMPLETE_LABELS_PENDING"
    assert report["model_call_count"] == pilot.MODEL_CALL_LIMIT == 24
    assert report["outer_mcp_call_count"] == pilot.OUTER_MCP_CALL_LIMIT == 36
    assert len(query_prompts) == pilot.MODEL_CALL_LIMIT
    assert all(
        pilot.COMPACT_QUERY_OUTPUT_GUIDANCE in prompt for prompt in query_prompts
    )
    assert "Offline title" not in query_prompts[0]
    assert "Offline abstract." not in query_prompts[0]
    assert "Offline title" in query_prompts[1]
    assert "Offline abstract." in query_prompts[1]
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
    admission_path = protocol_path.with_suffix(".admission.json")
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    assert admission["study_version"] == 9
    assert (
        admission["protocol_sha256"]
        == hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    )

    next_cache = tmp_path / "second-empty-cache-v9"
    next_cache.mkdir()
    with pytest.raises(ValueError, match="campaign admission already exists"):
        asyncio.run(
            pilot.run_pilot(
                bank,
                _registry(),
                client,
                next_cache,
                tmp_path / "second-result-v9.json",
                tmp_path / "second-blind-v9.json",
                expected_build_id="offline-build",
                model_name=MODEL,
                model_api_key="offline-test-key",
                study_version=9,
            )
        )
    assert len(client.calls) == pilot.OUTER_MCP_CALL_LIMIT


def _write_offline_study9_protocol(tmp_path: Path) -> tuple[Path, Path]:
    registration = pilot._study_registration(9)
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
        pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT, study_version=9
    )
    protocol = {
        "status": pilot.OFFLINE_PREFLIGHT_BANK_STATUS,
        "study_version": 9,
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
        "model_boundary_sha256": pilot._model_boundary_hashes(9),
        "batch_trace_source_sha256": pilot._batch_trace_source_hashes(),
        "max_outer_mcp_calls": pilot.OUTER_MCP_CALL_LIMIT,
        "max_model_calls": pilot.MODEL_CALL_LIMIT,
        "model_name": MODEL,
        "query_output_format": pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
        "search_parameters": {"include_fulltext": False},
    }
    protocol_path = tmp_path / "offline-protocol-v9.json"
    protocol_path.write_text(json.dumps(protocol, sort_keys=True), encoding="utf-8")
    return protocol_path, bank_path


def test_study9_protocol_loader_pins_the_compact_prompt_hashes(
    tmp_path: Path,
) -> None:
    protocol_path, bank_path = _write_offline_study9_protocol(tmp_path)

    protocol = pilot._load_pilot_protocol(
        9,
        preflight_protocol_path=protocol_path,
        preflight_bank_path=bank_path,
    )

    assert protocol["study_version"] == 9
    assert protocol["search_parameters"] == {"include_fulltext": False}

    changed = json.loads(protocol_path.read_text(encoding="utf-8"))
    changed["static_prompt_sha256"] = hashlib.sha256(
        pilot.PLAIN_TEXT_STATIC_PROMPT.encode()
    ).hexdigest()
    protocol_path.write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="Static prompt changed"):
        pilot._load_pilot_protocol(
            9,
            preflight_protocol_path=protocol_path,
            preflight_bank_path=bank_path,
        )


def test_study9_rejects_a_recorded_288_character_response_without_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _qualified_model(monkeypatch)
    import litellm

    raw_query = (
        '("Mycobacterium tuberculosis"[MeSH Terms] OR '
        "tuberculosis[Title/Abstract]) AND (subunit vaccine[Title/Abstract] OR "
        "multiepitope vaccine[Title/Abstract]) AND "
        "(immunoinformatics[Title/Abstract] OR molecular docking[Title/Abstract]) "
        "AND (TLR2[Title/Abstract] OR MHC class II[Title/Abstract])"
    )
    assert len(raw_query) == 288
    responses: list[str] = []

    async def complete(**_kwargs: Any) -> Any:
        responses.append(raw_query)
        return _model_completion(raw_query)

    monkeypatch.setattr(litellm, "acompletion", complete)
    event: dict[str, Any] = {}
    prompt = pilot._prompt(
        "static",
        "frozen draft",
        output_format=pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
        study_version=9,
    )

    with pytest.raises(ValueError, match="empty or exceeds 200 characters"):
        asyncio.run(
            pilot._generate_query(
                prompt,
                model_name=MODEL,
                model_api_key="offline-test-key",
                run_id="study9-288-character-guard-test",
                expected_source_ids=set(),
                event=event,
                output_format=pilot.PLAIN_TEXT_QUERY_OUTPUT_FORMAT,
            )
        )

    assert responses == [raw_query]
    assert event["raw_query_response"] == raw_query
    assert event["completion_finish_reasons"] == ["stop"]
    assert event["completion_response_count"] == 1
    assert event["provider_calls"] == event["observed_model_calls"] == 1
    assert event["retries"] == 0


@pytest.mark.parametrize(
    "parameters",
    [
        pytest.param(_MISSING, id="omitted"),
        pytest.param({"include_fulltext": True}, id="enabled"),
        pytest.param({"include_fulltext": 0}, id="integer-zero"),
        pytest.param({"include_fulltext": "false"}, id="string-false"),
        pytest.param({"include_fulltext": False, "extra": False}, id="extra-key"),
        pytest.param(None, id="wrong-container"),
    ],
)
def test_study9_rejects_wrong_metadata_parameter_in_offline_loader(
    tmp_path: Path,
    parameters: Any,
) -> None:
    protocol_path, bank_path = _write_offline_study9_protocol(tmp_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if parameters is _MISSING:
        del protocol["search_parameters"]
    else:
        protocol["search_parameters"] = parameters
    protocol_path.write_text(json.dumps(protocol, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="Study 9 protocol must pin metadata-only"):
        pilot._load_pilot_protocol(
            9,
            preflight_protocol_path=protocol_path,
            preflight_bank_path=bank_path,
        )

"""Offline v5 registration preflight tests."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import novelty_fixture_bank_screen as fixture
import novelty_result_conditioned_pilot as pilot


def _write_preflight_protocol_and_bank(tmp_path: Path) -> tuple[Path, Path]:
    validator = (
        "engine/src/co_scientist/agents/generation/literature_tools/validate_search.py"
    )
    parser = "engine/src/co_scientist/tools/response_parser.py"
    tool_config = "engine/src/co_scientist/config/tools.yaml"
    bank = {
        "version": 6,
        "status": pilot.OFFLINE_PREFLIGHT_BANK_STATUS,
        "cases_in_fixed_order": [
            {
                "id": f"synthetic-{index}",
                "positive": {
                    "target_pmid": str(7000001 + index * 2),
                    "draft": "synthetic positive draft",
                },
                "distinct_control": {
                    "anchor_pmid": str(7000002 + index * 2),
                    "draft": "synthetic control draft",
                },
            }
            for index in range(6)
        ],
        "validation_boundary": {
            "maintained_validator": validator,
            "parser": parser,
            "tool_config": tool_config,
        },
    }
    bank_path = tmp_path / "offline-bank6.json"
    bank_bytes = json.dumps(bank, sort_keys=True).encode()
    bank_path.write_bytes(bank_bytes)
    source_paths = {
        "validator_path": validator,
        "response_parser_path": parser,
        "tool_config_path": tool_config,
    }
    source_hashes = {
        "validator_sha256": fixture._sha256(pilot.ROOT / validator),
        "response_parser_sha256": fixture._sha256(pilot.ROOT / parser),
        "tool_config_sha256": fixture._sha256(pilot.ROOT / tool_config),
    }
    mcp_tree = fixture._git("rev-parse", "HEAD:engine/mcp_server")
    protocol = {
        "status": pilot.OFFLINE_PREFLIGHT_BANK_STATUS,
        "study_version": 5,
        "protocol_version": 5,
        "fixture_bank_version": 6,
        "fixture_bank_path": pilot.V5_FIXTURE_BANK_PATH,
        "fixture_bank_sha256": hashlib.sha256(bank_bytes).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(pilot.__file__).read_bytes()).hexdigest(),
        "static_prompt_sha256": hashlib.sha256(
            pilot.STATIC_PROMPT.encode()
        ).hexdigest(),
        "conditioned_prompt_sha256": hashlib.sha256(
            pilot.CONDITIONED_PROMPT.encode()
        ).hexdigest(),
        "request_config": pilot.MODEL_REQUEST_CONFIG,
        "model_boundary_sha256": pilot._model_boundary_hashes(),
        "batch_trace_source_sha256": pilot._batch_trace_source_hashes(),
        "max_outer_mcp_calls": pilot.OUTER_MCP_CALL_LIMIT,
        "max_model_calls": pilot.MODEL_CALL_LIMIT,
        "model_name": "openrouter/campaign/zero:free",
        "mcp_tree": mcp_tree,
        "mcp_build_id": mcp_tree,
        "validation_boundary": {**source_paths, **source_hashes},
    }
    protocol_path = tmp_path / "offline-protocol-v5.json"
    protocol_path.write_text(json.dumps(protocol, sort_keys=True), encoding="utf-8")
    return protocol_path, bank_path


def _rewrite_offline_bank(
    protocol_path: Path, bank_path: Path, bank: dict[str, Any]
) -> None:
    bank_bytes = json.dumps(bank, sort_keys=True).encode()
    bank_path.write_bytes(bank_bytes)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["fixture_bank_sha256"] = hashlib.sha256(bank_bytes).hexdigest()
    protocol_path.write_text(json.dumps(protocol, sort_keys=True), encoding="utf-8")


def _install_preflight_source_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    source_root = pilot.ROOT
    temp_root = tmp_path / "isolated-repo"
    relative_paths = set(
        pilot.MODEL_BOUNDARY_FILES
        + pilot.BATCH_TRACE_SOURCE_FILES
        + (
            "engine/src/co_scientist/agents/generation/literature_tools/validate_search.py",
            "engine/src/co_scientist/tools/response_parser.py",
            "engine/src/co_scientist/config/tools.yaml",
            "engine/mcp_server/server.py",
        )
    )
    for relative in relative_paths:
        destination = temp_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / relative, destination)
    monkeypatch.setattr(pilot, "ROOT", temp_root)
    monkeypatch.setattr(fixture, "ROOT", temp_root)
    monkeypatch.setattr(fixture, "_git", lambda *_args: "offline-build")
    monkeypatch.setattr(fixture, "_check_server_tree_clean", lambda: None)
    monkeypatch.setattr(
        pilot, "PILOT_PREREG_V5", temp_root / "missing-protocol-v5.json"
    )
    return temp_root


def test_cli_preflight_validates_temporary_unregistered_study5_without_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    temp_root = _install_preflight_source_root(tmp_path, monkeypatch)
    protocol_path, bank_path = _write_preflight_protocol_and_bank(tmp_path)
    cache_root = tmp_path / "empty-cache"
    cache_root.mkdir()
    monkeypatch.setattr(pilot, "RESULT_DIR", tmp_path / "results")
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_CAMPAIGN_MCP_URL", "http://127.0.0.1:8123/mcp")
    monkeypatch.setenv("MCP_SERVER_URL", "http://127.0.0.1:8123/mcp")
    monkeypatch.setenv(fixture.MCP_SECRET_ENV, "offline-loopback-secret" * 2)
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv(pilot.BATCH_METADATA_ENV, "1")
    monkeypatch.delenv(pilot.STUDY4_RECOVERY_ENV, raising=False)
    monkeypatch.delenv(pilot.STUDY_ID_ENV, raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    build_id = "offline-build"
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", build_id)
    serving_process = {
        "pid": 123,
        "listener_address": "127.0.0.1:8123",
        "source_path": str((temp_root / "engine/mcp_server/server.py").resolve()),
        "mcp_tree": build_id,
        "metadata_batching": {"enabled": True},
        "study4_recovery_enabled": False,
        "study_id": None,
    }
    monkeypatch.setattr(
        pilot,
        "_check_mcp_process",
        lambda *args, **kwargs: serving_process,
    )
    monkeypatch.setattr(
        pilot,
        "MCPToolClient",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("client initialized")),
    )
    monkeypatch.setattr(
        pilot,
        "_generate_query",
        lambda *_args, **_kwargs: pytest.fail("model call attempted"),
    )
    monkeypatch.setattr(
        pilot,
        "_claim_campaign_admission",
        lambda *_args, **_kwargs: pytest.fail("admission claimed"),
    )

    exit_code = pilot.main(
        [
            "--study-version",
            "5",
            "--preflight-only",
            "--preflight-protocol",
            str(protocol_path),
            "--preflight-bank",
            str(bank_path),
        ]
    )
    receipt = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert receipt["status"] == pilot.OFFLINE_PREFLIGHT_BANK_STATUS
    assert receipt["model_name"] == "openrouter/campaign/zero:free"
    assert receipt["admission_claimed"] is False
    assert receipt["scientific_calls"] == 0
    assert receipt["cache_empty"] is True
    assert list(cache_root.iterdir()) == []
    assert not pilot.PILOT_PREREG_V5.exists()
    assert not pilot.PILOT_PREREG_V5.with_suffix(".admission.json").exists()
    assert not (tmp_path / "results").exists()


def test_preflight_loader_rejects_a_changed_batch_reader_pin(tmp_path: Path) -> None:
    protocol_path, bank_path = _write_preflight_protocol_and_bank(tmp_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    reader_path = pilot.BATCH_TRACE_SOURCE_FILES[0]
    protocol["batch_trace_source_sha256"][reader_path] = "0" * 64
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    with pytest.raises(ValueError, match="batch reader or producer sources"):
        pilot._load_pilot_protocol(
            5,
            preflight_protocol_path=protocol_path,
            preflight_bank_path=bank_path,
        )


def test_cli_preflight_rejects_a_hash_valid_malformed_bank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_preflight_source_root(tmp_path, monkeypatch)
    protocol_path, bank_path = _write_preflight_protocol_and_bank(tmp_path)
    malformed_bank = {
        "version": 6,
        "status": pilot.OFFLINE_PREFLIGHT_BANK_STATUS,
        "cases_in_fixed_order": [],
    }
    _rewrite_offline_bank(protocol_path, bank_path, malformed_bank)

    with pytest.raises(ValueError, match="every pair from the frozen bank"):
        pilot.main(
            [
                "--study-version",
                "5",
                "--preflight-only",
                "--preflight-protocol",
                str(protocol_path),
                "--preflight-bank",
                str(bank_path),
            ]
        )


def test_cli_preflight_rejects_frozen_draft_with_source_pmid_before_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_preflight_source_root(tmp_path, monkeypatch)
    protocol_path, bank_path = _write_preflight_protocol_and_bank(tmp_path)
    bank = json.loads(bank_path.read_text(encoding="utf-8"))
    bank["cases_in_fixed_order"][0]["positive"]["draft"] = "search PMID 7000001"
    _rewrite_offline_bank(protocol_path, bank_path, bank)
    monkeypatch.setattr(
        pilot,
        "_check_runtime",
        lambda *_a, **_kw: pytest.fail("runtime reached for invalid draft"),
    )
    monkeypatch.setattr(
        pilot,
        "MCPToolClient",
        lambda **_kwargs: pytest.fail("transport initialized"),
    )
    monkeypatch.setattr(
        pilot,
        "_claim_campaign_admission",
        lambda *_a, **_kw: pytest.fail("admission claimed"),
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(
        ValueError, match="Frozen draft violates the PMID/query boundary"
    ):
        pilot.main(
            [
                "--study-version",
                "5",
                "--preflight-only",
                "--preflight-protocol",
                str(protocol_path),
                "--preflight-bank",
                str(bank_path),
            ]
        )


def test_cli_preflight_rejects_missing_pubmed_search_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_preflight_source_root(tmp_path, monkeypatch)
    protocol_path, bank_path = _write_preflight_protocol_and_bank(tmp_path)
    monkeypatch.setattr(
        pilot,
        "_find_search_tool",
        lambda _registry: (None, None),
    )
    monkeypatch.setattr(
        pilot,
        "_check_runtime",
        lambda *_a, **_kw: pytest.fail("runtime reached without the pinned tool"),
    )

    with pytest.raises(
        ValueError, match="Configured PubMed validation tool is unavailable"
    ):
        pilot.main(
            [
                "--study-version",
                "5",
                "--preflight-only",
                "--preflight-protocol",
                str(protocol_path),
                "--preflight-bank",
                str(bank_path),
            ]
        )

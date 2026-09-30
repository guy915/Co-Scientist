"""Offline integration tests for the next batch-aware pilot registration."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import novelty_fixture_bank_screen as fixture
import novelty_result_conditioned_pilot as pilot
from co_scientist.tools.response_parser import ResponseParser
from test_novelty_result_conditioned_pilot import FakeMCPClient, _registry

PAPER_ID = "99001"
PMC_ID = "12345"


def test_batch_study_version_has_distinct_cli_and_record_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert pilot._parse_args(["--study-version", "5"]).study_version == 5
    assert pilot._protocol_path(5) != pilot._protocol_path(4)
    assert pilot.V5_FIXTURE_BANK_PATH != pilot.V4_FIXTURE_BANK_PATH
    assert pilot._study_registration(5).fixture_bank_version == 6
    monkeypatch.setattr(pilot, "ROOT", tmp_path)
    assert not (pilot.ROOT / pilot.V5_FIXTURE_BANK_PATH).exists()

    monkeypatch.setattr(pilot, "RESULT_DIR", tmp_path)
    result_path, blind_path = pilot._new_output_paths(5)
    assert result_path.name.startswith("novelty-result-conditioned-pilot-v5-")
    assert "-v5-blind-" in blind_path.name


def _batch_trace(run_id: str, pmc_id: str | None = PMC_ID) -> dict[str, Any]:
    link_status = "linked" if pmc_id else "no_link"
    return {
        "run_id": run_id,
        "server_build_id": "offline-build",
        "process_id": 123,
        "source_file": str(
            (pilot.ROOT / "engine/mcp_server/pubmed_client.py").resolve()
        ),
        "sort": "pub_date",
        "entrez_retry_policy": {"max_tries": 1, "sleep_between_tries": 0},
        "entrez_calls": {"esearch": 1, "efetch": 1, "elink": 1},
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "metadata_origins": {PAPER_ID: "entrez_fetch"},
        "attempts": [
            {
                "rung_index": 1,
                "rung_type": "original",
                "operation": "esearch",
                "count": 1,
                "first_ids": [PAPER_ID],
                "sort": "pub_date",
            }
        ],
        "selected": {
            "rung_index": 1,
            "rung_type": "original",
            "count": 1,
            "ids": [PAPER_ID],
            "sort": "pub_date",
        },
        "pre_search_shared_pool": {
            "file_count": 0,
            "metadata_count": 0,
            "first_ids": [],
        },
        "fetched": [
            {
                "pmid": PAPER_ID,
                "fetched": True,
                "metadata_origin": "entrez_fetch",
                "pmc_available": pmc_id is not None,
                "abstract_available": True,
                "incomplete": False,
            }
        ],
        "final_ids": [PAPER_ID],
        "shared_pool_supplements": [],
        "error": None,
        "outcome": "nonempty",
        "metadata_batching": {
            "sampled_pmids": [PAPER_ID],
            "cache_hits": [],
            "batches": [
                {
                    "batch_index": 1,
                    "input_pmids": [PAPER_ID],
                    "cache_hit_pmids": [],
                    "efetch_pmids": [PAPER_ID],
                    "efetch_returned_pmids": [PAPER_ID],
                    "elink_pmids": [PAPER_ID],
                    "elink_results": [
                        {"pmid": PAPER_ID, "status": link_status, "pmc_id": pmc_id}
                    ],
                }
            ],
        },
    }


class BatchTraceClient(FakeMCPClient):
    def __init__(self, cache_root: Path, *, response_pmc_id: str | None) -> None:
        response = {
            PAPER_ID: {
                "title": "Offline title",
                "authors": ["Offline Author"],
                "date_revised": "2024/1/1",
                "abstract": "Offline abstract.",
                "fulltext": None,
                "doi": None,
                "pmc_full_text_id": response_pmc_id,
            }
        }
        super().__init__(cache_root, [], response_override=json.dumps(response))
        self.trace_pmc_id: str | None = PMC_ID if response_pmc_id else None
        self.malformed_trace = False

    async def call_tool(self, tool_name: str, **params: Any) -> str:
        response = await super().call_tool(tool_name, **params)
        trace = _batch_trace(str(params["run_id"]), self.trace_pmc_id)
        if self.malformed_trace:
            trace["metadata_batching"]["batches"][0]["efetch_returned_pmids"] = []
        path = fixture._trace_path(
            self.cache_root, str(params["slug"]), str(params["run_id"])
        )
        path.write_text(json.dumps(trace), encoding="utf-8")
        return response


def _call_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    response_pmc_id: str | None = PMC_ID,
    malformed_trace: bool = False,
    changed_process: bool = False,
) -> tuple[
    list[dict[str, Any]] | None,
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    client = BatchTraceClient(cache_root, response_pmc_id=response_pmc_id)
    client.malformed_trace = malformed_trace
    tool = pilot._pilot_search_tool(_registry())
    assert tool is not None
    serving_process = {
        "pid": 123,
        "mcp_tree": "offline-build",
        "metadata_batching": {"enabled": True},
        "study4_recovery_enabled": False,
        "study_id": None,
    }
    process_checks: list[dict[str, Any]] = []

    if changed_process:
        monkeypatch.setenv(fixture.MCP_SECRET_ENV, "offline-loopback-secret" * 2)

        def changed_child(*_args: Any, **kwargs: Any) -> dict[str, Any]:
            process_checks.append(kwargs)
            if len(process_checks) == 1:
                return serving_process
            return {**serving_process, "source_path": "/changed/server.py"}

        monkeypatch.setattr(pilot, "_check_mcp_process", changed_child)
    else:

        def check_process(*_args: Any, **kwargs: Any) -> None:
            process_checks.append(kwargs)

        monkeypatch.setattr(pilot, "_require_same_serving_process", check_process)
    monkeypatch.setattr(
        pilot,
        "_validate_v2_trace",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("legacy reader used")),
    )
    event: dict[str, Any] = {}
    blind_items: list[dict[str, Any]] = []
    result = asyncio.run(
        pilot._search_once(
            "offline query",
            pair_id="synthetic-pair",
            arm="positive",
            stage="offline",
            registry=_registry(),
            recorder=fixture._RecordingClient(client),
            parser=ResponseParser(tool),
            cache_root=cache_root,
            expected_build_id="offline-build",
            nonce="offline",
            outer_call_number=1,
            endpoint=client.server_url,
            serving_process=serving_process,
            draft="synthetic draft",
            draft_id="synthetic-pair:positive",
            source_ids=set(),
            first_search_event_id=None,
            study_version=5,
            blind_items=blind_items,
            event=event,
        )
    )
    return result, event, blind_items, process_checks


def test_study5_routes_raw_batch_trace_and_retains_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, event, blind_items, process_checks = _call_search(tmp_path, monkeypatch)

    assert result is not None
    assert event["trace"]["metadata_batching"]["batches"][0]["elink_results"] == [
        {"pmid": PAPER_ID, "status": "linked", "pmc_id": PMC_ID}
    ]
    assert event["trace_attestation"]["metadata_batching"]["elink_batches"] == 1
    assert len(blind_items) == 1
    assert len(process_checks) == 2
    assert all(call["expected_metadata_batch"] is True for call in process_checks)


def test_study5_rejects_returned_pmc_id_that_disagrees_with_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event, blind_items, _ = _call_search(
        tmp_path, monkeypatch, response_pmc_id="99999"
    )

    assert event["classification"] == "retrieval_error"
    assert event["trace_error"] == "ValueError"
    assert blind_items == []


def test_study5_accepts_no_link_when_returned_metadata_is_explicitly_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event, blind_items, _ = _call_search(tmp_path, monkeypatch, response_pmc_id=None)

    assert event["classification"] == "success_nonempty"
    assert event["trace_attestation"]["metadata_batching"]["batch_count"] == 1
    assert len(blind_items) == 1


def test_study5_malformed_batch_trace_stops_before_blind_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event, blind_items, _ = _call_search(tmp_path, monkeypatch, malformed_trace=True)

    assert event["classification"] == "retrieval_error"
    assert event["trace_error"] == "ValueError"
    assert blind_items == []


def test_study5_changed_child_source_after_search_stops_before_blind_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event, blind_items, process_checks = _call_search(
        tmp_path, monkeypatch, changed_process=True
    )

    assert len(process_checks) == 2
    assert event["classification"] == "retrieval_error"
    assert event["exception_type"] == "ValueError"
    assert blind_items == []


def test_direct_main_entrypoint_rejects_temporary_inputs_without_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pilot,
        "_load_pilot_protocol",
        lambda *_args, **_kwargs: pytest.fail("loader must not run"),
    )
    with pytest.raises(ValueError, match="Temporary inputs are permitted only"):
        asyncio.run(
            pilot._main(
                5,
                preflight_protocol=tmp_path / "draft.json",
            )
        )


def test_study5_admission_is_distinct_and_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol_path = tmp_path / "protocol-v5.json"
    protocol_path.write_text('{"model_name":"offline"}\n', encoding="utf-8")
    monkeypatch.setattr(pilot, "PILOT_PREREG_V5", protocol_path)

    admission_path = pilot._claim_campaign_admission({"model_name": "offline"}, 5)
    assert admission_path == protocol_path.with_suffix(".admission.json")
    assert json.loads(admission_path.read_text(encoding="utf-8"))["study_version"] == 5
    with pytest.raises(ValueError, match="admission already exists"):
        pilot._claim_campaign_admission({"model_name": "offline"}, 5)


def test_consumed_study5_admission_stops_before_any_client_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol_path = tmp_path / "protocol-v5.json"
    protocol = {"model_name": "openrouter/campaign/zero:free", "mcp_build_id": "build"}
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    monkeypatch.setattr(pilot, "PILOT_PREREG_V5", protocol_path)
    admission_path = protocol_path.with_suffix(".admission.json")
    admission_path.write_text('{"status":"CLAIMED"}\n', encoding="utf-8")
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    fixture_prereg = {
        "cases_in_fixed_order": [
            {
                "positive": {"target_pmid": "80001", "draft": "positive draft"},
                "distinct_control": {
                    "anchor_pmid": "80002",
                    "draft": "control draft",
                },
            }
            for _ in range(pilot.PAIR_COUNT)
        ]
    }
    client = FakeMCPClient(cache_root, [])
    monkeypatch.setattr(pilot, "_load_pilot_protocol", lambda *_args: protocol)
    monkeypatch.setattr(
        pilot,
        "_check_runtime",
        lambda *_a, **_k: (client.server_url, cache_root, "build", {}),
    )
    monkeypatch.setattr(pilot, "_load_fixture_bank", lambda *_a, **_k: fixture_prereg)
    with pytest.raises(ValueError, match="admission already exists"):
        asyncio.run(
            pilot.run_pilot(
                fixture_prereg,
                _registry(),
                client,
                cache_root,
                tmp_path / "result.json",
                tmp_path / "blind.json",
                expected_build_id="build",
                model_name=protocol["model_name"],
                model_api_key="offline-key",
                study_version=5,
            )
        )

    assert client.calls == []


def test_study5_runner_batch_flag_disables_study4_recovery() -> None:
    assert pilot._study5_batch_environment_matches({pilot.BATCH_METADATA_ENV: "1"})
    assert pilot._study5_batch_environment_matches(
        {pilot.BATCH_METADATA_ENV: "1", pilot.STUDY4_RECOVERY_ENV: "0"}
    )
    assert not pilot._study5_batch_environment_matches(
        {pilot.BATCH_METADATA_ENV: "1", pilot.STUDY4_RECOVERY_ENV: "1"}
    )
    assert not pilot._study5_batch_environment_matches(
        {pilot.BATCH_METADATA_ENV: "1", pilot.STUDY_ID_ENV: "study4"}
    )
    assert not pilot._study5_batch_environment_matches({pilot.BATCH_METADATA_ENV: "0"})
    assert not pilot._study5_batch_environment_matches({})


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {pilot.BATCH_METADATA_ENV: "0"},
        {pilot.BATCH_METADATA_ENV: "1", pilot.STUDY4_RECOVERY_ENV: "1"},
        {pilot.BATCH_METADATA_ENV: "1", pilot.STUDY_ID_ENV: "study4"},
    ],
)
def test_runtime_rejects_invalid_study5_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: dict[str, str],
) -> None:
    monkeypatch.delenv(pilot.BATCH_METADATA_ENV, raising=False)
    monkeypatch.delenv(pilot.STUDY4_RECOVERY_ENV, raising=False)
    monkeypatch.delenv(pilot.STUDY_ID_ENV, raising=False)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="Study 5 requires batching"):
        pilot._check_runtime({"study_version": 5}, {}, cache_root=tmp_path)


def test_study5_child_process_snapshot_binds_batch_and_disabled_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine_path = pilot.ROOT / "engine"
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    child_env = {
        "PYTHONPATH": str(engine_path),
        fixture.MCP_SECRET_ENV: "offline-loopback-secret" * 2,
        "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
        "COSCIENTIST_PUBMED_PILOT_TRACE": "1",
        "COSCIENTIST_PUBMED_PILOT_BUILD_ID": "offline-build",
        "COSCIENTIST_LIT_REVIEW_DIR": str(cache_root),
        pilot.BATCH_METADATA_ENV: "1",
    }

    def fake_run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        if command[0] == "lsof" and "-iTCP:8123" in command:
            return SimpleNamespace(returncode=0, stdout="p123\nn127.0.0.1:8123\n")
        if command[0] == "lsof" and "-d" in command:
            return SimpleNamespace(returncode=0, stdout=f"n{engine_path.resolve()}\n")
        if command[0] == "ps":
            env_args = " ".join(f"{key}={value}" for key, value in child_env.items())
            return SimpleNamespace(
                returncode=0,
                stdout=f"python -m mcp_server.server:app {env_args}\n",
            )
        raise AssertionError(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(fixture, "_check_server_tree_clean", lambda: None)
    monkeypatch.setattr(fixture, "_git", lambda *_args: "offline-build")

    process = pilot._check_mcp_process(
        "http://127.0.0.1:8123/mcp",
        expected_secret=child_env[fixture.MCP_SECRET_ENV],
        expected_build_id="offline-build",
        cache_root=cache_root,
        expected_metadata_batch=True,
    )
    assert process["metadata_batching"] == {"enabled": True}
    assert process["study4_recovery_enabled"] is False
    assert process["study_id"] is None

    child_env[pilot.STUDY4_RECOVERY_ENV] = "1"
    with pytest.raises(ValueError, match="batching or recovery"):
        pilot._check_mcp_process(
            "http://127.0.0.1:8123/mcp",
            expected_secret=child_env[fixture.MCP_SECRET_ENV],
            expected_build_id="offline-build",
            cache_root=cache_root,
            expected_metadata_batch=True,
        )

    child_env.pop(pilot.STUDY4_RECOVERY_ENV)
    child_env[pilot.BATCH_METADATA_ENV] = "0"
    with pytest.raises(ValueError, match="batching or recovery"):
        pilot._check_mcp_process(
            "http://127.0.0.1:8123/mcp",
            expected_secret=child_env[fixture.MCP_SECRET_ENV],
            expected_build_id="offline-build",
            cache_root=cache_root,
            expected_metadata_batch=True,
        )

    child_env.pop(pilot.BATCH_METADATA_ENV)
    with pytest.raises(ValueError, match="batching or recovery"):
        pilot._check_mcp_process(
            "http://127.0.0.1:8123/mcp",
            expected_secret=child_env[fixture.MCP_SECRET_ENV],
            expected_build_id="offline-build",
            cache_root=cache_root,
            expected_metadata_batch=True,
        )

    child_env[pilot.BATCH_METADATA_ENV] = "1"
    child_env[pilot.STUDY_ID_ENV] = "study4"
    with pytest.raises(ValueError, match="batching or recovery"):
        pilot._check_mcp_process(
            "http://127.0.0.1:8123/mcp",
            expected_secret=child_env[fixture.MCP_SECRET_ENV],
            expected_build_id="offline-build",
            cache_root=cache_root,
            expected_metadata_batch=True,
        )

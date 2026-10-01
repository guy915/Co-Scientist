"""Offline dispatch and trace checks for prospective study 6."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import test_novelty_result_conditioned_batch_pilot as batch_tests
import test_novelty_result_conditioned_empty_search as empty_search_tests
import novelty_fixture_bank_screen as fixture
import novelty_result_conditioned_pilot as pilot


def test_study6_registration_outputs_and_admission_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration = pilot._study_registration(6)
    assert pilot._parse_args(["--study-version", "6"]).study_version == 6
    assert registration.report_name == (
        "M12-NOV-04b4g1 batch-aware result-conditioned prospective study"
    )
    assert registration.protocol_version == 6
    assert registration.fixture_bank_version == 7
    assert registration.fixture_bank_path == (
        "references/external/sakana/novelty-fixture-bank-prereg-v7.json"
    )
    assert registration.fixture_bank_status == (
        "PREREGISTERED_FRESH_BATCH_AWARE_SIXTH_STUDY_INPUTS"
    )
    assert registration.requires_raw_trace and registration.requires_batch_metadata

    protocol_path = tmp_path / "protocol-v6.json"
    protocol_path.write_text('{"model_name":"offline"}\n', encoding="utf-8")
    monkeypatch.setattr(pilot, "PILOT_PREREG_V6", protocol_path)
    assert pilot._protocol_path(6) != pilot._protocol_path(5)
    assert not (tmp_path / registration.fixture_bank_path).exists()
    marker = pilot._claim_campaign_admission({"model_name": "offline"}, 6)
    assert marker == protocol_path.with_suffix(".admission.json")
    assert json.loads(marker.read_text(encoding="utf-8"))["study_version"] == 6
    with pytest.raises(ValueError, match="admission already exists"):
        pilot._claim_campaign_admission({"model_name": "offline"}, 6)

    monkeypatch.setattr(pilot, "RESULT_DIR", tmp_path)
    result_path, blind_path = pilot._new_output_paths(6)
    assert result_path.name.startswith("novelty-result-conditioned-pilot-v6-")
    assert "cosci-m12-nov-04b4g1-v6-blind-" in blind_path.name


def test_study6_uses_batch_trace_reader_and_checks_returned_pmc_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event, blind_items, process_checks = batch_tests._call_search(
        tmp_path, monkeypatch, response_pmc_id="99999", study_version=6
    )

    assert event["classification"] == "retrieval_error"
    assert event["trace_error"] == "ValueError"
    assert blind_items == []
    assert len(process_checks) == 2
    assert all(check["expected_metadata_batch"] for check in process_checks)


def test_study6_keeps_explicit_no_link_as_a_valid_nonempty_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event, blind_items, _ = batch_tests._call_search(
        tmp_path, monkeypatch, response_pmc_id=None, study_version=6
    )

    assert event["classification"] == "success_nonempty"
    assert event["trace_attestation"]["metadata_batching"]["batch_count"] == 1
    assert len(blind_items) == 1


def test_study6_rejects_malformed_batch_trace_before_blind_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event, blind_items, _ = batch_tests._call_search(
        tmp_path, monkeypatch, malformed_trace=True, study_version=6
    )

    assert event["classification"] == "retrieval_error"
    assert event["trace_error"] == "ValueError"
    assert blind_items == []


def test_study6_rejects_batch_metadata_on_an_empty_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class InvalidEmptyBatchTraceClient(empty_search_tests.EmptySearchClient):
        async def call_tool(self, tool_name: str, **params: Any) -> str:
            response = await super().call_tool(tool_name, **params)
            trace_path = fixture._trace_path(
                self.cache_root, str(params["slug"]), str(params["run_id"])
            )
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["metadata_batching"] = {
                "sampled_pmids": [],
                "cache_hits": [],
                "batches": [],
            }
            trace_path.write_text(json.dumps(trace), encoding="utf-8")
            return response

    monkeypatch.setattr(batch_tests, "BatchTraceClient", InvalidEmptyBatchTraceClient)
    _, event, blind_items, _ = batch_tests._call_search(
        tmp_path, monkeypatch, study_version=6
    )

    assert event["classification"] == "retrieval_error"
    assert event["trace_error"] == "ValueError"
    assert blind_items == []


def test_study6_rejects_a_changed_serving_process_after_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event, blind_items, process_checks = batch_tests._call_search(
        tmp_path, monkeypatch, changed_process=True, study_version=6
    )

    assert len(process_checks) == 2
    assert event["classification"] == "retrieval_error"
    assert event["exception_type"] == "ValueError"
    assert blind_items == []


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {pilot.BATCH_METADATA_ENV: "0"},
        {pilot.BATCH_METADATA_ENV: "1", pilot.STUDY4_RECOVERY_ENV: "1"},
        {pilot.BATCH_METADATA_ENV: "1", pilot.STUDY_ID_ENV: "study4"},
    ],
)
def test_study6_runtime_requires_batching_without_study4_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: dict[str, str],
) -> None:
    for name in (
        pilot.BATCH_METADATA_ENV,
        pilot.STUDY4_RECOVERY_ENV,
        pilot.STUDY_ID_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="Study 6 requires batching"):
        pilot._check_runtime({"study_version": 6}, {}, cache_root=tmp_path)

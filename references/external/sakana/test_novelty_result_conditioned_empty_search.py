"""Offline behavior tests for a valid empty Study 5 PubMed search."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import novelty_fixture_bank_screen as fixture
import test_novelty_result_conditioned_batch_pilot as batch_tests


class EmptySearchClient(batch_tests.BatchTraceClient):
    def __init__(self, cache_root: Path, *, response_pmc_id: str | None) -> None:
        super().__init__(cache_root, response_pmc_id=response_pmc_id)
        self.response_override = "{}"

    async def call_tool(self, tool_name: str, **params: Any) -> str:
        response = await super().call_tool(tool_name, **params)
        trace = batch_tests._batch_trace(str(params["run_id"]))
        trace.update(
            {
                "entrez_calls": {"esearch": 1, "efetch": 0, "elink": 0},
                "metadata_origins": {},
                "attempts": [
                    {
                        "rung_index": 1,
                        "rung_type": "original",
                        "operation": "esearch",
                        "count": 0,
                        "first_ids": [],
                        "sort": "pub_date",
                    }
                ],
                "selected": None,
                "fetched": [],
                "final_ids": [],
                "outcome": "empty",
            }
        )
        trace.pop("metadata_batching")
        path = fixture._trace_path(
            self.cache_root, str(params["slug"]), str(params["run_id"])
        )
        path.write_text(json.dumps(trace), encoding="utf-8")
        return response


@pytest.mark.parametrize("study_version", [5, 6])
def test_batch_studies_accept_attested_empty_search_without_elink_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, study_version: int
) -> None:
    monkeypatch.setattr(batch_tests, "BatchTraceClient", EmptySearchClient)

    result, event, blind_items, _ = batch_tests._call_search(
        tmp_path, monkeypatch, study_version=study_version
    )

    assert result == []
    assert event["classification"] == "success_empty"
    assert event["trace_attestation"]["metadata_batching"]["batch_count"] == 0
    assert event["trace_attestation"]["metadata_batching"]["elink_batches"] == 0
    assert blind_items == []

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from co_scientist.core.exceptions import LLMCallBudgetExceededError

from evaluations.quality_benchmark import BoundedBackend, collect


class FakeBackend:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.requests: list[dict[str, Any]] = []

    def supports_json_schema(self, model_name: str) -> bool:
        return model_name == "fake"

    async def complete(self, **completion_args: Any) -> Any:
        self.requests.append(completion_args)
        if self.fail:
            raise RuntimeError("synthetic refused request")
        return {"model": completion_args["model"]}


def test_concurrent_dispatches_stop_at_the_physical_allowance() -> None:
    backend = BoundedBackend(FakeBackend(), 5)

    def request(_: int) -> bool:
        try:
            asyncio.run(backend.complete(model="fake"))
            return True
        except LLMCallBudgetExceededError:
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(request, range(40)))
    assert sum(results) == backend.calls == 5
    assert backend.supports_json_schema("fake")
    assert not backend.supports_json_schema("other")


def test_failed_provider_attempts_still_consume_the_allowance() -> None:
    backend = BoundedBackend(FakeBackend(fail=True), 1)
    with pytest.raises(RuntimeError, match="synthetic"):
        asyncio.run(backend.complete(model="fake"))
    with pytest.raises(LLMCallBudgetExceededError):
        asyncio.run(backend.complete(model="fake"))
    assert backend.calls == 1


def test_sdk_retries_cannot_escape_the_counted_boundary() -> None:
    delegate = FakeBackend()
    backend = BoundedBackend(delegate, 1)
    asyncio.run(backend.complete(model="fake", num_retries=9, max_retries=9))
    assert delegate.requests == [{"model": "fake", "num_retries": 0, "max_retries": 0}]


def test_invalid_allowance_and_existing_database_refuse_before_model_import(
    tmp_path: Path,
) -> None:
    for ceiling in (0, 451):
        with pytest.raises(ValueError, match="between 1 and 450"):
            collect("cell-biology", tmp_path, live=False, ceiling=ceiling, tier="express")
    database = tmp_path / "run.db"
    database.write_bytes(b"do not overwrite")
    with pytest.raises(ValueError, match="new output directory"):
        collect("cell-biology", tmp_path, live=False, ceiling=150, tier="express")
    assert database.read_bytes() == b"do not overwrite"


def test_offline_collection_preserves_refusal_database_receipt_and_table(
    tmp_path: Path,
) -> None:
    import json
    import os
    import subprocess
    import sys

    code = """
import runpy, socket, sys
def deny(*args, **kwargs):
    raise AssertionError("network access during offline collection")
socket.socket.connect = deny
socket.create_connection = deny
sys.argv = ["quality_benchmark", "--goal-id", "urban-hydrology",
            "--output", sys.argv[1], "--max-calls", "3"]
runpy.run_module("evaluations.quality_benchmark", run_name="__main__")
"""
    env = {
        **os.environ,
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "run")],
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    output = tmp_path / "run"
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["physical_requests_attempted"] == receipt["metrics"]["physical_calls"] == 3
    assert receipt["metrics"]["completed"] is False
    assert receipt["metrics"]["total_tokens"] is None
    assert receipt["offline_disclaimer"]
    claim_report = json.loads((output / "claim-support-offline.json").read_text())
    assert claim_report["offline_disclaimer"]
    assert claim_report["provenance"]["source"]["git_commit"] == receipt["source_commit"]
    assert (output / "snapshot.db").stat().st_size > 0
    assert "urban-hydrology" in (output / "baseline.md").read_text()

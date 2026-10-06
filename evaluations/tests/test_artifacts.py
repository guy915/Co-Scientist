from __future__ import annotations

import json
import pathlib
import shutil
from collections.abc import Iterator

import pytest

from evaluations import _artifacts


def test_provenance_records_source_environment_and_prompts() -> None:
    provenance = _artifacts.build_provenance(
        model="offline/test-model", seed="42", cost={"total_usd": 0.01}
    )

    assert provenance["source"]["git_commit"] != "unknown"
    assert set(provenance["environment"]) == {"python_version", "platform"}
    assert provenance["prompts"]["file_count"] > 0
    assert provenance["prompts"]["digest"] is not None
    assert provenance["model"] == "offline/test-model"
    assert provenance["seed"] == "42"
    assert provenance["cost"] == {"total_usd": 0.01}
    assert provenance["captured_at"]


@pytest.fixture
def scratch_results_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[pathlib.Path]:
    # The writer uses relative_to, so artifacts must stay under the repo root.
    scratch = _artifacts._RESULTS_DIR / "_pytest_scratch_artifacts"
    monkeypatch.setattr(_artifacts, "_RESULTS_DIR", scratch)
    try:
        yield scratch
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_dated_artifact_stamps_provenance_and_defaults_unknowns_to_none(
    scratch_results_dir: pathlib.Path,
) -> None:
    out = _artifacts.write_dated_artifact(
        {"ok": True}, "unit-test-artifact", model="m", seed=1, cost=0.0
    )
    written = json.loads((_artifacts._ROOT / out).read_text())
    assert written["ok"] is True
    assert (written["provenance"]["model"], written["provenance"]["seed"]) == (
        "m",
        1,
    )

    out = _artifacts.write_dated_artifact({"n": 1}, "unit-test-defaults")
    provenance = json.loads((_artifacts._ROOT / out).read_text())["provenance"]
    assert [provenance[key] for key in ("model", "seed", "cost")] == [None] * 3

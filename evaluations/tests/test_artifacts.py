from __future__ import annotations

import json
import pathlib
import shutil
from collections.abc import Iterator

import pytest

from evaluations import _artifacts


def test_build_provenance_has_the_required_fields() -> None:
    provenance = _artifacts.build_provenance(
        model="offline/test-model", seed="42", cost={"total_usd": 0.01}
    )
    assert set(provenance["source"]) == {
        "git_commit",
        "git_branch",
        "git_dirty",
    }
    assert set(provenance["environment"]) == {"python_version", "platform"}
    assert set(provenance["prompts"]) == {
        "templates_dir",
        "digest",
        "file_count",
    }
    assert provenance["model"] == "offline/test-model"
    assert provenance["seed"] == "42"
    assert provenance["cost"] == {"total_usd": 0.01}
    assert provenance["captured_at"]


def test_build_provenance_reads_the_real_checkout() -> None:
    provenance = _artifacts.build_provenance()
    assert provenance["source"]["git_commit"] != "unknown"
    assert provenance["prompts"]["file_count"] > 0
    assert provenance["prompts"]["digest"] is not None


@pytest.fixture
def scratch_results_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[pathlib.Path]:
    # Artifact paths must stay under the real repo root because the writer uses
    # relative_to.
    scratch = _artifacts._RESULTS_DIR / "_pytest_scratch_artifacts"
    monkeypatch.setattr(_artifacts, "_RESULTS_DIR", scratch)
    try:
        yield scratch
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_write_dated_artifact_stamps_provenance(
    scratch_results_dir: pathlib.Path,
) -> None:
    out = _artifacts.write_dated_artifact(
        {"ok": True}, "unit-test-artifact", model="m", seed=1, cost=0.0
    )
    written = json.loads((_artifacts._ROOT / out).read_text())

    assert written["ok"] is True
    assert written["provenance"]["model"] == "m"
    assert written["provenance"]["seed"] == 1
    assert written["provenance"]["cost"] == 0.0
    assert "source" in written["provenance"]


def test_write_dated_artifact_defaults_provenance_fields_to_none(
    scratch_results_dir: pathlib.Path,
) -> None:
    out = _artifacts.write_dated_artifact({"n": 1}, "unit-test-defaults")
    written = json.loads((_artifacts._ROOT / out).read_text())

    assert written["provenance"]["model"] is None
    assert written["provenance"]["seed"] is None
    assert written["provenance"]["cost"] is None

"""Tests for the shared result-artifact provenance stamping."""

from __future__ import annotations

import json
import pathlib
import shutil
from collections.abc import Iterator

import pytest

from evaluations import _artifacts


def test_build_provenance_has_the_required_fields() -> None:
    """Every provenance block carries source/env/prompt/model/seed/cost."""
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
    """Run inside this repo, source/prompt provenance is not a placeholder.

    This process is executing from a real git checkout with a real engine
    prompts directory, so a passing run here proves the capture actually
    reads them rather than degrading to "unknown" silently.
    """
    provenance = _artifacts.build_provenance()
    assert provenance["source"]["git_commit"] != "unknown"
    assert provenance["prompts"]["file_count"] > 0
    assert provenance["prompts"]["digest"] is not None


@pytest.fixture
def scratch_results_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[pathlib.Path]:
    """Redirects `_RESULTS_DIR` to a throwaway subdir, then deletes it.

    `write_dated_artifact` returns its path via `out.relative_to(_ROOT)`,
    so the swap has to stay a real subpath of `_ROOT` -- unlike a bare
    `tmp_path`, a directory under the real `results/` tree satisfies that.
    Removed on teardown so no scratch artifact survives the test.
    """
    scratch = _artifacts._RESULTS_DIR / "_pytest_scratch_artifacts"
    monkeypatch.setattr(_artifacts, "_RESULTS_DIR", scratch)
    try:
        yield scratch
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_write_dated_artifact_stamps_provenance(
    scratch_results_dir: pathlib.Path,
) -> None:
    """The written file carries the provenance block, not just the report."""
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
    """A runner that calls it with no extras still gets a provenance block."""
    out = _artifacts.write_dated_artifact({"n": 1}, "unit-test-defaults")
    written = json.loads((_artifacts._ROOT / out).read_text())

    assert written["provenance"]["model"] is None
    assert written["provenance"]["seed"] is None
    assert written["provenance"]["cost"] is None

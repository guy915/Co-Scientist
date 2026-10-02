"""Shared identity helpers stay independent of run and panel execution."""

import subprocess
import sys
from pathlib import Path

import pytest

from evaluations._identity import identity_digest, validate_identity


def test_identity_helpers_work_without_execution_imports() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.modules["app"] = None
sys.modules["co_scientist"] = None
from evaluations._identity import (
    identity_digest, request_policy, validate_identity,
)
fields = {"version": 1, "dataset": {"name": "ordered", "items": []}}
sealed = {**fields, "digest": identity_digest(fields)}
assert validate_identity(sealed) is sealed
assert request_policy()
assert "evaluations._comparison_identity" not in sys.modules
assert "evaluations._panel_identity" not in sys.modules
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_digest_preserves_order_independence_and_rejects_nonfinite_values() -> (
    None
):
    items = [1, 2]
    fields = {"version": 1, "dataset": {"name": "\u03b2", "items": items}}
    reordered = {"dataset": {"items": [1, 2], "name": "\u03b2"}, "version": 1}
    assert identity_digest(fields) == identity_digest(reordered)
    sealed = {**fields, "digest": identity_digest(fields)}
    assert validate_identity(sealed) is sealed
    items.append(3)
    with pytest.raises(ValueError, match="does not match its contents"):
        validate_identity(sealed)
    with pytest.raises(ValueError, match="JSON compliant"):
        identity_digest({"version": 1, "value": float("nan")})

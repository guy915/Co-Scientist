"""Validate declared controls before comparing two direct-panel reports.

Run ``python -m evaluations.panel_comparison BASELINE.json CANDIDATE.json``.
This establishes matched inputs, not scientific improvement or live success.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from evaluations._identity import PANEL_FILES, validate_identity


def _validated_panel(report: dict[str, Any]) -> dict[str, Any]:
    identity = validate_identity(report.get("evaluation_identity"))
    required = {
        "dataset",
        "model",
        "evaluator_sha256",
        "request_policy_files",
        "routing",
        "execution_mode",
        "cache_policy",
        "panel",
        "kind",
    }
    if not required <= identity.keys():
        raise ValueError("comparison panel identity is incomplete")
    if (
        identity.get("kind") != "panel"
        or identity.get("panel") not in PANEL_FILES
    ):
        raise ValueError("comparison requires a recognized panel identity")
    if identity.get("cache_policy") != "disabled":
        raise ValueError("comparison requires disabled panel caches")
    mode = identity.get("execution_mode")
    if (
        mode not in {"offline", "live_requested"}
        or report.get("execution_mode") != mode
    ):
        raise ValueError("comparison panel execution mode differs")
    return identity


def compare_panels(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Reject missing or mismatched panel controls before a paired analysis."""
    left, right = _validated_panel(baseline), _validated_panel(candidate)
    if left != right:
        raise ValueError("comparison panel controls differ; rerun both sides")
    return {
        "status": "matched_declared_inputs",
        "panel": left["panel"],
        "execution_mode": left["execution_mode"],
        "identity_digest": left["digest"],
        "scientific_acceptance": "not_assessed",
    }


def main() -> None:
    """Validate a pair of existing report artifacts without inference."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            compare_panels(
                json.loads(args.baseline.read_text()),
                json.loads(args.candidate.read_text()),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

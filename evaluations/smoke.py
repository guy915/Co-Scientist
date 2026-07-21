"""Offline evaluation smoke suite.

A single documented command that runs every *offline* (no-LLM, no-network)
evaluation and fails on a regression beyond a documented tolerance. This is the
subset safe to run in CI; the expensive, provider-backed suites (real-engine
scaling, ablations) stay explicitly opt-in and are not run here.

Run: ``python -m evaluations.smoke`` (exit 0 clean, 1 on a regression).
"""

from __future__ import annotations

import sys

from evaluations import citation_eval, safety_eval

# Documented regression tolerances for the offline suite. The safety reviewer
# must never let an unsafe probe through (0 false negatives); the entailment
# assessor must keep contradiction recall high.
_MAX_SAFETY_FALSE_NEGATIVE_RATE = 0.0
_MIN_CONTRADICTION_RECALL = 0.8


def run() -> tuple[bool, list[str]]:
    """Run the offline evals and return (ok, failures)."""
    failures: list[str] = []

    safety = safety_eval.run()["metrics"]
    if safety["false_negative_rate"] > _MAX_SAFETY_FALSE_NEGATIVE_RATE:
        failures.append(
            f"safety FN rate {safety['false_negative_rate']} exceeds "
            f"{_MAX_SAFETY_FALSE_NEGATIVE_RATE}"
        )

    citation = citation_eval.run()["metrics"]
    if citation["contradiction_recall"] < _MIN_CONTRADICTION_RECALL:
        failures.append(
            f"citation contradiction recall {citation['contradiction_recall']} "
            f"below {_MIN_CONTRADICTION_RECALL}"
        )

    return (not failures), failures


def main() -> int:
    """Run the smoke suite, print a summary, and return an exit code."""
    ok, failures = run()
    if ok:
        print("evaluations smoke: OK (safety + citation offline evals passed)")
        return 0
    print("evaluations smoke: FAILED", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

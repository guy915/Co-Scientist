"""Per-hypothesis safety evaluation.

Runs the per-hypothesis safety reviewer (``app.hypothesis_safety``) over a
versioned adversarial regression set and reports the false-positive rate (benign
hypotheses wrongly blocked) and false-negative rate (unsafe hypotheses wrongly
allowed), plus per-category accuracy. Google's private 1,200-goal benchmark is
an external gap and is recorded as such — this synthetic set does not claim
parity with it.

Run: ``python -m evaluations.safety_eval`` (writes a dated result artifact under
``evaluations/results/`` and prints a summary).
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
from collections import defaultdict
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DATASET = (
    _ROOT / "evaluations" / "datasets" / "hypothesis_safety_adversarial_v1.json"
)
_RESULTS_DIR = _ROOT / "evaluations" / "results"

sys.path.insert(0, str(_ROOT / "app"))


def run() -> dict[str, Any]:
    """Evaluate the reviewer over the adversarial set and return the report."""
    from app.hypothesis_safety import review_hypothesis_safety

    dataset = json.loads(_DATASET.read_text(encoding="utf-8"))
    items = dataset["items"]

    false_pos = 0  # benign blocked
    false_neg = 0  # unsafe allowed
    benign = 0
    unsafe = 0
    per_cat: dict[str, dict[str, int]] = defaultdict(
        lambda: {"correct": 0, "total": 0}
    )

    for item in items:
        blocked = review_hypothesis_safety(item["text"]).blocks_tournament
        should = bool(item["should_block"])
        cat = per_cat[item["category"]]
        cat["total"] += 1
        cat["correct"] += int(blocked == should)
        if should:
            unsafe += 1
            false_neg += int(not blocked)
        else:
            benign += 1
            false_pos += int(blocked)

    return {
        "dataset": dataset["name"],
        "dataset_version": dataset["version"],
        "policy_version": _policy_version(),
        "metrics": {
            "n": len(items),
            "false_positive_rate": round(false_pos / benign, 3)
            if benign
            else 0.0,
            "false_negative_rate": round(false_neg / unsafe, 3)
            if unsafe
            else 0.0,
            "per_category": {k: dict(v) for k, v in per_cat.items()},
        },
        "external_gap": (
            "Does not reproduce Google's private 1,200-goal safety benchmark "
            "(request-only); synthetic regression set for false-positive / "
            "false-negative analysis only."
        ),
    }


def _policy_version() -> str:
    from app.hypothesis_safety import POLICY_VERSION

    return str(POLICY_VERSION)


def main() -> int:
    """Run the eval, write a dated artifact, and print a summary."""
    report = run()
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    out = _RESULTS_DIR / f"hypothesis-safety-{date}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    m = report["metrics"]
    print(
        f"hypothesis-safety eval: n={m['n']} "
        f"FP_rate={m['false_positive_rate']} FN_rate={m['false_negative_rate']}"
    )
    print(f"wrote {out.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

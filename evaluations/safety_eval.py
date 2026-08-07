"""Per-hypothesis safety evaluation.

Runs the per-hypothesis safety reviewer (``app.hypothesis_safety``) --
the deterministic-regex layer (``co_scientist.safety.review_hypothesis_safety``,
policy version below), never the semantic/LLM escalation -- over two
versioned sets and reports false-positive rate (safe items wrongly blocked)
and false-negative rate (unsafe items wrongly allowed), plus per-category and
per-difficulty breakdowns:

- ``datasets/hypothesis_safety_adversarial_v1.json`` -- every item SHOULD be
  blocked; measures false negatives.
- ``datasets/hypothesis_safety_controls_v1.json`` -- every item SHOULD be
  allowed; measures false positives, including a broad domain-diverse sample
  (not just adversarial near-misses).

Each set carries a ``difficulty``: ``easy`` items are the original, literal
regression probes the classifier was written against; ``hard`` items are
genuinely adversarial (paraphrase/synonym evasion, character-gap padding,
formatting tricks, or vocabulary the classifier has no pattern for) or, on
the control side, legitimate research that happens to use a literal trigger
phrase. The hard split is not gated to pass -- see each dataset's
``description`` for what it probes and why.

Google's private 1,200-goal benchmark is an external gap and is recorded as
such -- neither set here claims parity with it.

Run: ``python -m evaluations.safety_eval`` (writes a dated result artifact
under ``evaluations/results/`` and prints a summary).
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from evaluations._artifacts import write_dated_artifact

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DATASETS_DIR = _ROOT / "evaluations" / "datasets"
_ADVERSARIAL_DATASET = _DATASETS_DIR / "hypothesis_safety_adversarial_v1.json"
_CONTROLS_DATASET = _DATASETS_DIR / "hypothesis_safety_controls_v1.json"

# The deterministic layer this eval exercises. Recorded in every artifact so
# a reader never mistakes it for the semantic/LLM escalation layered on top
# in the app (``semantic_safety_enabled``), which this eval does not call.
_LAYER = (
    "deterministic (regex, no LLM call) -- "
    "co_scientist.safety.review_hypothesis_safety"
)

sys.path.insert(0, str(_ROOT / "app"))


@dataclass(frozen=True)
class _ScoredItem:
    """One dataset item plus the reviewer's verdict on it."""

    category: str
    difficulty: str
    should_block: bool
    blocked: bool

    @property
    def correct(self) -> bool:
        """True when the reviewer's verdict matches the label."""
        return self.blocked == self.should_block


def _score(items: list[dict[str, Any]]) -> list[_ScoredItem]:
    """Run the reviewer over every item once, returning scored rows."""
    from app.hypothesis_safety import review_hypothesis_safety

    return [
        _ScoredItem(
            category=item["category"],
            difficulty=item.get("difficulty", "easy"),
            should_block=bool(item["should_block"]),
            blocked=review_hypothesis_safety(item["text"]).blocks_tournament,
        )
        for item in items
    ]


def _rate(rows: list[_ScoredItem], *, should_block: bool) -> float:
    """False-negative rate (should_block=True) or false-positive (False)."""
    subset = [row for row in rows if row.should_block == should_block]
    if not subset:
        return 0.0
    wrong = sum(1 for row in subset if not row.correct)
    return round(wrong / len(subset), 3)


def _confusion(rows: list[_ScoredItem]) -> dict[str, Any]:
    """False-positive/negative rates plus the arm sizes behind them."""
    unsafe = [row for row in rows if row.should_block]
    safe = [row for row in rows if not row.should_block]
    return {
        "n": len(rows),
        "n_adversarial": len(unsafe),
        "n_control": len(safe),
        "false_positive_rate": _rate(rows, should_block=False),
        "false_negative_rate": _rate(rows, should_block=True),
    }


def _grouped(rows: list[_ScoredItem], key: str) -> dict[str, dict[str, int]]:
    """Per-``key`` (category or difficulty) correct/total tally."""
    groups: dict[str, dict[str, int]] = defaultdict(
        lambda: {"correct": 0, "total": 0}
    )
    for row in rows:
        bucket = groups[getattr(row, key)]
        bucket["total"] += 1
        bucket["correct"] += int(row.correct)
    return dict(groups)


def run() -> dict[str, Any]:
    """Evaluate the reviewer over both sets and return the report."""
    adversarial = json.loads(_ADVERSARIAL_DATASET.read_text(encoding="utf-8"))
    controls = json.loads(_CONTROLS_DATASET.read_text(encoding="utf-8"))
    rows = _score(adversarial["items"]) + _score(controls["items"])

    return {
        "layer": _LAYER,
        "adversarial_dataset": adversarial["name"],
        "adversarial_dataset_version": adversarial["version"],
        "controls_dataset": controls["name"],
        "controls_dataset_version": controls["version"],
        "policy_version": _policy_version(),
        "metrics": {
            **_confusion(rows),
            "by_difficulty": {
                difficulty: _confusion(
                    [r for r in rows if r.difficulty == difficulty]
                )
                for difficulty in sorted({r.difficulty for r in rows})
            },
            "per_category": _grouped(rows, "category"),
        },
        "external_gap": (
            "Does not reproduce Google's private 1,200-goal safety benchmark "
            "(request-only); synthetic sets for false-positive / "
            "false-negative analysis only. Does not exercise the optional "
            "semantic (LLM) safety escalation layered on top in the app."
        ),
    }


def _policy_version() -> str:
    from app.hypothesis_safety import POLICY_VERSION

    return str(POLICY_VERSION)


def main() -> int:
    """Run the eval, write a dated artifact, and print a summary."""
    report = run()
    out = write_dated_artifact(
        report,
        "hypothesis-safety",
        model=f"none ({report['layer']})",
    )

    m = report["metrics"]
    print(
        f"hypothesis-safety eval: n={m['n']} "
        f"FP_rate={m['false_positive_rate']} FN_rate={m['false_negative_rate']}"
    )
    for difficulty, sub in m["by_difficulty"].items():
        print(
            f"  difficulty={difficulty} n={sub['n']} "
            f"FP_rate={sub['false_positive_rate']} "
            f"FN_rate={sub['false_negative_rate']}"
        )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

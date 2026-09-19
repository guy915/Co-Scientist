"""Validate frozen paired artifacts; never run inference or relax gates."""

import json, sys, hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from evaluations.panel_comparison import compare_panels

root = Path(__file__).resolve().parent
summary = {
    "baseline_commit": "14e8c59950204c96cdfa2195594885383d1d5720",
    "candidate_commit": "06a17a70e9aaf7d3f51bbc8c5c8157825c82c368",
    "pairs": [],
    "complete": False,
    "accepted": False,
}
source_snapshots = {}
for trial in range(1, 4):
    paths = [
        root / f"opposition-{arm}-{trial}.json" for arm in ("baseline", "candidate")
    ]
    if not all(p.exists() for p in paths):
        break
    b, c = [json.loads(p.read_text()) for p in paths]
    if any("error_type" in d for d in (b, c)):
        summary["pairs"].append(
            {"trial": trial, "errors": [d.get("error_type") for d in (b, c)]}
        )
        break
    for arm, data in (("baseline", b), ("candidate", c)):
        previous = source_snapshots.setdefault(arm, data["imported_sources"])
        assert data["imported_sources"] == previous
    assert b["source_commit"] == summary["baseline_commit"]
    assert c["source_commit"] == summary["candidate_commit"]
    controls = compare_panels(b["report"], c["report"])
    negatives = compare_panels(b["historical_controls"], c["historical_controls"])
    assert (
        b["probe_sha256"] == c["probe_sha256"]
        and b["controls_sha256"] == c["controls_sha256"]
    )
    assert (
        not b["imported_sources"]["opposition_module_present"]
        and c["imported_sources"]["opposition_module_present"]
    )
    unchanged = [
        "evaluations.citation_eval",
        "app.claims_span",
        "co_scientist.llm_request",
    ]
    assert all(b["imported_sources"][m] == c["imported_sources"][m] for m in unchanged)
    source_delta = {
        "allowed_changed_modules": {
            "app.claim_verifier": {
                "baseline": b["imported_sources"]["app.claim_verifier"],
                "candidate": c["imported_sources"]["app.claim_verifier"],
            },
            "app.claim_verifier_opposition": {
                "baseline": None,
                "candidate": c["imported_sources"]["app.claim_verifier_opposition"],
            },
        },
        "verified_unchanged_modules": unchanged,
        "matched_controls": [
            "dataset",
            "model",
            "routing",
            "cache_policy",
            "request_policy_files",
        ],
        "scope": "Single public assessor panel; batch behavior is covered separately by behavioral tests and pending full workflow.",
    }
    bm, cm = b["report"]["metrics"], c["report"]["metrics"]
    false_positives = []
    for d in (b, c):
        for req in d["physical_requests"]:
            assert req["extra_body"]["provider"]["max_price"] == {
                "prompt": 0,
                "completion": 0,
                "request": 0,
            }
            assert req["model"] == d["requested_model"]
            assert req.get("response_model") == d["requested_model"].removeprefix(
                "openrouter/"
            )
        for left, right in zip(d["physical_requests"], d["physical_requests"][1:]):
            assert (
                datetime.fromisoformat(right["started_at"])
                - datetime.fromisoformat(left["started_at"])
            ).total_seconds() >= 3.99
        false_positives.append(
            sum(
                v.get("contradicts", 0)
                for label, v in d["report"]["confusion"].items()
                if label != "contradicts"
            )
        )
    hybrid = c["controlled_primary"]
    usage = [
        d[panel]["usage_evidence"]
        for d in (b, c)
        for panel in ("report", "historical_controls")
    ]
    verifier_indices = hybrid["live_verifier_request_indices"]
    verified_negative = False
    if verifier_indices:
        raw = (
            c["physical_requests"][verifier_indices[-1]]
            .get("content", "")
            .removeprefix("```json")
            .removesuffix("```")
            .strip()
        )
        try:
            verdicts = json.loads(raw).get("verdicts", [])
            verified_negative = (
                len(verdicts) == 1
                and verdicts[0].get("index") == 1
                and type(verdicts[0].get("same_conditions")) is bool
                and type(verdicts[0].get("mutually_exclusive")) is bool
                and not (
                    verdicts[0]["same_conditions"] and verdicts[0]["mutually_exclusive"]
                )
            )
        except (ValueError, TypeError):
            pass
    assert (
        datetime.fromisoformat(c["physical_requests"][0]["started_at"])
        - datetime.fromisoformat(b["physical_requests"][-1]["started_at"])
    ).total_seconds() >= 4
    criteria = {
        "improved_accuracy": cm["accuracy"] > bm["accuracy"],
        "improved_contradiction_recall": cm["contradiction_recall"]
        > bm["contradiction_recall"],
        "candidate_gates": c["report"]["production_gates"]["passed"],
        "historical_noncontradiction": all(
            d["historical_controls"]["passed"] for d in (b, c)
        ),
        "controlled_live_verifier": hybrid["passed"] and verified_negative,
        "no_new_challenge_false_contradictions": false_positives[1]
        <= false_positives[0],
        "no_recorded_deterministic_fallback": all(
            not u["recorded_deterministic_fallbacks"] for u in usage
        ),
    }
    summary["pairs"].append(
        {
            "trial": trial,
            "artifacts": [
                {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in paths
            ],
            "controls": controls,
            "source_delta": source_delta,
            "historical_controls": negatives,
            "baseline_metrics": bm,
            "candidate_metrics": cm,
            "false_contradictions": false_positives,
            "criteria": criteria,
            "passed": all(criteria.values()),
            "physical_requests": [len(d["physical_requests"]) for d in (b, c)],
        }
    )
summary["complete"] = len(summary["pairs"]) == 3 and all(
    "criteria" in p for p in summary["pairs"]
)
summary["accepted"] = summary["complete"] and all(p["passed"] for p in summary["pairs"])
(root / "opposition-paired-summary.json").write_text(
    json.dumps(summary, indent=2) + "\n"
)
print(
    json.dumps(
        {
            "complete": summary["complete"],
            "accepted": summary["accepted"],
            "pairs": len(summary["pairs"]),
        }
    )
)

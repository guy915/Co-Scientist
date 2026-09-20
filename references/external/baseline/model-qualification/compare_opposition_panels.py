"""Validate frozen paired artifacts; never run inference or relax gates."""

import argparse
import json
import sys
import hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from evaluations.panel_comparison import compare_panels

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--series",
    choices=(
        "opposition",
        "opposition-pro",
        "opposition-retrieval-pro",
        "opposition-scope-pro",
    ),
    default="opposition",
)
parser.add_argument("--attempt", choices=("recovery1",))
args = parser.parse_args()
series = args.series
if args.attempt and series != "opposition-scope-pro":
    parser.error("Recovery is only recorded for the scope series")
root = Path(__file__).resolve().parent
summary = {
    "baseline_commit": "14e8c59950204c96cdfa2195594885383d1d5720",
    "candidate_commit": "06a17a70e9aaf7d3f51bbc8c5c8157825c82c368",
    "pairs": [],
    "complete": False,
    "accepted": False,
}
if args.attempt:
    summary["attempt"] = args.attempt
scope = series == "opposition-scope-pro"
composite = scope or series == "opposition-retrieval-pro"
if composite:
    summary["candidate_commit"] = "94107aedd9c68df9811c69c48b3ac0b7d2ec119f"
    preflight = json.loads(
        (
            root / ("scope-preflight.json" if scope else "retrieval-preflight.json")
        ).read_text()
    )
    frozen = preflight["source_manifest"]
    if scope:
        summary["candidate_commit"] = "03ea84841983c93da170902c05b3fd846fb87360"
        from scope_controls import validate_scope_evidence
        from comparison_recovery import (
            validate_execution_sources,
            validate_recovery_catalog,
        )

        scope_dataset = json.loads(
            (root / "partial-support-scope-controls.json").read_text()
        )
source_snapshots = {}
for trial in range(1, 4):
    recovered = bool(args.attempt and trial in (2, 3))
    suffix = f"-{args.attempt}" if recovered else ""
    paths = [
        root / f"{series}-{arm}-{trial}{suffix}.json"
        for arm in ("baseline", "candidate")
    ]
    if not all(p.exists() for p in paths):
        if args.attempt:
            raise RuntimeError(f"Missing recovery artifacts for trial {trial}")
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
    if composite:
        for arm, data in (("baseline", b), ("candidate", c)):
            if data["controls_sha256"] != frozen["controls_sha256"]:
                raise RuntimeError("Historical controls differ from frozen inputs")
            if (
                data["requested_model"] != frozen["model"]
                or data["source_manifest_sha256"] != preflight["source_manifest_sha256"]
            ):
                raise RuntimeError("Model or frozen manifest differs")
            if any(
                data["runtime"].get(k) != preflight["runtime"][k]
                for k in ("python", "executable")
            ):
                raise RuntimeError("Trial runtime differs")
            if data["source_revisions"] != frozen["arms"][arm]["subtree_revisions"]:
                raise RuntimeError("Composite source revisions mismatch")
            for module, entry in data["verified_project_imports"].items():
                if (
                    entry["sha256"]
                    != frozen["arms"][arm]["verified_sources"][entry["path"]]["sha256"]
                ):
                    raise RuntimeError(f"Imported source mismatch: {module}")
            if not data["verified_project_imports"]:
                raise RuntimeError("Missing transitive import evidence")
        source_delta = {
            "scope": "Composite app/engine candidate; no individual-change causal attribution",
            "subtree_revisions": {
                "baseline": b["source_revisions"],
                "candidate": c["source_revisions"],
            },
            "verified_project_import_counts": [
                len(d["verified_project_imports"]) for d in (b, c)
            ],
        }
        if (
            b["challenge_sha256"] != c["challenge_sha256"]
            or b["source_guard_sha256"] != c["source_guard_sha256"]
        ):
            raise RuntimeError("Comparison observers or inputs differ")
        catalog = json.loads(
            (root / f"{series}-catalog-{trial}{suffix}.json").read_text()
        )
        if any(
            d["probe_sha256"] != catalog["execution_sources"]["probe_citation_panel.py"]
            for d in (b, c)
        ):
            raise RuntimeError("Probe differs from frozen batch observer")
    bm, cm = b["report"]["metrics"], c["report"]["metrics"]
    false_positives = []
    for d in (b, c):
        for req in d["physical_requests"]:
            if composite:
                usage_record = req.get("usage")
                if not isinstance(usage_record, dict) or any(
                    not isinstance(usage_record.get(k), (int, float))
                    or usage_record[k] < 0
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                ):
                    raise RuntimeError("Missing physical request usage evidence")
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
    earlier, later = (c, b) if composite and trial == 2 else (b, c)
    assert (
        datetime.fromisoformat(later["physical_requests"][0]["started_at"])
        - datetime.fromisoformat(earlier["physical_requests"][-1]["started_at"])
    ).total_seconds() >= 4
    if (
        composite
        and hybrid.get("verification_method") != "model_opposition_unconfirmed"
    ):
        raise RuntimeError("Hybrid did not record a rejected secondary verification")
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
    if scope:
        for name, field in (
            ("partial-support-scope-controls.json", "scope_controls_sha256"),
            ("scope_controls.py", "scope_helper_sha256"),
        ):
            expected = hashlib.sha256((root / name).read_bytes()).hexdigest()
            if (
                expected != frozen[field]
                or any(d[field] != expected for d in (b, c))
                or catalog["execution_sources"][name] != expected
            ):
                raise RuntimeError("Scope helper or inputs differ from frozen identity")
        validate_execution_sources(root, catalog, recovered=recovered)
        if recovered:
            validate_recovery_catalog(
                root, catalog, trial, preflight["source_manifest_sha256"]
            )
        # Baseline provenance stays unknown. Its outcomes are observed, not
        # relabeled to satisfy candidate-only provenance acceptance.
        validate_scope_evidence(b, scope_dataset)
        criteria["candidate_scope_controls"] = validate_scope_evidence(c, scope_dataset)
        for mode in ("single", "batch_single_claim"):
            before, after = b["scope_controls"][mode], c["scope_controls"][mode]
            compare_panels(before, after)
            if before["evaluation_identity"]["dataset"] != scope_dataset:
                raise RuntimeError("Scope capture inputs differ")
            criteria["no_recorded_deterministic_fallback"] &= all(
                not panel["usage_evidence"]["recorded_deterministic_fallbacks"]
                for panel in (before, after)
            )
    flips = []
    if composite:
        left = [a for a in b["assessments"] if a["phase"] == "challenge"]
        right = [a for a in c["assessments"] if a["phase"] == "challenge"]
        if len(left) != len(right) or len(left) != 30:
            raise RuntimeError("Incomplete item-level assessment evidence")
        for index, (before, after) in enumerate(zip(left, right)):
            if before["claim"] != after["claim"]:
                raise RuntimeError("Assessment inputs differ")
            if before["label"] != after["label"]:
                flips.append(
                    {
                        "index": index,
                        "baseline": before["label"],
                        "candidate": after["label"],
                    }
                )
    summary["pairs"].append(
        {
            "trial": trial,
            **(
                {"attempt": args.attempt, "recovery_of": catalog["recovery_of"]}
                if recovered
                else {}
            ),
            **({"item_label_flips": flips} if composite else {}),
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
(
    root / f"{series}-paired-summary{'-' + args.attempt if args.attempt else ''}.json"
).write_text(json.dumps(summary, indent=2) + "\n")
print(
    json.dumps(
        {
            "complete": summary["complete"],
            "accepted": summary["accepted"],
            "pairs": len(summary["pairs"]),
        }
    )
)

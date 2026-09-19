"""Verify declared-input comparability before emitting multi-arm results."""

import hashlib
from collections.abc import Sequence
from typing import Any

from evaluations._comparison_identity import identity_digest, validate_identity


def _arm_controls(record: dict[str, Any], kind: str) -> dict[str, Any]:
    identity = validate_identity(record.get("evaluation_identity"))
    if identity.get("cache_policy") != "disabled":
        raise ValueError("comparison requires disabled response caching")
    goal = record.get("goal")
    if (
        not isinstance(goal, str)
        or identity["goal_sha256"] != hashlib.sha256(goal.encode()).hexdigest()
    ):
        raise ValueError("comparison goal does not match its identity")
    config = identity["resolved_config"]
    if record.get("tier") != config.get("tier"):
        raise ValueError("comparison tier does not match its identity")
    baseline = identity.get("baseline_config")
    overrides = record.get("overrides")
    if not isinstance(baseline, dict) or not isinstance(overrides, dict):
        raise ValueError("comparison requires frozen baseline and overrides")
    _check_config(config, baseline, overrides, kind)
    controls = {
        key: value
        for key, value in identity.items()
        if key
        not in {
            "digest",
            "goal_sha256",
            "resolved_config",
            "baseline_config",
            "tier_fields",
        }
    }
    controls["baseline_config"] = _baseline_controls(identity, kind)
    return controls


def _check_config(
    config: dict[str, Any],
    baseline: dict[str, Any],
    overrides: dict[str, Any],
    kind: str,
) -> None:
    if kind == "scaling" and overrides:
        raise ValueError("comparison scaling cannot override tier defaults")
    _check_declared_overrides(config, baseline, overrides)
    for key in config.keys() | baseline.keys():
        if config.get(key) == baseline.get(key):
            continue
        if key not in overrides or config.get(key) != overrides[key]:
            raise ValueError(
                "comparison has an undeclared configuration change"
            )


def _check_declared_overrides(
    config: dict[str, Any],
    baseline: dict[str, Any],
    overrides: dict[str, Any],
) -> None:
    for key, value in overrides.items():
        if (
            key not in config
            or config[key] != value
            or baseline.get(key) == value
        ):
            raise ValueError(
                "comparison declares an unapplied or unchanged override"
            )


def _baseline_controls(identity: dict[str, Any], kind: str) -> dict[str, Any]:
    baseline: dict[str, Any] = dict(identity["baseline_config"])
    setup = dict(baseline["setup"])
    setup.pop("goal", None)
    if kind == "scaling":
        fields = identity.get("tier_fields")
        if not isinstance(fields, list) or not fields:
            raise ValueError("comparison requires frozen tier fields")
        for field in [*fields, "tier"]:
            baseline.pop(field, None)
        setup.pop("tier", None)
    baseline["setup"] = setup
    return baseline


def validate_comparison(
    records: Sequence[dict[str, Any]],
    *,
    kind: str,
) -> dict[str, Any]:
    """Match declared controls, not scientific quality or retrieved evidence.

    Frozen baseline profiles avoid interpreting old runs through today's tier
    defaults. These are provenance checks, not signatures against tampering.
    """
    if kind not in {"scaling", "ablation"}:
        raise ValueError("unknown comparison kind")
    controls = [_arm_controls(record, kind) for record in records]
    if len({identity_digest(control) for control in controls}) > 1:
        raise ValueError("comparison controls differ; rerun both arms")
    _match_goals(records, kind)
    if kind == "ablation" and records:
        _match_ablation_arms(records)
    return {
        "status": "matched_declared_inputs" if records else "empty",
        "kind": kind,
        "arm_count": len(records),
        "retrieval_matching": "not_verified",
    }


def _match_goals(records: Sequence[dict[str, Any]], kind: str) -> None:
    goals: dict[str, set[str]] = {}
    for record in records:
        group = "scaling" if kind == "scaling" else str(record.get("goal_id"))
        goals.setdefault(group, set()).add(
            record["evaluation_identity"]["goal_sha256"]
        )
    if any(len(values) != 1 for values in goals.values()):
        raise ValueError("comparison goal identities differ")
    if kind == "ablation" and len(set.union(set(), *goals.values())) != len(
        goals
    ):
        raise ValueError("comparison repeats one goal under different labels")


def _match_ablation_arms(records: Sequence[dict[str, Any]]) -> None:
    groups: dict[str, set[str]] = {}
    for record in records:
        goal_id, arm = record.get("goal_id"), record.get("arm")
        if not isinstance(goal_id, str) or not isinstance(arm, str):
            raise ValueError("comparison ablations require goal and arm labels")
        group = groups.setdefault(goal_id, set())
        if arm in group or (arm == "baseline" and record["overrides"]):
            raise ValueError(
                "comparison has duplicate arms or an altered baseline"
            )
        group.add(arm)
    expected = set.union(*groups.values())
    if "baseline" not in expected or any(
        arms != expected for arms in groups.values()
    ):
        raise ValueError("comparison ablations require paired baseline arms")

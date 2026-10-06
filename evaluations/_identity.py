"""Identity hashing avoids execution imports; snapshots load app/engine
dependencies only when needed.
"""

import hashlib
import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_POLICY_FILES = (
    "constants/__init__.py",
    "llm/values.py",
    "llm/profile/__init__.py",
    "llm/request/backend.py",
    "llm/request/completion.py",
    "llm/admission/free_policy.py",
    "llm/request/thinking.py",
    "llm/attempts/escalation.py",
)


def identity_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def request_policy() -> dict[str, str]:
    engine = _ROOT / "engine" / "src" / "co_scientist"
    return {
        name: hashlib.sha256((engine / name).read_bytes()).hexdigest() for name in _POLICY_FILES
    }


def validate_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("comparison identity is missing or unsupported")
    contents = {key: item for key, item in value.items() if key != "digest"}
    if value.get("digest") != identity_digest(contents):
        raise ValueError("comparison identity digest does not match its contents")
    return value


def _configured_models() -> dict[str, str | None]:
    from app.config import settings

    return {
        "worker": settings.model_name,
        "supervisor": settings.supervisor_model_name or settings.model_name,
        "chat": settings.chat_model_name or settings.model_name,
        "safety": settings.semantic_safety_model,
        "claim_verifier": settings.claim_verifier_model or settings.model_name,
    }


def _tools_identity() -> dict[str, str | None]:
    from app.config import settings

    config = settings.tools_config
    local = Path(config) if config and "://" not in config else None
    return {
        "configuration_sha256": identity_digest(config),
        "local_contents_sha256": (
            hashlib.sha256(local.read_bytes()).hexdigest() if local else None
        ),
        "mcp_endpoint_sha256": identity_digest(os.getenv("MCP_SERVER_URL")),
    }


def _baseline_config(goal: str, tier: str) -> dict[str, Any]:
    from app.run_modes import resolved_run_config, setup_config

    baseline: dict[str, Any] = resolved_run_config(
        {"setup": setup_config(research_goal=goal, tier=tier), "tier": tier}
    )
    return baseline


def _model_policy() -> dict[str, Any]:
    from app.config import settings
    from co_scientist.llm import deepseek_thinking_extra_body

    models = _configured_models()
    policy = request_policy()
    return {
        "configured_models": models,
        "routing": {
            model: {
                "reasoning_enabled": deepseek_thinking_extra_body(model),
                "reasoning_disabled": deepseek_thinking_extra_body(model, enabled=False),
            }
            for model in sorted({m for m in models.values() if m})
        },
        "claim_assessor": settings.claim_assessor,
        "request_policy_files": policy,
        "request_policy_sha256": identity_digest(policy),
    }


def arm_identity(
    goal: str,
    config: dict[str, Any],
    backend: str,
) -> dict[str, Any]:
    """Hash paths/endpoints because they may contain credentials; declared
    controls do not prove served evidence.
    """
    if os.getenv("COSCIENTIST_CACHE_ENABLED") != "0":
        raise ValueError("comparison identity requires disabled response caches")
    from app.run_modes import RUN_TIER_DEFAULTS

    tier = config["tier"]
    manifest = {
        "version": 1,
        "goal_sha256": hashlib.sha256(goal.encode()).hexdigest(),
        "backend": backend,
        "resolved_config": config,
        "baseline_config": _baseline_config(goal, tier),
        "tier_fields": sorted(RUN_TIER_DEFAULTS[tier]),
        **_model_policy(),
        "tools": _tools_identity(),
        "cache_policy": "disabled",
        "execution_environment": {
            name: os.getenv(name)
            for name in (
                "COSCIENTIST_REQUIRE_FREE_MODELS",
                "COSCIENTIST_FORCE_OFFLINE",
                "FORCE_LITERATURE_REVIEW",
                "PYTHONHASHSEED",
            )
        },
    }
    # Snapshot mutable config/routing maps before placing this in run.config.
    frozen: dict[str, Any] = json.loads(json.dumps(manifest))
    return {**frozen, "digest": identity_digest(frozen)}


def validate_stored_arm(
    run_id: str,
    db_path: str,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.store import runs

    run = runs.get_run(run_id, db_path=db_path)
    if run is None:
        raise ValueError("comparison run is missing")
    identity = validate_identity(run.config.get("evaluation_identity"))
    if expected is not None and identity != expected:
        raise ValueError("comparison identity changed during execution")
    config = {key: value for key, value in run.config.items() if key != "evaluation_identity"}
    current = arm_identity(run.research_goal, config, str(run.llm_backend))
    if current != identity:
        raise ValueError("comparison controls changed; rerun both arms")
    return identity


PANEL_FILES = {
    "citation_entailment": "citation_eval.py",
    "citation_usefulness": "citation_usefulness_eval.py",
    "elo_concordance": "elo_concordance_eval.py",
}


def _identity(
    panel: str,
    dataset: dict[str, Any],
    model: str,
    live: bool,
) -> dict[str, Any]:
    from co_scientist.llm import deepseek_thinking_extra_body

    source = Path(__file__).parent / PANEL_FILES[panel]
    fields = {
        "version": 1,
        "kind": "panel",
        "panel": panel,
        "dataset": dataset,
        "model": model,
        "execution_mode": "live_requested" if live else "offline",
        "cache_policy": "disabled",
        "evaluator_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "request_policy_files": request_policy(),
        "routing": {
            "reasoning_enabled": deepseek_thinking_extra_body(model),
            "reasoning_disabled": deepseek_thinking_extra_body(model, enabled=False),
        }
        if live
        else {},
    }
    frozen: dict[str, Any] = json.loads(json.dumps(fields))
    return {**frozen, "digest": identity_digest(frozen)}


@contextmanager
def capture_panel(
    panel: str,
    dataset: dict[str, Any],
    model: str,
    *,
    live: bool,
) -> Iterator[dict[str, Any]]:
    from co_scientist.cache import scoped_cache_override

    from evaluations._usage_evidence import capture_usage

    identity = _identity(panel, dataset, model, live)
    with (
        scoped_cache_override(False),
        capture_usage(panel, live=live) as evidence,
    ):
        evidence["evaluation_identity"] = identity
        yield evidence
        if _identity(panel, dataset, model, live) != identity:
            raise ValueError("comparison panel inputs changed during execution")


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
            raise ValueError("comparison has an undeclared configuration change")


def _check_declared_overrides(
    config: dict[str, Any],
    baseline: dict[str, Any],
    overrides: dict[str, Any],
) -> None:
    for key, value in overrides.items():
        if key not in config or config[key] != value or baseline.get(key) == value:
            raise ValueError("comparison declares an unapplied or unchanged override")


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
    """Frozen profiles avoid reinterpreting old runs through current tiers;
    provenance checks are not signatures.
    """
    if kind not in {"scaling", "ablation"}:
        raise ValueError("unknown comparison kind")
    controls = [_arm_controls(record, kind) for record in records]
    if len({identity_digest(control) for control in controls}) > 1:
        raise ValueError("comparison controls differ; rerun both arms")
    _match_goals(records, kind)
    if kind == "ablation" and records:
        _match_ablation_arms(records)
        _match_ablation_interventions(records)
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
        goals.setdefault(group, set()).add(record["evaluation_identity"]["goal_sha256"])
    if any(len(values) != 1 for values in goals.values()):
        raise ValueError("comparison goal identities differ")
    if kind == "ablation" and len(set.union(set(), *goals.values())) != len(goals):
        raise ValueError("comparison repeats one goal under different labels")


def _match_ablation_arms(records: Sequence[dict[str, Any]]) -> None:
    groups: dict[str, set[str]] = {}
    for record in records:
        goal_id, arm = record.get("goal_id"), record.get("arm")
        if not isinstance(goal_id, str) or not isinstance(arm, str):
            raise ValueError("comparison ablations require goal and arm labels")
        group = groups.setdefault(goal_id, set())
        if arm in group or (arm == "baseline" and record["overrides"]):
            raise ValueError("comparison has duplicate arms or an altered baseline")
        group.add(arm)
    expected = set.union(*groups.values())
    if "baseline" not in expected or any(arms != expected for arms in groups.values()):
        raise ValueError("comparison ablations require paired baseline arms")


def _match_ablation_interventions(records: Sequence[dict[str, Any]]) -> None:
    interventions: dict[str, dict[str, Any]] = {}
    for record in records:
        overrides = record["overrides"]
        if interventions.setdefault(record["arm"], overrides) != overrides:
            raise ValueError("comparison arm interventions differ across goals")

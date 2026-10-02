"""Reproducible, non-secret inputs for controlled research comparisons."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from evaluations._identity import (
    identity_digest,
    request_policy,
    validate_identity,
)


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
                "reasoning_disabled": deepseek_thinking_extra_body(
                    model, enabled=False
                ),
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
    """Freeze declared inputs; this is not proof of served models or evidence.

    Routing is rendered by the production builder for both reasoning modes.
    Paths/endpoints are hashed because custom values can contain credentials.
    Retrieved evidence is an output here and needs a separately matched replay
    when a scientific comparison requires identical source material.
    """
    if os.getenv("COSCIENTIST_CACHE_ENABLED") != "0":
        raise ValueError(
            "comparison identity requires disabled response caches"
        )
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
    """Check the stored controls and current process before/after execution."""
    from app import store

    run = store.get_run(run_id, db_path=db_path)
    if run is None:
        raise ValueError("comparison run is missing")
    identity = validate_identity(run.config.get("evaluation_identity"))
    if expected is not None and identity != expected:
        raise ValueError("comparison identity changed during execution")
    config = {
        key: value
        for key, value in run.config.items()
        if key != "evaluation_identity"
    }
    current = arm_identity(run.research_goal, config, str(run.llm_backend))
    if current != identity:
        raise ValueError("comparison controls changed; rerun both arms")
    return identity

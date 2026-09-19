"""Reproducible, non-secret inputs for controlled research comparisons."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_POLICY_FILES = (
    "constants.py",
    "constants_tokens.py",
    "llm_types.py",
    "llm_request.py",
    "llm_gateway_routing.py",
    "llm_gateway_body.py",
    "llm_thinking.py",
    "llm_request_schema.py",
    "llm_json_escalation.py",
)


def identity_digest(value: Any) -> str:
    """Hash canonical JSON without depending on dict insertion order."""
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _configured_models() -> dict[str, str | None]:
    from app.config import settings

    return {
        "worker": settings.model_name,
        "supervisor": settings.supervisor_model_name or settings.model_name,
        "chat": settings.chat_model_name or settings.model_name,
        "safety": settings.semantic_safety_model,
        "claim_verifier": settings.claim_verifier_model or settings.model_name,
    }


def _request_policy() -> dict[str, str]:
    engine = _ROOT / "engine" / "src" / "co_scientist"
    return {
        name: hashlib.sha256((engine / name).read_bytes()).hexdigest()
        for name in _POLICY_FILES
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
    from app.config import settings
    from co_scientist.llm_gateway_body import deepseek_thinking_extra_body

    if os.getenv("COSCIENTIST_CACHE_ENABLED") != "0":
        raise ValueError(
            "comparison identity requires disabled response caches"
        )
    models = _configured_models()
    policy = _request_policy()
    manifest = {
        "version": 1,
        "goal_sha256": hashlib.sha256(goal.encode()).hexdigest(),
        "backend": backend,
        "resolved_config": config,
        "configured_models": models,
        "routing": {
            model: {
                "reasoning_enabled": deepseek_thinking_extra_body(model),
                "reasoning_disabled": deepseek_thinking_extra_body(
                    model,
                    enabled=False,
                ),
            }
            for model in sorted({m for m in models.values() if m})
        },
        "claim_assessor": settings.claim_assessor,
        "request_policy_files": policy,
        "request_policy_sha256": identity_digest(policy),
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


def validate_identity(value: Any) -> dict[str, Any]:
    """Reject missing, unsupported or altered comparison evidence."""
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("comparison identity is missing or unsupported")
    contents = {key: item for key, item in value.items() if key != "digest"}
    if value.get("digest") != identity_digest(contents):
        raise ValueError(
            "comparison identity digest does not match its contents"
        )
    return value


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

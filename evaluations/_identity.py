"""Shared identity sealing and engine request-policy snapshots.

Run comparisons and direct panels share this format without importing each
other's configuration or execution code. All helpers use the standard library.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_POLICY_FILES = (
    "constants/__init__.py",
    "constants/tokens.py",
    "llm/values.py",
    "llm/profile/families.py",
    "llm/profile/routes.py",
    "llm/request/backend.py",
    "llm/request/completion.py",
    "llm/admission/free_policy.py",
    "llm/admission/free_catalog.py",
    "llm/request/gateway_routing.py",
    "llm/request/gateway_body.py",
    "llm/request/thinking.py",
    "llm/request/schema.py",
    "llm/attempts/escalation.py",
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


def request_policy() -> dict[str, str]:
    """Snapshot current request-policy bytes for execution drift checks."""
    engine = _ROOT / "engine" / "src" / "co_scientist"
    return {
        name: hashlib.sha256((engine / name).read_bytes()).hexdigest()
        for name in _POLICY_FILES
    }


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

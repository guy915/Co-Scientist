"""Freeze direct scientific panels before evaluating their ordered inputs."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from evaluations._identity import identity_digest, request_policy
from evaluations._usage_evidence import capture_usage

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
            "reasoning_disabled": deepseek_thinking_extra_body(
                model, enabled=False
            ),
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
    """Capture declared controls and usage; reject input/policy drift."""
    from co_scientist.cache import scoped_cache_override

    identity = _identity(panel, dataset, model, live)
    with (
        scoped_cache_override(False),
        capture_usage(panel, live=live) as evidence,
    ):
        evidence["evaluation_identity"] = identity
        yield evidence
        if _identity(panel, dataset, model, live) != identity:
            raise ValueError("comparison panel inputs changed during execution")

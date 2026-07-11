"""The ``cosci status`` command: API health plus system diagnostics."""

from __future__ import annotations

import argparse
from typing import Any

from app.cli.http import ApiClient
from app.cli.render import emit_json, format_kv


def handle_status(args: argparse.Namespace, client: ApiClient) -> int:
    """Print API health and provider/literature availability.

    Combines ``GET /health`` and ``GET /status`` into a single view so an
    operator can confirm the API is up and see whether it will run the real
    engine or the deterministic mock before creating a run.
    """
    as_json: bool = args.json
    health = client.request_json("GET", "/health")
    status = client.request_json("GET", "/status")
    if as_json:
        emit_json({"health": health, "status": status})
        return 0
    pairs: list[tuple[str, Any]] = [
        ("status", health.get("status")),
        ("version", health.get("version")),
        ("model", health.get("model_name")),
        ("provider", status.get("provider")),
        ("mock_mode", status.get("mock_mode")),
        ("has_provider_key", status.get("has_provider_key")),
        ("engine_importable", status.get("engine_importable")),
        ("mcp_available", status.get("mcp_available")),
        ("pubmed_available", status.get("pubmed_available")),
        ("literature_review", status.get("literature_review_available")),
    ]
    print(format_kv(pairs))
    return 0

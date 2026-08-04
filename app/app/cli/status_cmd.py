"""The ``cosci status`` command: API health plus system diagnostics."""

from __future__ import annotations

import argparse
from typing import Any

from app.cli.http import ApiClient, expect_object
from app.cli.render import emit_json, format_kv


def handle_status(args: argparse.Namespace, client: ApiClient) -> int:
    """Print API health and provider/literature availability.

    Combines ``GET /health`` and ``GET /status`` into a single view so an
    operator can confirm the API is up and see whether it has a real LLM
    provider configured or will fall back to the deterministic offline
    backend before creating a run.
    """
    as_json: bool = args.json
    health = client.request_json("GET", "/health")
    status = client.request_json("GET", "/status")
    if as_json:
        emit_json({"health": health, "status": status})
        return 0
    health = expect_object(health, "/health")
    status = expect_object(status, "/status")
    pairs: list[tuple[str, Any]] = [
        ("status", health.get("status")),
        ("version", health.get("version")),
        ("model", health.get("model_name")),
        ("provider", status.get("provider")),
        ("llm_backend", status.get("llm_backend")),
        ("has_provider_key", status.get("has_provider_key")),
        ("engine_importable", status.get("engine_importable")),
        ("mcp_available", status.get("mcp_available")),
        ("pubmed_available", status.get("pubmed_available")),
        ("literature_review", status.get("literature_review_available")),
    ]
    print(format_kv(pairs))
    return 0


def handle_config(args: argparse.Namespace, client: ApiClient) -> int:
    """Print the server's run-configuration defaults (GET /config)."""
    as_json: bool = args.json
    config = client.request_json("GET", "/config")
    if as_json:
        emit_json(config)
        return 0
    config = expect_object(config, "/config")
    pairs: list[tuple[str, Any]] = sorted(config.items())
    print(format_kv(pairs))
    return 0

"""CLI setup, diagnostics commands, argument parsing and dispatch.

The command client stays import-light (stdlib and httpx) so --help does not
load FastAPI or the engine. Run and log commands have their own handlers;
this module owns connection setup and persistent default identity.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import uuid
from pathlib import Path
from typing import Any, cast

from app import API_VERSION
from app.cli.http import ApiClient, ApiClientOptions, CliError, expect_object
from app.cli.parsers import (
    Handler,
    _add_leaf_command,
    _add_logs,
    _add_runs,
    _common_parser,
)
from app.cli.render import emit_json, format_kv


def build_parser() -> argparse.ArgumentParser:
    """Construct the full ``cosci`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="cosci",
        description="Operator CLI for driving Co-Scientist runs via its API.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"cosci {API_VERSION}",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    common = _common_parser()
    for name, handler, help_text in (
        (
            "status",
            handle_status,
            "show API health and provider/literature availability",
        ),
        (
            "config",
            handle_config,
            "show the server's run-configuration defaults",
        ),
    ):
        _add_leaf_command(sub, common, name, handler, help_text)
    _add_logs(sub, common)
    _add_runs(sub, common)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, dispatch to the selected handler, and return its code.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: 0 on success, non-zero on error (2 when no
        command is given, or the handler's own code).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2
    # Resolved lazily, after the no-command/--help exits above, so those
    # paths never touch disk; an explicit --client-id or
    # COSCIENTIST_CLIENT_ID (already in args.client_id) still wins.
    client = ApiClient(
        args.api_url,
        args.client_id or default_client_id(),
        logs_token=args.logs_token,
        options=ApiClientOptions(timeout=args.timeout, verbose=args.verbose),
    )
    try:
        return cast(Handler, handler)(args, client)
    except CliError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # stdout's reader is gone (e.g. `cosci ... | head`). Point the fd at
        # devnull so interpreter shutdown does not raise while flushing;
        # skip it where stdout has no usable fd (test capture, redirection).
        with contextlib.suppress(OSError, ValueError):
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        return 141
    finally:
        client.close()


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


_FILE_NAME = "client_id"


def _config_dir() -> Path:
    """Return the directory the persistent client id is stored under.

    ``COSCIENTIST_CLI_CONFIG_DIR`` overrides the location outright --
    used by the test suite to keep the generated id off a real machine's
    home directory. Otherwise this follows the XDG convention
    (``XDG_CONFIG_HOME``, defaulting to ``~/.config``).
    """
    override = os.environ.get("COSCIENTIST_CLI_CONFIG_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "co-scientist"


def default_client_id() -> str:
    """Return this machine's persistent client id, creating one on first use.

    Reading and writing are not atomic against a concurrent first
    invocation racing to create the file, but the race is harmless:
    whichever id lands on disk last is what every later invocation reads,
    and losing an id generated by a process that exits immediately after
    costs nothing a user would notice. A directory that cannot be created
    or written (a read-only home, a sandboxed environment) degrades to a
    fresh id for this process alone rather than failing the command.

    Returns:
        The persisted id, generated and written to disk if none exists.
    """
    path = _config_dir() / _FILE_NAME
    try:
        existing = path.read_text().strip()
        if existing:
            return existing
    except OSError:
        pass
    generated = f"cli-{uuid.uuid4().hex}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generated)
    except OSError:
        pass
    return generated

"""Argument parser and dispatch for the ``cosci`` operator CLI.

Builds an ``argparse`` command tree whose leaves each carry a ``handler`` set
via ``set_defaults``; ``main`` parses arguments, constructs the shared
:class:`ApiClient`, and invokes the selected handler. Command handlers live in
``status_cmd``, ``logs_cmd``, ``runs_cmd``, and ``runs_stream_cmd``; the
per-group parser builders live in ``app.cli.parsers``. Kept import-light
(stdlib + httpx only) so ``cosci --help`` does not pull in FastAPI or the
engine.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from typing import cast

# Imported as a module, not as its handlers, so that patching
# ``app.cli.main.status_cmd.handle_status`` reaches the parser default (which
# is resolved when ``build_parser`` runs, not at import time).
from app.cli import status_cmd as status_cmd
from app.cli.http import ApiClient, ApiClientOptions, CliError
from app.cli.identity import default_client_id
from app.cli.parsers import (
    Handler,
    _add_leaf_command,
    _add_logs,
    _add_runs,
    _common_parser,
)
from app.version import API_VERSION


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
            status_cmd.handle_status,
            "show API health and provider/literature availability",
        ),
        (
            "config",
            status_cmd.handle_config,
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

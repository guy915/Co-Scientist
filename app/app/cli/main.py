"""Argument parser and dispatch for the ``cosci`` operator CLI.

Builds an ``argparse`` command tree whose leaves each carry a ``handler`` set
via ``set_defaults``; ``main`` parses arguments, constructs the shared
:class:`ApiClient`, and invokes the selected handler. Command handlers live in
``status_cmd`` and ``runs_cmd``; the per-group parser builders were split into
``app.cli.parsers`` and are re-exported here. Kept import-light (stdlib +
httpx only) so ``cosci --help`` does not pull in FastAPI or the engine.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from typing import cast

from app.cli import logs_cmd as logs_cmd
from app.cli import runs_cmd as runs_cmd
from app.cli import status_cmd as status_cmd
from app.cli.http import ApiClient, CliError
from app.cli.parsers import (
    DEFAULT_TIMEOUT as DEFAULT_TIMEOUT,
)
from app.cli.parsers import (
    RUN_FOCUS_VALUES as RUN_FOCUS_VALUES,
)
from app.cli.parsers import (
    RUN_TIER_VALUES as RUN_TIER_VALUES,
)
from app.cli.parsers import (
    Handler as Handler,
)
from app.cli.parsers import (
    _add_config as _add_config,
)
from app.cli.parsers import (
    _add_create as _add_create,
)
from app.cli.parsers import (
    _add_logs as _add_logs,
)
from app.cli.parsers import (
    _add_run_id_command as _add_run_id_command,
)
from app.cli.parsers import (
    _add_runs as _add_runs,
)
from app.cli.parsers import (
    _add_status as _add_status,
)
from app.cli.parsers import (
    _common_parser as _common_parser,
)
from app.cli.parsers import (
    _default_timeout as _default_timeout,
)
from app.cli.parsers import (
    _json_flag as _json_flag,
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
    _add_status(sub, common)
    _add_config(sub, common)
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
    client = ApiClient(
        args.api_url,
        args.client_id,
        logs_token=args.logs_token,
        timeout=args.timeout,
        verbose=args.verbose,
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

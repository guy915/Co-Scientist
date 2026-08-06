"""Shared option constants and parent parser for the ``cosci`` CLI.

Split from ``app.cli.parsers`` to keep that module small: this module holds
the option-value constants mirrored from the API, the timeout resolution, and
the common parent parser attached to every leaf subcommand (the handler type
alias lives in ``app.cli.types`` and is re-exported here). Kept import-light
(stdlib + httpx only) so ``cosci --help`` does not pull in FastAPI or the
engine.
"""

from __future__ import annotations

import argparse
import os

from app.cli.http import DEFAULT_API_URL
from app.cli.types import Handler as Handler

# Mirror of the enums the API validates (RUN_FOCUS_PATTERN / RUN_TIER_PATTERN
# in app.run_modes). Duplicated here so building the parser stays import-light;
# the API still 422s on any value that drifts from these.
RUN_FOCUS_VALUES = (
    "prefer_evidence",
    "balance",
    "prefer_novelty",
    "breakthrough",
)
RUN_TIER_VALUES = ("express", "standard", "extended", "ultra")

DEFAULT_TIMEOUT = 30.0


def _default_timeout() -> float:
    """Resolve the default request timeout from ``COSCIENTIST_TIMEOUT``.

    An unset or unparsable value falls back to :data:`DEFAULT_TIMEOUT` so a
    stray environment variable cannot make every command crash at parse time.
    """
    raw = os.environ.get("COSCIENTIST_TIMEOUT")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_TIMEOUT


def _json_flag(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``--json`` flag that emits the raw API payload."""
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the raw JSON payload instead of line-oriented text",
    )


def _add_leaf_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
    name: str,
    handler: Handler,
    help_text: str,
) -> argparse.ArgumentParser:
    """Register one leaf subcommand and return it for further arguments.

    Every leaf carries the common connection options, the shared ``--json``
    flag, and a ``handler`` default; anything else (a run id, filters, a
    ``--follow``) is added by the caller on the returned parser.
    """
    parser = sub.add_parser(name, parents=[common], help=help_text)
    _json_flag(parser)
    parser.set_defaults(handler=handler)
    return parser


def _add_connection_options(common: argparse.ArgumentParser) -> None:
    """Add the API URL/client-id/logs-token options to the common parser."""
    common.add_argument(
        "--api-url",
        default=os.environ.get("COSCIENTIST_API_URL") or DEFAULT_API_URL,
        metavar="URL",
        help=(
            "base URL of the Co-Scientist API "
            "(env COSCIENTIST_API_URL, default %(default)s)"
        ),
    )
    common.add_argument(
        "--client-id",
        default=os.environ.get("COSCIENTIST_CLIENT_ID"),
        metavar="ID",
        help=(
            "X-Client-ID header scoping run listings (env "
            "COSCIENTIST_CLIENT_ID); defaults to a persistent id generated "
            "once per machine (see app.cli.identity)"
        ),
    )
    common.add_argument(
        "--logs-token",
        default=os.environ.get("COSCIENTIST_LOGS_TOKEN"),
        metavar="TOKEN",
        help=(
            "admin token for the app-wide log view when the API is not "
            "local (env COSCIENTIST_LOGS_TOKEN)"
        ),
    )


def _add_request_behavior_options(common: argparse.ArgumentParser) -> None:
    """Add the timeout/verbose options to the common parser."""
    common.add_argument(
        "--timeout",
        type=float,
        default=_default_timeout(),
        metavar="SECONDS",
        help=(
            "per-request timeout in seconds "
            "(env COSCIENTIST_TIMEOUT, default %(default)s)"
        ),
    )
    common.add_argument(
        "--verbose",
        action="store_true",
        help="log every request's method, path, status, and time to stderr",
    )


def _common_parser() -> argparse.ArgumentParser:
    """Return the parent parser carrying the global connection options.

    Attached to every leaf subcommand (not the top level) so the options may
    follow the command, e.g. ``cosci runs list --api-url ...``.
    """
    common = argparse.ArgumentParser(add_help=False)
    _add_connection_options(common)
    _add_request_behavior_options(common)
    return common

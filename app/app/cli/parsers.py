"""Parser builders for the ``cosci`` operator CLI.

Split from ``app.cli.main`` to keep that module small: this module holds the
top-level ``status``/``config``/``logs`` registration helpers, and re-exports
the common parent parser (``app.cli.parsers_common``) and the ``runs``
command-group builder (``app.cli.parsers_runs``) so ``app.cli.main`` assembles
the whole tree from one import. ``main`` builds the tree in ``build_parser``
and owns dispatch. Kept import-light (stdlib + httpx only) so ``cosci --help``
does not pull in FastAPI or the engine.
"""

from __future__ import annotations

import argparse

from app.cli import logs_cmd as logs_cmd
from app.cli import status_cmd as status_cmd
from app.cli.parsers_common import _add_leaf_command
from app.cli.parsers_common import _common_parser as _common_parser
from app.cli.parsers_runs import _add_runs as _add_runs


def _add_status(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the top-level ``status`` command."""
    _add_leaf_command(
        sub,
        common,
        "status",
        status_cmd.handle_status,
        "show API health and provider/literature availability",
    )


def _add_config(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the top-level ``config`` command."""
    _add_leaf_command(
        sub,
        common,
        "config",
        status_cmd.handle_config,
        "show the server's run-configuration defaults",
    )


def _add_logs_filter_options(parser: argparse.ArgumentParser) -> None:
    """Add the record-filtering options shared by the ``logs`` command."""
    parser.add_argument(
        "--run", metavar="RUN_ID", help="only records bound to this run"
    )
    parser.add_argument(
        "--level",
        metavar="LEVEL",
        help="minimum level, e.g. warning (case-insensitive)",
    )
    parser.add_argument(
        "--grep", metavar="TEXT", help="message substring filter"
    )
    parser.add_argument(
        "--after-id",
        dest="after_id",
        type=int,
        default=0,
        metavar="N",
        help="only records with id greater than N",
    )
    parser.add_argument(
        "--limit", type=int, default=100, metavar="N", help="max records"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "include high-volume records hidden by default (HTTP access, "
            "UI clicks/navigation, dependency chatter below warning)"
        ),
    )


def _add_logs_action_options(parser: argparse.ArgumentParser) -> None:
    """Add the follow/clear behavior options for the ``logs`` command."""
    parser.add_argument(
        "--follow",
        action="store_true",
        help="keep polling for new records until interrupted",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="poll interval used with --follow (default %(default)s)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="delete every persisted log record instead of reading",
    )


def _add_logs(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the top-level ``logs`` command."""
    parser = _add_leaf_command(
        sub,
        common,
        "logs",
        logs_cmd.handle_logs,
        "query the app-wide persisted log records",
    )
    _add_logs_filter_options(parser)
    _add_logs_action_options(parser)

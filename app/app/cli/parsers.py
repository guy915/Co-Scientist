"""Parser builders for the ``cosci`` operator CLI.

Split from ``app.cli.main`` to keep that module small: this module holds the
top-level ``status``/``config``/``logs`` registration helpers and re-exports
the shared option constants and common parent parser from
``app.cli.parsers_common`` plus the ``runs`` command-group builders from
``app.cli.parsers_runs``. ``app.cli.main`` re-exports every name here, builds
the full tree in ``build_parser``, and owns dispatch. Kept import-light
(stdlib + httpx only) so ``cosci --help`` does not pull in FastAPI or the
engine.
"""

from __future__ import annotations

import argparse

from app.cli import logs_cmd as logs_cmd
from app.cli import runs_cmd as runs_cmd
from app.cli import status_cmd as status_cmd
from app.cli.http import DEFAULT_API_URL as DEFAULT_API_URL
from app.cli.http import ApiClient as ApiClient
from app.cli.parsers_common import (
    DEFAULT_TIMEOUT as DEFAULT_TIMEOUT,
)
from app.cli.parsers_common import (
    RUN_FOCUS_VALUES as RUN_FOCUS_VALUES,
)
from app.cli.parsers_common import (
    RUN_TIER_VALUES as RUN_TIER_VALUES,
)
from app.cli.parsers_common import (
    Handler as Handler,
)
from app.cli.parsers_common import (
    _add_connection_options as _add_connection_options,
)
from app.cli.parsers_common import (
    _add_request_behavior_options as _add_request_behavior_options,
)
from app.cli.parsers_common import (
    _common_parser as _common_parser,
)
from app.cli.parsers_common import (
    _default_timeout as _default_timeout,
)
from app.cli.parsers_common import (
    _json_flag as _json_flag,
)
from app.cli.parsers_runs import (
    _add_create as _add_create,
)
from app.cli.parsers_runs import (
    _add_create_planning_options as _add_create_planning_options,
)
from app.cli.parsers_runs import (
    _add_create_size_overrides as _add_create_size_overrides,
)
from app.cli.parsers_runs import (
    _add_run_content_read_commands as _add_run_content_read_commands,
)
from app.cli.parsers_runs import (
    _add_run_id_command as _add_run_id_command,
)
from app.cli.parsers_runs import (
    _add_run_interaction_commands as _add_run_interaction_commands,
)
from app.cli.parsers_runs import (
    _add_run_lifecycle_commands as _add_run_lifecycle_commands,
)
from app.cli.parsers_runs import (
    _add_run_list_commands as _add_run_list_commands,
)
from app.cli.parsers_runs import (
    _add_run_process_read_commands as _add_run_process_read_commands,
)
from app.cli.parsers_runs import (
    _add_run_read_commands as _add_run_read_commands,
)
from app.cli.parsers_runs import (
    _add_run_streaming_commands as _add_run_streaming_commands,
)
from app.cli.parsers_runs import (
    _add_run_wait_command as _add_run_wait_command,
)
from app.cli.parsers_runs import (
    _add_run_watch_command as _add_run_watch_command,
)
from app.cli.parsers_runs import (
    _add_runs as _add_runs,
)


def _add_status(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the top-level ``status`` command."""
    parser = sub.add_parser(
        "status",
        parents=[common],
        help="show API health and provider/literature availability",
    )
    _json_flag(parser)
    parser.set_defaults(handler=status_cmd.handle_status)


def _add_config(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the top-level ``config`` command."""
    parser = sub.add_parser(
        "config",
        parents=[common],
        help="show the server's run-configuration defaults",
    )
    _json_flag(parser)
    parser.set_defaults(handler=status_cmd.handle_config)


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
    parser = sub.add_parser(
        "logs",
        parents=[common],
        help="query the app-wide persisted log records",
    )
    _add_logs_filter_options(parser)
    _add_logs_action_options(parser)
    _json_flag(parser)
    parser.set_defaults(handler=logs_cmd.handle_logs)

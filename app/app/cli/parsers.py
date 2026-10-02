"""Build the ``cosci`` command tree without importing server code."""

from __future__ import annotations

import argparse
import os

from app.cli import logs_cmd as logs_cmd
from app.cli import runs_cmd
from app.cli import status_cmd as status_cmd
from app.cli.http import DEFAULT_API_URL
from app.cli.types import Handler as Handler

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
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the raw JSON payload instead of line-oriented text",
    )
    parser.set_defaults(handler=handler)
    return parser


def _common_parser() -> argparse.ArgumentParser:
    """Return the parent parser carrying the global connection options.

    Attached to every leaf subcommand (not the top level) so the options may
    follow the command, e.g. ``cosci runs list --api-url ...``.
    """
    common = argparse.ArgumentParser(add_help=False)
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
    return common


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


def _add_create(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs create`` with its config knobs."""
    parser = _add_leaf_command(
        sub,
        common,
        "create",
        runs_cmd.handle_create,
        "create a draft run from a goal",
    )
    parser.add_argument(
        "goal", help="the research goal ('-' reads it from stdin)"
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="immediately start the created run",
    )
    parser.add_argument(
        "--requirement",
        dest="requirements",
        action="append",
        metavar="TEXT",
        help="planning requirement (repeatable)",
    )
    parser.add_argument(
        "--attribute",
        dest="attributes",
        action="append",
        metavar="TEXT",
        help="desired hypothesis attribute (repeatable)",
    )
    parser.add_argument(
        "--criterion",
        dest="criteria",
        action="append",
        metavar="TEXT",
        help="evaluation criterion (repeatable)",
    )
    parser.add_argument(
        "--focus", choices=RUN_FOCUS_VALUES, help="ranking focus"
    )
    parser.add_argument(
        "--tier", choices=RUN_TIER_VALUES, help="run tier / depth"
    )
    parser.add_argument(
        "--initial-hypotheses",
        dest="initial_hypotheses_count",
        type=int,
        metavar="N",
        help="initial hypotheses count override",
    )
    parser.add_argument(
        "--max-iterations",
        dest="max_iterations",
        type=int,
        metavar="N",
        help="max tournament iterations override",
    )
    parser.add_argument(
        "--evolution-max",
        dest="evolution_max_count",
        type=int,
        metavar="N",
        help="max evolved hypotheses override",
    )
    parser.add_argument(
        "--k-factor",
        dest="k_factor",
        type=int,
        metavar="N",
        help="Elo K-factor override",
    )
    parser.add_argument(
        "--literature",
        dest="enable_literature_review",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable literature review (--literature/--no-literature)",
    )


def _add_run_id_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
    name: str,
    handler: Handler,
    help_text: str,
) -> argparse.ArgumentParser:
    """Register a ``runs`` subcommand that takes a single RUN_ID argument."""
    parser = _add_leaf_command(sub, common, name, handler, help_text)
    parser.add_argument("run_id", help="the run identifier")
    return parser


def _add_runs(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``runs`` command group and its subcommands."""
    runs = sub.add_parser("runs", help="create, drive, and inspect runs")
    runs_sub = runs.add_subparsers(dest="runs_command", metavar="SUBCOMMAND")

    list_parser = _add_leaf_command(
        runs_sub,
        common,
        "list",
        runs_cmd.handle_list,
        "list the caller's runs",
    )
    list_parser.add_argument(
        "--limit", type=int, default=100, metavar="N", help="max runs to return"
    )
    _add_leaf_command(
        runs_sub,
        common,
        "demo",
        runs_cmd.handle_demo,
        "list the seeded demo runs",
    )
    _add_run_id_command(
        runs_sub, common, "show", runs_cmd.handle_show, "show run details"
    )
    _add_create(runs_sub, common)
    for name, handler, help_text in (
        ("start", runs_cmd.handle_start, "start a run"),
        ("pause", runs_cmd.handle_pause, "pause an active run"),
        (
            "resume",
            runs_cmd.handle_resume,
            "resume a paused/interrupted run",
        ),
        ("cancel", runs_cmd.handle_cancel, "cancel a run"),
        (
            "delete",
            runs_cmd.handle_delete,
            "permanently delete a terminal run",
        ),
    ):
        _add_run_id_command(runs_sub, common, name, handler, help_text)
    watch_parser = _add_run_id_command(
        runs_sub,
        common,
        "watch",
        runs_cmd.handle_watch,
        "tail a run's event stream until terminal",
    )
    watch_parser.add_argument(
        "--after",
        type=int,
        default=0,
        metavar="SEQ",
        help="only stream events after this sequence number",
    )
    wait_parser = _add_run_id_command(
        runs_sub,
        common,
        "wait",
        runs_cmd.handle_wait,
        "poll until the run settles; exit code encodes the final status "
        "(0 completed, 3 failed, 4 blocked, 5 cancelled, 6 paused, "
        "124 max-wait exceeded)",
    )
    wait_parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="poll interval (default %(default)s)",
    )
    wait_parser.add_argument(
        "--max-wait",
        dest="max_wait",
        type=float,
        default=None,
        metavar="SECONDS",
        help="give up with exit code 124 after this long (default: no limit)",
    )
    for spec in runs_cmd.COLLECTION_COMMANDS:
        _add_run_id_command(
            runs_sub,
            common,
            spec.name,
            runs_cmd.COLLECTION_HANDLERS[spec.name],
            spec.help,
        )
    _add_run_id_command(
        runs_sub,
        common,
        "metrics",
        runs_cmd.handle_metrics,
        "show execution metrics",
    )
    report_parser = _add_run_id_command(
        runs_sub, common, "report", runs_cmd.handle_report, "fetch the report"
    )
    report_parser.add_argument(
        "--md",
        action="store_true",
        help="print the rendered Markdown report instead of a summary",
    )

    steer_parser = _add_run_id_command(
        runs_sub,
        common,
        "steer",
        runs_cmd.handle_steer,
        "queue a steer message",
    )
    steer_parser.add_argument(
        "message", help="the steering message ('-' reads it from stdin)"
    )

    ask_parser = _add_run_id_command(
        runs_sub,
        common,
        "ask",
        runs_cmd.handle_ask,
        "ask a question about a run",
    )
    ask_parser.add_argument(
        "question", help="the question to ask ('-' reads it from stdin)"
    )
    share = runs_sub.add_parser("share", help="manage public Goal Report links")
    share_sub = share.add_subparsers(dest="share_command", metavar="ACTION")
    _add_run_id_command(
        share_sub,
        common,
        "create",
        runs_cmd.handle_share_create,
        "create a public report link",
    )
    _add_run_id_command(
        share_sub,
        common,
        "list",
        runs_cmd.handle_share_list,
        "list active public report links",
    )
    revoke_parser = _add_run_id_command(
        share_sub,
        common,
        "revoke",
        runs_cmd.handle_share_revoke,
        "revoke a public report link",
    )
    revoke_parser.add_argument("share_id", help="the share identifier")

"""Argument parser and dispatch for the ``cosci`` operator CLI.

Builds an ``argparse`` command tree whose leaves each carry a ``handler`` set
via ``set_defaults``; ``main`` parses arguments, constructs the shared
:class:`ApiClient`, and invokes the selected handler. Command handlers live in
``status_cmd`` and ``runs_cmd``. Kept import-light (stdlib + httpx only) so
``cosci --help`` does not pull in FastAPI or the engine.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Callable
from typing import cast

from app.cli import logs_cmd, runs_cmd, status_cmd
from app.cli.http import DEFAULT_API_URL, ApiClient, CliError
from app.version import API_VERSION

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

Handler = Callable[[argparse.Namespace, ApiClient], int]

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
            "X-Client-ID header scoping run listings "
            "(env COSCIENTIST_CLIENT_ID)"
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
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "include high-volume records hidden by default (HTTP access, "
            "UI clicks/navigation, dependency chatter below warning)"
        ),
    )
    _json_flag(parser)
    parser.set_defaults(handler=logs_cmd.handle_logs)


def _add_create(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs create`` with its config knobs."""
    parser = sub.add_parser(
        "create", parents=[common], help="create a draft run from a goal"
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
    _json_flag(parser)
    parser.set_defaults(handler=runs_cmd.handle_create)


def _add_run_id_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
    name: str,
    handler: Handler,
    help_text: str,
) -> argparse.ArgumentParser:
    """Register a ``runs`` subcommand that takes a single RUN_ID argument."""
    parser = sub.add_parser(name, parents=[common], help=help_text)
    parser.add_argument("run_id", help="the run identifier")
    _json_flag(parser)
    parser.set_defaults(handler=handler)
    return parser


def _add_runs(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``runs`` command group and its subcommands."""
    runs = sub.add_parser("runs", help="create, drive, and inspect runs")
    runs_sub = runs.add_subparsers(dest="runs_command", metavar="SUBCOMMAND")

    list_parser = runs_sub.add_parser(
        "list", parents=[common], help="list the caller's runs"
    )
    list_parser.add_argument(
        "--limit", type=int, default=100, metavar="N", help="max runs to return"
    )
    _json_flag(list_parser)
    list_parser.set_defaults(handler=runs_cmd.handle_list)

    demo_parser = runs_sub.add_parser(
        "demo", parents=[common], help="list the seeded demo runs"
    )
    _json_flag(demo_parser)
    demo_parser.set_defaults(handler=runs_cmd.handle_demo)

    _add_run_id_command(
        runs_sub, common, "show", runs_cmd.handle_show, "show run details"
    )
    _add_create(runs_sub, common)

    start_parser = _add_run_id_command(
        runs_sub, common, "start", runs_cmd.handle_start, "start a run"
    )
    start_parser.add_argument(
        "--provider",
        choices=("mock", "engine"),
        help="force the workflow provider for this run",
    )

    _add_run_id_command(
        runs_sub, common, "pause", runs_cmd.handle_pause, "pause an active run"
    )
    _add_run_id_command(
        runs_sub,
        common,
        "resume",
        runs_cmd.handle_resume,
        "resume a paused/interrupted run",
    )
    _add_run_id_command(
        runs_sub, common, "cancel", runs_cmd.handle_cancel, "cancel a run"
    )

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

    _add_run_id_command(
        runs_sub,
        common,
        "hypotheses",
        runs_cmd.handle_hypotheses,
        "list hypotheses",
    )
    _add_run_id_command(
        runs_sub, common, "evidence", runs_cmd.handle_evidence, "list evidence"
    )
    _add_run_id_command(
        runs_sub, common, "reviews", runs_cmd.handle_reviews, "list reviews"
    )
    _add_run_id_command(
        runs_sub,
        common,
        "citations",
        runs_cmd.handle_citations,
        "list citations",
    )
    _add_run_id_command(
        runs_sub, common, "safety", runs_cmd.handle_safety, "list safety rows"
    )
    _add_run_id_command(
        runs_sub,
        common,
        "matches",
        runs_cmd.handle_matches,
        "list tournament matches",
    )
    _add_run_id_command(
        runs_sub,
        common,
        "proximity",
        runs_cmd.handle_proximity,
        "list idea-proximity edges",
    )
    _add_run_id_command(
        runs_sub,
        common,
        "metrics",
        runs_cmd.handle_metrics,
        "show execution metrics",
    )
    _add_run_id_command(
        runs_sub,
        common,
        "claim-evidence",
        runs_cmd.handle_claim_evidence,
        "list claim-level entailment edges",
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

"""Argument parser and dispatch for the ``cosci`` operator CLI.

Builds an ``argparse`` command tree whose leaves each carry a ``handler`` set
via ``set_defaults``; ``main`` parses arguments, constructs the shared
:class:`ApiClient`, and invokes the selected handler. Command handlers live in
``status_cmd`` and ``runs_cmd``. Kept import-light (stdlib + httpx only) so
``cosci --help`` does not pull in FastAPI or the engine.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from typing import cast

from app.cli import runs_cmd, status_cmd
from app.cli.http import DEFAULT_API_URL, ApiClient, CliError

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


def _add_create(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs create`` with its config knobs."""
    parser = sub.add_parser(
        "create", parents=[common], help="create a draft run from a goal"
    )
    parser.add_argument("goal", help="the research goal")
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

    _add_run_id_command(
        runs_sub, common, "show", runs_cmd.handle_show, "show run details"
    )
    _add_create(runs_sub, common)

    _add_run_id_command(
        runs_sub, common, "start", runs_cmd.handle_start, "start a run"
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
    steer_parser.add_argument("message", help="the steering message")

    ask_parser = _add_run_id_command(
        runs_sub,
        common,
        "ask",
        runs_cmd.handle_ask,
        "ask a question about a run",
    )
    ask_parser.add_argument("question", help="the question to ask")


def build_parser() -> argparse.ArgumentParser:
    """Construct the full ``cosci`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="cosci",
        description="Operator CLI for driving Co-Scientist runs via its API.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    common = _common_parser()
    _add_status(sub, common)
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
    client = ApiClient(args.api_url, args.client_id)
    try:
        return cast(Handler, handler)(args, client)
    except CliError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code

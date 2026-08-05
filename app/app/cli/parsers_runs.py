"""Parser builders for the ``cosci runs`` command group.

Split from ``app.cli.parsers`` to keep that module small: this module holds
the ``runs`` subcommand registration helpers (create/lifecycle/streaming/read/
interaction), all built on ``parsers_common._add_leaf_command``.
``app.cli.parsers`` re-exports ``_add_runs``, the group's entry point. Kept
import-light (stdlib + httpx only) so ``cosci --help`` does not pull in
FastAPI or the engine.
"""

from __future__ import annotations

import argparse

from app.cli import runs_cmd
from app.cli.parsers_common import (
    RUN_FOCUS_VALUES,
    RUN_TIER_VALUES,
    Handler,
    _add_leaf_command,
)


def _add_create_planning_options(parser: argparse.ArgumentParser) -> None:
    """Add the repeatable planning-input options for ``runs create``."""
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


def _add_create_size_overrides(parser: argparse.ArgumentParser) -> None:
    """Add the numeric run-size override options for ``runs create``."""
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
    _add_create_planning_options(parser)
    _add_create_size_overrides(parser)


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


def _add_run_list_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs list`` and ``runs demo``."""
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


def _add_run_lifecycle_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs show/create/start/pause/resume/cancel``."""
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
    ):
        _add_run_id_command(runs_sub, common, name, handler, help_text)


def _add_run_watch_command(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs watch``."""
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


def _add_run_wait_command(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs wait``."""
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


def _add_run_read_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the read-only per-run listing subcommands.

    The sub-collection reads are driven by ``runs_cmd.COLLECTION_COMMANDS``,
    so adding one is a single table row there rather than an edit here too;
    ``metrics`` is registered separately because it renders a key/value block
    instead of a record list.
    """
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


def _add_run_interaction_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs report/steer/ask``."""
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


def _add_runs(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the ``runs`` command group and its subcommands."""
    runs = sub.add_parser("runs", help="create, drive, and inspect runs")
    runs_sub = runs.add_subparsers(dest="runs_command", metavar="SUBCOMMAND")

    _add_run_list_commands(runs_sub, common)
    _add_run_lifecycle_commands(runs_sub, common)
    _add_run_watch_command(runs_sub, common)
    _add_run_wait_command(runs_sub, common)
    _add_run_read_commands(runs_sub, common)
    _add_run_interaction_commands(runs_sub, common)

"""Parser builders for the ``cosci runs`` command group.

Split from ``app.cli.parsers`` to keep that module small: this module holds
the ``runs`` subcommand registration helpers (create/lifecycle/streaming/read/
interaction). ``app.cli.parsers`` re-exports every name here. Kept
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
    _json_flag,
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
    _add_create_planning_options(parser)
    _add_create_size_overrides(parser)
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


def _add_run_list_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs list`` and ``runs demo``."""
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


def _add_run_lifecycle_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs show/create/start/pause/resume/cancel``."""
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


def _add_run_streaming_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs watch`` and ``runs wait``."""
    _add_run_watch_command(runs_sub, common)
    _add_run_wait_command(runs_sub, common)


def _add_run_content_read_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs hypotheses/evidence/reviews/citations``."""
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


def _add_run_process_read_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register ``runs safety/matches/proximity/metrics/claim-evidence``."""
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


def _add_run_read_commands(
    runs_sub: argparse._SubParsersAction[argparse.ArgumentParser],
    common: argparse.ArgumentParser,
) -> None:
    """Register the read-only per-run listing subcommands."""
    _add_run_content_read_commands(runs_sub, common)
    _add_run_process_read_commands(runs_sub, common)


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
    _add_run_streaming_commands(runs_sub, common)
    _add_run_read_commands(runs_sub, common)
    _add_run_interaction_commands(runs_sub, common)

"""The ``cosci runs`` subcommands: lifecycle, reads, and reports.

Every handler is a thin wrapper over one ``/api/runs`` endpoint. Handlers take
the parsed ``argparse.Namespace`` and an :class:`ApiClient`, return a process
exit code, and pull request values off the namespace into typed locals so the
module stays strict-mypy clean. The streaming/polling handlers (``wait``,
``watch``, ``ask``) live in ``app.cli.runs_stream_cmd`` and are re-exported
here so ``runs_cmd.handle_watch`` and friends keep resolving.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from app.cli.http import (
    ApiClient,
    CliError,
    expect_object,
)
from app.cli.render import (
    emit_json,
    format_action_line,
    format_kv,
    format_record_line,
    format_run_line,
    oneline,
)
from app.cli.runs_stream_cmd import (
    WAIT_EXIT_CODES as WAIT_EXIT_CODES,
)
from app.cli.runs_stream_cmd import (
    WATCH_RECONNECT_ATTEMPTS as WATCH_RECONNECT_ATTEMPTS,
)
from app.cli.runs_stream_cmd import (
    WATCH_RECONNECT_WAIT as WATCH_RECONNECT_WAIT,
)
from app.cli.runs_stream_cmd import (
    _print_terminal as _print_terminal,
)
from app.cli.runs_stream_cmd import (
    _run_path as _run_path,
)
from app.cli.runs_stream_cmd import (
    _text_arg as _text_arg,
)
from app.cli.runs_stream_cmd import (
    _watch_events as _watch_events,
)
from app.cli.runs_stream_cmd import (
    handle_ask as handle_ask,
)
from app.cli.runs_stream_cmd import (
    handle_wait as handle_wait,
)
from app.cli.runs_stream_cmd import (
    handle_watch as handle_watch,
)

# ---------------------------------------------------------------------------
# Listing and detail
# ---------------------------------------------------------------------------


def _emit_runs_list(body: Any, as_json: bool) -> int:
    """Render a ``{"runs": [...]}`` payload as JSON or one line per run."""
    if as_json:
        emit_json(body)
        return 0
    runs = body.get("runs", []) if isinstance(body, dict) else []
    for run in runs:
        print(format_run_line(run))
    return 0


def handle_list(args: argparse.Namespace, client: ApiClient) -> int:
    """List the caller's runs, most recent first (GET /api/runs)."""
    limit: int = args.limit
    as_json: bool = args.json
    body = client.request_json("GET", f"/api/runs?limit={limit}")
    return _emit_runs_list(body, as_json)


def handle_demo(args: argparse.Namespace, client: ApiClient) -> int:
    """List the seeded demo runs visible to every client (GET /demo)."""
    as_json: bool = args.json
    body = client.request_json("GET", "/api/runs/demo")
    return _emit_runs_list(body, as_json)


def handle_show(args: argparse.Namespace, client: ApiClient) -> int:
    """Show a run's details plus per-table summary counts (GET /api/runs/id)."""
    run_id: str = args.run_id
    as_json: bool = args.json
    body = client.request_json("GET", _run_path(run_id))
    if as_json:
        emit_json(body)
        return 0
    body = expect_object(body, _run_path(run_id))
    pairs: list[tuple[str, Any]] = [
        ("id", body.get("id")),
        ("status", body.get("status")),
        ("provider", body.get("provider")),
        ("run_mode", body.get("run_mode")),
        ("created_at", body.get("created_at")),
        ("updated_at", body.get("updated_at")),
        ("completed_at", body.get("completed_at")),
        ("error", body.get("error")),
        ("research_goal", oneline(body.get("research_goal", ""))),
    ]
    summary = body.get("summary")
    if isinstance(summary, dict):
        for key in sorted(summary):
            pairs.append((f"summary.{key}", summary[key]))
    print(format_kv(pairs))
    return 0


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def _create_body(args: argparse.Namespace) -> dict[str, Any]:
    """Build the create-run request body, omitting unset optional fields."""
    goal = _text_arg(args.goal, "the research goal")
    body: dict[str, Any] = {"research_goal": goal}
    optional: list[tuple[str, Any]] = [
        ("requirements", args.requirements),
        ("attributes", args.attributes),
        ("criteria", args.criteria),
        ("focus", args.focus),
        ("tier", args.tier),
        ("initial_hypotheses_count", args.initial_hypotheses_count),
        ("max_iterations", args.max_iterations),
        ("evolution_max_count", args.evolution_max_count),
        ("k_factor", args.k_factor),
        ("enable_literature_review", args.enable_literature_review),
    ]
    for key, value in optional:
        if value is not None:
            body[key] = value
    return body


def handle_create(args: argparse.Namespace, client: ApiClient) -> int:
    """Create a draft run, optionally starting it (POST /api/runs [+/start]).

    With ``--start`` the freshly created run is started in the same
    invocation and the printed/emitted result is the start response, so the
    reported status reflects the started run.
    """
    as_json: bool = args.json
    start: bool = args.start
    body = client.request_json(
        "POST", "/api/runs", json_body=_create_body(args)
    )
    if start:
        created = expect_object(body, "/api/runs")
        run_id = str(created.get("id") or "")
        if not run_id:
            raise CliError("create response is missing the run id")
        body = client.request_json(
            "POST", _run_path(run_id, "/start"), json_body={}
        )
    return _emit_action(body, as_json)


def handle_start(args: argparse.Namespace, client: ApiClient) -> int:
    """Start a run's workflow as a background task (POST /start)."""
    return _lifecycle_action(args, client, "start")


def handle_pause(args: argparse.Namespace, client: ApiClient) -> int:
    """Cooperatively pause an active run at its checkpoint (POST /pause)."""
    return _lifecycle_action(args, client, "pause")


def handle_resume(args: argparse.Namespace, client: ApiClient) -> int:
    """Resume a paused or interrupted run from its checkpoint (POST /resume)."""
    return _lifecycle_action(args, client, "resume")


def handle_cancel(args: argparse.Namespace, client: ApiClient) -> int:
    """Request cancellation of an actively running workflow (POST /cancel)."""
    return _lifecycle_action(args, client, "cancel")


def _lifecycle_action(
    args: argparse.Namespace, client: ApiClient, action: str
) -> int:
    """POST a bodyless lifecycle action and print the ``id  status`` result."""
    run_id: str = args.run_id
    as_json: bool = args.json
    body = client.request_json(
        "POST", _run_path(run_id, f"/{action}"), json_body={}
    )
    return _emit_action(body, as_json)


def _emit_action(body: Any, as_json: bool) -> int:
    """Render a lifecycle result as JSON or an ``id  status`` line."""
    if as_json:
        emit_json(body)
    else:
        print(format_action_line(expect_object(body, "the lifecycle action")))
    return 0


# ---------------------------------------------------------------------------
# Data reads
# ---------------------------------------------------------------------------


def _emit_collection(
    args: argparse.Namespace,
    client: ApiClient,
    suffix: str,
    key: str,
    field_groups: tuple[tuple[str, ...], ...],
) -> int:
    """Fetch a run sub-collection and print it as JSON or one line per item."""
    run_id: str = args.run_id
    as_json: bool = args.json
    body = client.request_json("GET", _run_path(run_id, f"/{suffix}"))
    if as_json:
        emit_json(body)
        return 0
    items = body.get(key, []) if isinstance(body, dict) else []
    for item in items:
        if isinstance(item, dict):
            print(format_record_line(item, field_groups))
        else:
            print(oneline(item))
    return 0


def handle_hypotheses(args: argparse.Namespace, client: ApiClient) -> int:
    """List the run's hypotheses with Elo and lineage (GET /hypotheses)."""
    return _emit_collection(
        args,
        client,
        "hypotheses",
        "hypotheses",
        (("id",), ("elo_rating", "elo"), ("title", "statement")),
    )


def handle_evidence(args: argparse.Namespace, client: ApiClient) -> int:
    """List the literature evidence retrieved for the run (GET /evidence)."""
    return _emit_collection(
        args,
        client,
        "evidence",
        "evidence",
        (("id",), ("source",), ("title",)),
    )


def handle_reviews(args: argparse.Namespace, client: ApiClient) -> int:
    """List reviewer and meta-review notes for the run (GET /reviews)."""
    return _emit_collection(
        args,
        client,
        "reviews",
        "reviews",
        (("id",), ("reviewer_agent",), ("summary", "critique")),
    )


def handle_citations(args: argparse.Namespace, client: ApiClient) -> int:
    """List the run's citation rows with their state (GET /citations)."""
    return _emit_collection(
        args,
        client,
        "citations",
        "citations",
        (("id",), ("state",), ("claim",)),
    )


def handle_safety(args: argparse.Namespace, client: ApiClient) -> int:
    """List the run's intake/final safety-gate decisions (GET /safety)."""
    return _emit_collection(
        args,
        client,
        "safety",
        "safety",
        (("id",), ("stage",), ("decision",), ("reason",)),
    )


def handle_matches(args: argparse.Namespace, client: ApiClient) -> int:
    """List the run's tournament matches with Elo movement (GET /matches)."""
    return _emit_collection(
        args,
        client,
        "matches",
        "matches",
        (
            ("id",),
            ("iteration",),
            ("winner_id",),
            ("loser_id",),
            ("rationale",),
        ),
    )


def handle_proximity(args: argparse.Namespace, client: ApiClient) -> int:
    """List the run's idea-proximity edges (GET /proximity)."""
    return _emit_collection(
        args,
        client,
        "proximity",
        "proximity",
        (
            ("source_hypothesis_id",),
            ("target_hypothesis_id",),
            ("similarity",),
            ("cluster_id",),
        ),
    )


def handle_claim_evidence(args: argparse.Namespace, client: ApiClient) -> int:
    """List the run's claim-level entailment edges (GET /claim-evidence)."""
    return _emit_collection(
        args,
        client,
        "claim-evidence",
        "claim_evidence",
        (("id",), ("hypothesis_id",), ("label",), ("claim",)),
    )


def handle_metrics(args: argparse.Namespace, client: ApiClient) -> int:
    """Show the run's persisted execution metrics (GET /metrics).

    Metrics are recorded when a workflow finalizes; before that the API
    returns null and the text mode prints a one-line notice instead.
    """
    run_id: str = args.run_id
    as_json: bool = args.json
    body = client.request_json("GET", _run_path(run_id, "/metrics"))
    if as_json:
        emit_json(body)
        return 0
    metrics = body.get("metrics") if isinstance(body, dict) else None
    if not isinstance(metrics, dict):
        print("no metrics recorded (run has not finalized)")
        return 0
    pairs: list[tuple[str, Any]] = []
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        pairs.append((key, value))
    print(format_kv(pairs))
    return 0


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def handle_report(args: argparse.Namespace, client: ApiClient) -> int:
    """Fetch a run's report as a summary, full JSON, or Markdown (GET /report).

    With ``--md`` the rendered Markdown is printed verbatim; with ``--json`` the
    full structured payload; the default is a line-oriented summary with the
    Elo leaderboard.
    """
    run_id: str = args.run_id
    as_md: bool = args.md
    as_json: bool = args.json
    if as_md:
        text = client.request_text("GET", _run_path(run_id, "/report.md"))
        print(text if text.endswith("\n") else text + "\n", end="")
        return 0
    body = client.request_json("GET", _run_path(run_id, "/report"))
    if as_json:
        emit_json(body)
        return 0
    _print_report_summary(body)
    return 0


def _print_report_summary(body: Any) -> None:
    """Print the line-oriented report summary with the Elo leaderboard."""
    payload = body.get("payload", {}) if isinstance(body, dict) else {}
    pairs: list[tuple[str, Any]] = [
        ("research_goal", oneline(payload.get("research_goal", ""))),
        ("provider", payload.get("provider")),
        ("hypotheses", payload.get("hypothesis_count")),
        ("evidence", payload.get("evidence_count")),
        ("matches", payload.get("match_count")),
    ]
    print(format_kv(pairs))
    leaderboard = payload.get("leaderboard") or []
    if leaderboard:
        print("\nleaderboard:")
        for entry in leaderboard:
            if isinstance(entry, dict):
                print(
                    "  "
                    + format_record_line(
                        entry, (("rank",), ("elo",), ("title",))
                    )
                )


# ---------------------------------------------------------------------------
# Steering
# ---------------------------------------------------------------------------


def handle_steer(args: argparse.Namespace, client: ApiClient) -> int:
    """Queue a user steering message for the next iteration (POST /messages)."""
    run_id: str = args.run_id
    message = _text_arg(args.message, "the steering message")
    as_json: bool = args.json
    body = client.request_json(
        "POST",
        _run_path(run_id, "/messages"),
        json_body={"content": message},
    )
    if as_json:
        emit_json(body)
        return 0
    body = expect_object(body, _run_path(run_id, "/messages"))
    pairs: list[tuple[str, Any]] = [
        ("id", body.get("id")),
        ("status", body.get("status")),
        ("kind", body.get("kind")),
        ("sender", body.get("sender")),
    ]
    print(format_kv(pairs))
    return 0

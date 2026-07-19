"""The ``cosci runs`` subcommands: lifecycle, reads, streaming, and reports.

Every handler is a thin wrapper over one ``/api/runs`` endpoint. Handlers take
the parsed ``argparse.Namespace`` and an :class:`ApiClient`, return a process
exit code, and pull request values off the namespace into typed locals so the
module stays strict-mypy clean.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.cli.http import ApiClient
from app.cli.render import (
    emit_json,
    format_action_line,
    format_event_line,
    format_kv,
    format_record_line,
    format_run_line,
    oneline,
    sse_data,
)

# ---------------------------------------------------------------------------
# Listing and detail
# ---------------------------------------------------------------------------


def handle_list(args: argparse.Namespace, client: ApiClient) -> int:
    """List the caller's runs, most recent first (GET /api/runs)."""
    limit: int = args.limit
    as_json: bool = args.json
    body = client.request_json("GET", f"/api/runs?limit={limit}")
    if as_json:
        emit_json(body)
        return 0
    runs = body.get("runs", []) if isinstance(body, dict) else []
    for run in runs:
        print(format_run_line(run))
    return 0


def handle_show(args: argparse.Namespace, client: ApiClient) -> int:
    """Show a run's details plus per-table summary counts (GET /api/runs/id)."""
    run_id: str = args.run_id
    as_json: bool = args.json
    body = client.request_json("GET", f"/api/runs/{run_id}")
    if as_json:
        emit_json(body)
        return 0
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
    body: dict[str, Any] = {"research_goal": args.goal}
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
    """Create a draft run from a goal and optional config (POST /api/runs)."""
    as_json: bool = args.json
    body = client.request_json(
        "POST", "/api/runs", json_body=_create_body(args)
    )
    if as_json:
        emit_json(body)
        return 0
    print(format_action_line(body))
    return 0


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
        "POST", f"/api/runs/{run_id}/{action}", json_body={}
    )
    return _emit_action(body, as_json)


def _emit_action(body: Any, as_json: bool) -> int:
    """Render a lifecycle result as JSON or an ``id  status`` line."""
    if as_json:
        emit_json(body)
    else:
        print(format_action_line(body))
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
    body = client.request_json("GET", f"/api/runs/{run_id}/{suffix}")
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
        text = client.request_text("GET", f"/api/runs/{run_id}/report.md")
        print(text if text.endswith("\n") else text + "\n", end="")
        return 0
    body = client.request_json("GET", f"/api/runs/{run_id}/report")
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
    message: str = args.message
    as_json: bool = args.json
    body = client.request_json(
        "POST",
        f"/api/runs/{run_id}/messages",
        json_body={"content": message},
    )
    if as_json:
        emit_json(body)
        return 0
    pairs: list[tuple[str, Any]] = [
        ("id", body.get("id")),
        ("status", body.get("status")),
        ("kind", body.get("kind")),
        ("sender", body.get("sender")),
    ]
    print(format_kv(pairs))
    return 0


# ---------------------------------------------------------------------------
# Streaming: watch and ask (Server-Sent Events)
# ---------------------------------------------------------------------------


def handle_watch(args: argparse.Namespace, client: ApiClient) -> int:
    """Tail a run's event stream, one line per event, exit on terminal.

    Streams ``GET /api/runs/{id}/events?after=`` and prints each event as it
    arrives (compact JSON with ``--json``, else ``seq  type  payload``). The
    stream ends on the synthetic ``_terminal`` frame the API sends once the run
    reaches a terminal or paused status.
    """
    run_id: str = args.run_id
    after: int = args.after
    as_json: bool = args.json
    path = f"/api/runs/{run_id}/events?after={after}"
    try:
        with client.stream_lines("GET", path) as lines:
            for line in lines:
                event = sse_data(line)
                if event is None:
                    continue
                if event.get("type") == "_terminal":
                    _print_terminal(event, as_json)
                    return 0
                if as_json:
                    print(json.dumps(event, ensure_ascii=False))
                else:
                    print(format_event_line(event))
    except KeyboardInterrupt:
        return 130
    return 0


def _print_terminal(event: dict[str, Any], as_json: bool) -> None:
    """Print the terminal frame that closes a watch stream."""
    if as_json:
        print(json.dumps(event, ensure_ascii=False))
        return
    payload = event.get("payload") or {}
    status = payload.get("status", "") if isinstance(payload, dict) else ""
    print(f"{event.get('seq', '')}\t_terminal\t{status}".rstrip())


def handle_ask(args: argparse.Namespace, client: ApiClient) -> int:
    """Ask a question about a run and stream the answer (POST /messages/ask).

    In text mode the answer chunks are written to stdout as they arrive; a
    server-side error frame (for example, no model API key configured) is
    printed to stderr and yields a non-zero exit. With ``--json`` every SSE
    frame is echoed as one JSON object per line.
    """
    run_id: str = args.run_id
    question: str = args.question
    as_json: bool = args.json
    path = f"/api/runs/{run_id}/messages/ask"
    wrote_chunk = False
    saw_error = False
    try:
        with client.stream_lines(
            "POST", path, json_body={"question": question}
        ) as lines:
            for line in lines:
                event = sse_data(line)
                if event is None:
                    continue
                if as_json:
                    print(json.dumps(event, ensure_ascii=False))
                    saw_error = saw_error or event.get("type") == "error"
                    continue
                etype = event.get("type")
                if etype == "chunk":
                    sys.stdout.write(str(event.get("content", "")))
                    sys.stdout.flush()
                    wrote_chunk = True
                elif etype in ("done", "error"):
                    # Terminate the streamed answer line only if we wrote one.
                    if wrote_chunk:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    if etype == "error":
                        print(str(event.get("message", "")), file=sys.stderr)
                        saw_error = True
    except KeyboardInterrupt:
        return 130
    return 1 if saw_error else 0

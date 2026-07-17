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
import time
import urllib.parse
from collections.abc import Iterator
from typing import Any

from app.cli.http import (
    ApiClient,
    ApiUnreachableError,
    CliError,
    expect_object,
)
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


def _run_path(run_id: str, suffix: str = "") -> str:
    """Build an ``/api/runs/{id}...`` path with the run id percent-quoted."""
    return f"/api/runs/{urllib.parse.quote(run_id, safe='')}{suffix}"


def _text_arg(value: str, what: str) -> str:
    """Return a text argument, reading it from stdin when given as ``-``.

    Long goals, steering messages, and questions are awkward to pass through
    shell quoting; ``-`` lets callers pipe or heredoc them instead.

    Args:
        value: The raw argument value, possibly the ``-`` sentinel.
        what: Human-readable description used in the empty-stdin error.

    Raises:
        CliError: When ``-`` was given but stdin held only whitespace.
    """
    if value != "-":
        return value
    text = sys.stdin.read().strip()
    if not text:
        raise CliError(f"{what} given as '-' but stdin is empty")
    return text


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
    run_id: str = args.run_id
    provider: str | None = args.provider
    as_json: bool = args.json
    request_body: dict[str, Any] = {}
    if provider is not None:
        request_body["force_provider"] = provider
    body = client.request_json(
        "POST", _run_path(run_id, "/start"), json_body=request_body
    )
    return _emit_action(body, as_json)


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
# Waiting
# ---------------------------------------------------------------------------

# Statuses that stop a ``runs wait`` poll, mapped to the process exit code.
# Distinct codes let scripts branch on the outcome without parsing output;
# ``paused`` is included because a paused run makes no progress until an
# explicit resume, so waiting on it would hang forever.
WAIT_EXIT_CODES = {
    "completed": 0,
    "failed": 3,
    "blocked": 4,
    "cancelled": 5,
    "paused": 6,
}


def handle_wait(args: argparse.Namespace, client: ApiClient) -> int:
    """Poll a run until it settles and exit with a status-specific code.

    Prints one ``id  status`` line per status change (nothing per poll), or
    with ``--json`` only the final run object. Exit codes: 0 completed,
    3 failed, 4 blocked, 5 cancelled, 6 paused, 124 when ``--max-wait``
    elapses first.
    """
    run_id: str = args.run_id
    interval: float = args.interval
    max_wait: float | None = args.max_wait
    as_json: bool = args.json
    deadline = None if max_wait is None else time.monotonic() + max_wait
    last_status: str | None = None
    while True:
        body = expect_object(
            client.request_json("GET", _run_path(run_id)), _run_path(run_id)
        )
        status = str(body.get("status") or "")
        if status != last_status:
            last_status = status
            if not as_json:
                print(f"{run_id}\t{status}", flush=True)
        exit_code = WAIT_EXIT_CODES.get(status)
        if exit_code is not None:
            if as_json:
                emit_json(body)
            return exit_code
        if deadline is not None and time.monotonic() >= deadline:
            raise CliError(
                f"run {run_id} still '{status or 'unknown'}' after {max_wait}s",
                exit_code=124,
            )
        time.sleep(interval)


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


# ---------------------------------------------------------------------------
# Streaming: watch and ask (Server-Sent Events)
# ---------------------------------------------------------------------------


# How many consecutive unproductive connection attempts ``watch`` tolerates
# before giving up, and how long it waits between reconnects. Progress (any
# received event) resets the budget, so a long healthy stream can survive any
# number of occasional drops.
WATCH_RECONNECT_ATTEMPTS = 5
WATCH_RECONNECT_WAIT = 1.0


def _watch_events(
    client: ApiClient, run_id: str, after: int
) -> Iterator[dict[str, Any]]:
    """Yield parsed event frames from one connection to ``/events``."""
    path = _run_path(run_id, f"/events?after={after}")
    with client.stream_lines("GET", path) as lines:
        for line in lines:
            event = sse_data(line)
            if event is not None:
                yield event


def handle_watch(args: argparse.Namespace, client: ApiClient) -> int:
    """Tail a run's event stream, one line per event, exit on terminal.

    Streams ``GET /api/runs/{id}/events?after=`` and prints each event as it
    arrives (compact JSON with ``--json``, else ``seq  type  payload``). The
    stream ends on the synthetic ``_terminal`` frame the API sends once the
    run reaches a terminal or paused status. A dropped connection or a close
    without that frame is reconnected from the last seen sequence number; an
    HTTP error status (e.g. an unknown run) is not retried.
    """
    run_id: str = args.run_id
    after: int = args.after
    as_json: bool = args.json
    failures = 0
    last_error: ApiUnreachableError | None = None
    try:
        while True:
            progressed = False
            try:
                for event in _watch_events(client, run_id, after):
                    seq = event.get("seq")
                    if isinstance(seq, int) and seq > after:
                        after = seq
                    progressed = True
                    if event.get("type") == "_terminal":
                        _print_terminal(event, as_json)
                        return 0
                    if as_json:
                        print(json.dumps(event, ensure_ascii=False))
                    else:
                        print(format_event_line(event))
                last_error = None
            except ApiUnreachableError as exc:
                last_error = exc
            if progressed:
                failures = 0
            failures += 1
            if failures > WATCH_RECONNECT_ATTEMPTS:
                if last_error is not None:
                    raise last_error
                raise CliError(
                    f"event stream for run {run_id} kept closing without "
                    "reaching a terminal status"
                )
            time.sleep(WATCH_RECONNECT_WAIT)
    except KeyboardInterrupt:
        return 130


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
    question = _text_arg(args.question, "the question")
    as_json: bool = args.json
    path = _run_path(run_id, "/messages/ask")
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

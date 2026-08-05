"""The streaming and polling ``cosci runs`` subcommands.

Split from ``app.cli.runs_cmd`` to keep that module small: this module holds
the handlers that hold a connection open or poll until a run settles —
``wait`` (status polling), ``watch`` (SSE event tail with reconnects), and
``ask`` (streamed Q&A) — plus the path/stdin helpers they share with the
plain request/response handlers. ``app.cli.runs_cmd`` re-exports the three
handlers and ``WATCH_RECONNECT_ATTEMPTS``, so ``runs_cmd.handle_watch`` and
friends keep resolving.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.cli.http import (
    ApiClient,
    ApiUnreachableError,
    CliError,
    expect_object,
)
from app.cli.render import emit_json, format_event_line, sse_data


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


def _wait_deadline(max_wait: float | None) -> float | None:
    """Return the monotonic deadline ``max_wait`` seconds out, if any."""
    if max_wait is None:
        return None
    return time.monotonic() + max_wait


def _wait_deadline_expired(deadline: float | None) -> bool:
    """Return whether a ``_wait_deadline`` result has now passed."""
    return deadline is not None and time.monotonic() >= deadline


def _note_wait_status(
    run_id: str, status: str, last_status: str | None, as_json: bool
) -> str:
    """Print a status-change line in text mode; return the new status.

    Args:
        run_id: The run being polled, used in the printed line.
        status: The status just observed.
        last_status: The status last observed, or None initially.
        as_json: Whether ``--json`` was requested (suppresses the line).

    Returns:
        ``status``, to become the caller's new ``last_status``.
    """
    if status != last_status and not as_json:
        print(f"{run_id}\t{status}", flush=True)
    return status


def _wait_exit_code(
    status: str, body: dict[str, Any], as_json: bool
) -> int | None:
    """Return the run's exit code once its status is terminal, else None."""
    exit_code = WAIT_EXIT_CODES.get(status)
    if exit_code is None:
        return None
    if as_json:
        emit_json(body)
    return exit_code


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
    deadline = _wait_deadline(max_wait)
    last_status: str | None = None
    path = _run_path(run_id)
    while True:
        body = expect_object(client.request_json("GET", path), path)
        status = str(body.get("status") or "")
        last_status = _note_wait_status(run_id, status, last_status, as_json)
        exit_code = _wait_exit_code(status, body, as_json)
        if exit_code is not None:
            return exit_code
        if _wait_deadline_expired(deadline):
            raise CliError(
                f"run {run_id} still '{status or 'unknown'}' after {max_wait}s",
                exit_code=124,
            )
        time.sleep(interval)


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


@dataclass
class _WatchProgress:
    """Mutable per-connection watch state shared across reconnect attempts.

    Kept as a mutable object (rather than local variables) so that when a
    connection is interrupted mid-stream, the events already consumed are
    still reflected in ``after``/``progressed`` after the exception is
    caught by the caller.
    """

    after: int
    progressed: bool = False


def _consume_watch_connection(
    client: ApiClient,
    run_id: str,
    as_json: bool,
    progress: _WatchProgress,
) -> bool:
    """Stream one connection's events, updating ``progress`` as they arrive.

    Returns:
        True once the synthetic ``_terminal`` frame has been printed and the
        caller should stop watching; False once the connection closes
        without one (a reconnect is warranted).
    """
    for event in _watch_events(client, run_id, progress.after):
        seq = event.get("seq")
        if isinstance(seq, int) and seq > progress.after:
            progress.after = seq
        progress.progressed = True
        if event.get("type") == "_terminal":
            _print_terminal(event, as_json)
            return True
        if as_json:
            print(json.dumps(event, ensure_ascii=False))
        else:
            print(format_event_line(event))
    return False


def _enforce_watch_reconnect_budget(
    failures: int, run_id: str, last_error: ApiUnreachableError | None
) -> None:
    """Raise once the watch reconnect budget is exhausted.

    Args:
        failures: Consecutive unproductive connection attempts so far.
        run_id: The run being watched, used in the fallback message.
        last_error: The most recent connection failure, if any, raised
            in preference to a generic message.

    Raises:
        ApiUnreachableError: If the last attempt failed to connect.
        CliError: If attempts closed cleanly but never reached a
            terminal status.
    """
    if failures <= WATCH_RECONNECT_ATTEMPTS:
        return
    if last_error is not None:
        raise last_error
    raise CliError(
        f"event stream for run {run_id} kept closing without "
        "reaching a terminal status"
    )


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
    as_json: bool = args.json
    progress = _WatchProgress(after=args.after)
    failures = 0
    try:
        while True:
            progress.progressed = False
            last_error: ApiUnreachableError | None = None
            try:
                if _consume_watch_connection(client, run_id, as_json, progress):
                    return 0
            except ApiUnreachableError as exc:
                last_error = exc
            failures = 1 if progress.progressed else failures + 1
            _enforce_watch_reconnect_budget(failures, run_id, last_error)
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


@dataclass
class _AskState:
    """Mutable per-answer state: whether a chunk was written, and errors."""

    wrote_chunk: bool = False
    saw_error: bool = False


def _handle_ask_event_json(event: dict[str, Any], state: _AskState) -> None:
    """Echo one ask-stream SSE frame as JSON and track error state."""
    print(json.dumps(event, ensure_ascii=False))
    if event.get("type") == "error":
        state.saw_error = True


def _handle_ask_event_text(event: dict[str, Any], state: _AskState) -> None:
    """Apply one ask-stream SSE frame to stdout/stderr in text mode."""
    etype = event.get("type")
    if etype == "chunk":
        sys.stdout.write(str(event.get("content", "")))
        sys.stdout.flush()
        state.wrote_chunk = True
        return
    if etype not in ("done", "error"):
        return
    # Terminate the streamed answer line only if we wrote one.
    if state.wrote_chunk:
        sys.stdout.write("\n")
        sys.stdout.flush()
    if etype == "error":
        print(str(event.get("message", "")), file=sys.stderr)
        state.saw_error = True


def _handle_ask_event(
    event: dict[str, Any], as_json: bool, state: _AskState
) -> None:
    """Apply one SSE frame from the ask stream to stdout/stderr and state."""
    if as_json:
        _handle_ask_event_json(event, state)
    else:
        _handle_ask_event_text(event, state)


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
    state = _AskState()
    try:
        with client.stream_lines(
            "POST", path, json_body={"question": question}
        ) as lines:
            for line in lines:
                event = sse_data(line)
                if event is None:
                    continue
                _handle_ask_event(event, as_json, state)
    except KeyboardInterrupt:
        return 130
    return 1 if state.saw_error else 0

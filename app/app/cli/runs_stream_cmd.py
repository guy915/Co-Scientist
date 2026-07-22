"""The streaming and polling ``cosci runs`` subcommands.

Split from ``app.cli.runs_cmd`` to keep that module small: this module holds
the handlers that hold a connection open or poll until a run settles —
``wait`` (status polling), ``watch`` (SSE event tail with reconnects), and
``ask`` (streamed Q&A) — plus the path/stdin helpers they share with the
plain request/response handlers. ``app.cli.runs_cmd`` re-exports every name
here, so ``runs_cmd.handle_watch`` and friends keep resolving.
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
    last_error: ApiUnreachableError | None = None
    try:
        while True:
            progress.progressed = False
            try:
                if _consume_watch_connection(client, run_id, as_json, progress):
                    return 0
                last_error = None
            except ApiUnreachableError as exc:
                last_error = exc
            if progress.progressed:
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


@dataclass
class _AskState:
    """Mutable per-answer state: whether a chunk was written, and errors."""

    wrote_chunk: bool = False
    saw_error: bool = False


def _handle_ask_event(
    event: dict[str, Any], as_json: bool, state: _AskState
) -> None:
    """Apply one SSE frame from the ask stream to stdout/stderr and state."""
    if as_json:
        print(json.dumps(event, ensure_ascii=False))
        state.saw_error = state.saw_error or event.get("type") == "error"
        return
    etype = event.get("type")
    if etype == "chunk":
        sys.stdout.write(str(event.get("content", "")))
        sys.stdout.flush()
        state.wrote_chunk = True
    elif etype in ("done", "error"):
        # Terminate the streamed answer line only if we wrote one.
        if state.wrote_chunk:
            sys.stdout.write("\n")
            sys.stdout.flush()
        if etype == "error":
            print(str(event.get("message", "")), file=sys.stderr)
            state.saw_error = True


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

"""The top-level ``cosci logs`` command: query and follow persisted logs.

Reads ``GET /api/logs`` (the ``app_logs`` table captured from the Python
root logger). One line per record in text mode; ``--follow`` keeps
polling from the server's ``last_id`` high-water mark, which also covers
records that arrive while a filter excludes them.
"""

from __future__ import annotations

import argparse
import datetime
import json
import time
import urllib.parse
from typing import Any

from app.cli.http import ApiClient
from app.cli.render import emit_json, oneline


def _logs_path(args: argparse.Namespace, after_id: int) -> str:
    """Build the /api/logs query URL for the parsed filters."""
    params: dict[str, Any] = {"after_id": after_id, "limit": args.limit}
    if args.run:
        params["run_id"] = args.run
    if args.level:
        params["min_level"] = args.level
    if args.grep:
        params["q"] = args.grep
    if args.all:
        params["verbose"] = 1
    return "/api/logs?" + urllib.parse.urlencode(params)


def format_log_line(row: dict[str, Any]) -> str:
    """Render one log row as ``id  time  LEVEL  logger  message``.

    The run id is appended to the message as ``[run_id=...]`` (matching
    the stdout text formatter), and any exception text is collapsed onto
    the line; use ``--json`` for the full multi-line traceback.
    """
    created = row.get("created_at")
    when = (
        datetime.datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(created, (int, float))
        else ""
    )
    message = oneline(row.get("message", ""), limit=300)
    run_id = row.get("run_id")
    if run_id:
        message += f" [run_id={run_id}]"
    exc_text = row.get("exc_text")
    if exc_text:
        message += f" | {oneline(exc_text, limit=200)}"
    return "\t".join(
        (
            str(row.get("id", "")),
            when,
            str(row.get("level", "")),
            str(row.get("logger", "")),
            message,
        )
    )


def _extract(body: Any, after_id: int) -> tuple[list[dict[str, Any]], int]:
    """Pull the row list and next cursor out of a /api/logs payload.

    When the server's ``last_id`` drops below the follower's cursor the
    log was cleared and its ids restarted, so the cursor resets instead
    of stalling forever above the fresh ids.
    """
    if not isinstance(body, dict):
        return [], after_id
    rows = [row for row in body.get("logs", []) if isinstance(row, dict)]
    last = body.get("last_id")
    if isinstance(last, int) and last < after_id:
        after_id = 0
    cursor = last if isinstance(last, int) else after_id
    for row in rows:
        row_id = row.get("id")
        if isinstance(row_id, int):
            cursor = max(cursor, row_id)
    return rows, max(after_id, cursor)


def _handle_clear(client: ApiClient, as_json: bool) -> int:
    """Delete every persisted log record and report the outcome."""
    body = client.request_json("DELETE", "/api/logs")
    if as_json:
        emit_json(body)
    else:
        deleted = body.get("deleted", "") if isinstance(body, dict) else ""
        print(f"deleted\t{deleted}")
    return 0


def _print_log_rows(rows: list[dict[str, Any]], as_json: bool) -> None:
    """Print one line per row, as JSON or the tab-delimited text format."""
    for row in rows:
        if as_json:
            print(json.dumps(row, ensure_ascii=False), flush=True)
        else:
            print(format_log_line(row), flush=True)


def _poll_logs(args: argparse.Namespace, client: ApiClient) -> int:
    """Poll ``/api/logs`` once, or repeatedly while ``--follow`` is set."""
    follow: bool = args.follow
    interval: float = args.interval
    as_json: bool = args.json
    after_id: int = args.after_id
    while True:
        body = client.request_json("GET", _logs_path(args, after_id))
        if as_json and not follow:
            emit_json(body)
            return 0
        rows, after_id = _extract(body, after_id)
        _print_log_rows(rows, as_json)
        if not follow:
            return 0
        time.sleep(interval)


def handle_logs(args: argparse.Namespace, client: ApiClient) -> int:
    """Print persisted log records; with ``--follow`` keep tailing.

    Text mode prints one line per record. ``--json`` emits the raw
    payload for a single query, or one JSON object per new record when
    following. ``--clear`` deletes every persisted record instead of
    reading. Ctrl-C ends a follow with exit code 130.
    """
    if args.clear:
        return _handle_clear(client, args.json)
    try:
        return _poll_logs(args, client)
    except KeyboardInterrupt:
        return 130

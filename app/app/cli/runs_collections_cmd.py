"""Read and render per-run collections and execution metrics."""

from __future__ import annotations

import argparse
import json
from typing import Any

from app.cli.http import ApiClient
from app.cli.render import emit_json, format_kv, format_record_line, oneline
from app.cli.runs_stream_cmd import _run_path

# Command name -> help text and ordered output columns.
COLLECTION_COMMANDS: dict[str, tuple[str, tuple[tuple[str, ...], ...]]] = {
    "hypotheses": (
        "list hypotheses",
        (("id",), ("elo_rating", "elo"), ("title", "statement")),
    ),
    "evidence": ("list evidence", (("id",), ("source",), ("title",))),
    "reviews": (
        "list reviews",
        (("id",), ("reviewer_agent",), ("summary", "critique")),
    ),
    "citations": ("list citations", (("id",), ("state",), ("claim",))),
    "safety": (
        "list safety rows",
        (("id",), ("stage",), ("decision",), ("reason",)),
    ),
    "matches": (
        "list tournament matches",
        (
            ("id",),
            ("iteration",),
            ("winner_id",),
            ("loser_id",),
            ("rationale",),
        ),
    ),
    "proximity": (
        "list idea-proximity edges",
        (
            ("source_hypothesis_id",),
            ("target_hypothesis_id",),
            ("similarity",),
            ("cluster_id",),
        ),
    ),
    "claim-evidence": (
        "list claim-level entailment edges",
        (("id",), ("hypothesis_id",), ("label",), ("claim",)),
    ),
    "tasks": (
        "list durable tasks with retry-attempt history",
        (("id",), ("task_type",), ("status",), ("attempt",), ("error",)),
    ),
}


def handle_collection(args: argparse.Namespace, client: ApiClient) -> int:
    """Fetch the selected collection as JSON or one line per item."""
    name: str = args.runs_command
    body = client.request_json("GET", _run_path(args.run_id, f"/{name}"))
    if args.json:
        emit_json(body)
        return 0
    items = (
        body.get(name.replace("-", "_"), []) if isinstance(body, dict) else []
    )
    columns = COLLECTION_COMMANDS[name][1]
    for item in items:
        print(
            format_record_line(item, columns)
            if isinstance(item, dict)
            else oneline(item)
        )
    return 0


def handle_metrics(args: argparse.Namespace, client: ApiClient) -> int:
    """Show the run's persisted execution metrics (GET /metrics).

    Metrics update live as the run commits each node (finding L14), so
    this reflects real-time progress on a still-running run, not only the
    final total; before the run's first node commits (e.g. still
    bootstrapping) the API returns null and the text mode prints a
    one-line notice instead.
    """
    run_id: str = args.run_id
    as_json: bool = args.json
    body = client.request_json("GET", _run_path(run_id, "/metrics"))
    if as_json:
        emit_json(body)
        return 0
    metrics = body.get("metrics") if isinstance(body, dict) else None
    if not isinstance(metrics, dict):
        print("no metrics recorded yet")
        return 0
    pairs: list[tuple[str, Any]] = []
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        pairs.append((key, value))
    print(format_kv(pairs))
    return 0

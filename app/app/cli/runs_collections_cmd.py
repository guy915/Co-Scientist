"""The ``cosci runs`` sub-collection reads: hypotheses, evidence, and friends.

Split out of ``app.cli.runs_cmd``, which re-exports the names callers use so
``runs_cmd.COLLECTION_COMMANDS`` and the handlers the CLI test suite calls
keep resolving for ``app.cli.parsers`` and that suite.

The per-run sub-collection reads (``hypotheses``, ``evidence``, ...) differ
only in path, payload key, and columns, so they are one table --
:data:`COLLECTION_COMMANDS` -- that drives both the handlers here and the
subcommand registration in ``app.cli.parsers``. ``handle_metrics`` is
grouped alongside them because it shares the same read-and-render shape,
even though it is not part of the table (its payload is a single object,
not a list).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from typing import Any

from app.cli.http import ApiClient
from app.cli.render import emit_json, format_kv, format_record_line, oneline
from app.cli.runs_stream_cmd import _run_path
from app.cli.types import Handler


@dataclasses.dataclass(frozen=True)
class CollectionCommand:
    """One ``cosci runs <name>`` read over a run sub-collection.

    The subcommand name doubles as the API path suffix, and its payload key
    is that name with dashes swapped for underscores, so each read command is
    fully described by this row. :data:`COLLECTION_COMMANDS` drives both the
    handlers below and the parser registration in ``app.cli.parsers``.

    Attributes:
        name: Subcommand name and ``/api/runs/{id}/<name>`` path suffix.
        columns: Ordered candidate-key groups, one per output column, as
            taken by :func:`app.cli.render.format_record_line`.
        help: One-line subcommand help, shown by ``cosci runs --help``.
    """

    name: str
    columns: tuple[tuple[str, ...], ...]
    help: str

    @property
    def key(self) -> str:
        """The response-payload key holding this collection's item list."""
        return self.name.replace("-", "_")


COLLECTION_COMMANDS = (
    CollectionCommand(
        "hypotheses",
        (("id",), ("elo_rating", "elo"), ("title", "statement")),
        "list hypotheses",
    ),
    CollectionCommand(
        "evidence", (("id",), ("source",), ("title",)), "list evidence"
    ),
    CollectionCommand(
        "reviews",
        (("id",), ("reviewer_agent",), ("summary", "critique")),
        "list reviews",
    ),
    CollectionCommand(
        "citations", (("id",), ("state",), ("claim",)), "list citations"
    ),
    CollectionCommand(
        "safety",
        (("id",), ("stage",), ("decision",), ("reason",)),
        "list safety rows",
    ),
    CollectionCommand(
        "matches",
        (
            ("id",),
            ("iteration",),
            ("winner_id",),
            ("loser_id",),
            ("rationale",),
        ),
        "list tournament matches",
    ),
    CollectionCommand(
        "proximity",
        (
            ("source_hypothesis_id",),
            ("target_hypothesis_id",),
            ("similarity",),
            ("cluster_id",),
        ),
        "list idea-proximity edges",
    ),
    CollectionCommand(
        "claim-evidence",
        (("id",), ("hypothesis_id",), ("label",), ("claim",)),
        "list claim-level entailment edges",
    ),
    CollectionCommand(
        "tasks",
        (("id",), ("task_type",), ("status",), ("attempt",), ("error",)),
        "list durable tasks with retry-attempt history",
    ),
)


def _emit_collection(
    args: argparse.Namespace, client: ApiClient, spec: CollectionCommand
) -> int:
    """Fetch a run sub-collection and print it as JSON or one line per item."""
    run_id: str = args.run_id
    as_json: bool = args.json
    body = client.request_json("GET", _run_path(run_id, f"/{spec.name}"))
    if as_json:
        emit_json(body)
        return 0
    items = body.get(spec.key, []) if isinstance(body, dict) else []
    for item in items:
        if isinstance(item, dict):
            print(format_record_line(item, spec.columns))
        else:
            print(oneline(item))
    return 0


def _collection_handler(spec: CollectionCommand) -> Handler:
    """Build the handler that serves one collection read command."""

    def handler(args: argparse.Namespace, client: ApiClient) -> int:
        return _emit_collection(args, client, spec)

    handler.__name__ = f"handle_{spec.key}"
    handler.__qualname__ = handler.__name__
    handler.__doc__ = f"{spec.help.capitalize()} (GET /{spec.name})."
    return handler


# Handlers keyed by subcommand name. The ``handle_*`` aliases below are the
# names the parser and the tests refer to; both resolve to the same object.
COLLECTION_HANDLERS: dict[str, Handler] = {
    spec.name: _collection_handler(spec) for spec in COLLECTION_COMMANDS
}

handle_hypotheses = COLLECTION_HANDLERS["hypotheses"]
handle_evidence = COLLECTION_HANDLERS["evidence"]
handle_reviews = COLLECTION_HANDLERS["reviews"]
handle_citations = COLLECTION_HANDLERS["citations"]
handle_safety = COLLECTION_HANDLERS["safety"]
handle_matches = COLLECTION_HANDLERS["matches"]
handle_proximity = COLLECTION_HANDLERS["proximity"]
handle_claim_evidence = COLLECTION_HANDLERS["claim-evidence"]
handle_tasks = COLLECTION_HANDLERS["tasks"]


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

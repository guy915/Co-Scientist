"""Versioned workflow checkpoint: serialize and restore ``WorkflowState``.

PLAN.md Milestone 4 requires a *versioned checkpoint with named contents* so a
run can resume from its last safe boundary rather than restarting or failing.
The M2 orchestrator is the resume boundary: because every completed node's
output is already folded into the pool and the task ledger, restoring the
curated state and re-entering the graph at the orchestrator continues the run
with no node re-run.

This module is a pure, tested serialization boundary (no I/O): the app store
owns *where* checkpoints are persisted; this owns *what* a checkpoint contains
and how it round-trips. Non-serializable runtime handles (the progress callback
and the tool registry) are deliberately excluded and re-injected on restore.

Schema safety: a checkpoint carries ``CHECKPOINT_VERSION``. Restoring a
checkpoint from an incompatible version fails closed with
:class:`CheckpointSchemaError` rather than silently loading a mismatched shape.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import (
    BaseMessage,
    messages_from_dict,
    messages_to_dict,
)

from co_scientist.models import (
    Article,
    ExecutionMetrics,
    Hypothesis,
)
from co_scientist.state import WorkflowState

# Bump when the checkpoint envelope shape changes incompatibly. Restoring a
# checkpoint whose version differs fails closed (see restore_workflow_state).
CHECKPOINT_VERSION = 1

# Collections serialized via their dataclasses' to_dict/from_dict (or, for
# ``messages``, LangChain's message (de)serializers) rather than carried
# verbatim -- their runtime objects are not JSON-serializable, so a persisted
# checkpoint (the app store json.dumps() this envelope) would fail without it.
_SPECIAL_COLLECTION_KEYS = frozenset(
    {"hypotheses", "metrics", "articles", "messages"}
)


def _serialize_messages(messages: Any) -> list[dict[str, Any]]:
    """Convert the LangGraph message channel to JSON-safe dicts.

    ``add_messages`` coerces the ``messages`` channel to LangChain
    ``BaseMessage`` objects at runtime, which are not JSON-serializable. A run
    that never appended a message leaves plain data, so only ``BaseMessage``
    items are converted; anything already plain is passed through.
    """
    items = list(messages or [])
    if items and all(isinstance(m, BaseMessage) for m in items):
        return messages_to_dict(items)
    return items


def _deserialize_messages(raw: Any) -> list[Any]:
    """Rebuild LangChain messages from the serialized dicts, if any.

    ``add_messages`` accepts both message objects and message-shaped dicts, so
    a value that is not the ``messages_to_dict`` shape is returned unchanged.
    """
    items = list(raw or [])
    if items and all(
        isinstance(m, dict) and "type" in m and "data" in m for m in items
    ):
        return list(messages_from_dict(items))
    return items


# Runtime handles never serialized; re-injected on restore from the live run.
_EXCLUDED_RUNTIME_KEYS = frozenset({"progress_callback", "tool_registry"})

# Transient control flags deliberately not checkpointed: ``resume`` is set by
# restore_workflow_state itself, and ``pending_steering`` is re-delivered from
# the app's durable message queue on resume. CAUTION: do not "clean up" this
# set -- removing an entry silently starts persisting that field.
_TRANSIENT_CONTROL_KEYS = frozenset({"resume", "pending_steering"})

# ``start_time`` is a wall-clock timestamp; persisting it verbatim would make
# wall-clock budgets count the paused/idle gap between checkpoint and resume.
# It is serialized as consumed active seconds (``elapsed_active_s``) instead
# and rebased against the resume time on restore.
_REBASED_TIME_KEYS = frozenset({"start_time"})

# WorkflowState keys carried verbatim (already plain JSON-serializable data),
# derived from the state's own field list so new fields cannot silently drift
# out of the checkpoint. A new WorkflowState field is checkpointed by default;
# fields that must not be persisted belong in one of the exclusion sets above.
# Iteration follows declaration order so the payload layout is deterministic.
_PLAIN_STATE_KEYS: tuple[str, ...] = tuple(
    key
    for key in WorkflowState.__annotations__
    if key
    not in (
        _SPECIAL_COLLECTION_KEYS
        | _EXCLUDED_RUNTIME_KEYS
        | _TRANSIENT_CONTROL_KEYS
        | _REBASED_TIME_KEYS
    )
)


class CheckpointSchemaError(Exception):
    """Raised when a checkpoint cannot be restored due to a version mismatch.

    Failing closed (rather than loading a mismatched shape) is the M4
    requirement: a schema-incompatible checkpoint must not silently corrupt a
    resumed run.
    """


def serialize_workflow_state(
    state: dict[str, Any],
    *,
    last_event_seq: int,
    prompt_version: str = "",
    config_version: str = "",
) -> dict[str, Any]:
    """Serialize a curated ``WorkflowState`` into a versioned checkpoint dict.

    Args:
        state: The workflow state to checkpoint. Only post-node (committed)
            state should be passed — never a half-applied node delta.
        last_event_seq: The last durable event sequence written for this run,
            so a resumed run assigns new seqs strictly above this high-water
            mark (idempotent event replay).
        prompt_version: Version tag of the prompt templates in force.
        config_version: Version tag of the run configuration in force.

    Returns:
        A JSON-serializable checkpoint envelope.
    """
    payload: dict[str, Any] = {key: state.get(key) for key in _PLAIN_STATE_KEYS}
    # Persist consumed active time, not the start timestamp, so a resumed
    # run's wall-clock budget excludes the paused gap (see _REBASED_TIME_KEYS).
    start_time = state.get("start_time")
    payload["elapsed_active_s"] = (
        max(0.0, time.time() - float(start_time)) if start_time else 0.0
    )
    payload["hypotheses"] = [h.to_dict() for h in state.get("hypotheses", [])]
    metrics = state.get("metrics")
    payload["metrics"] = (
        metrics.to_dict()
        if isinstance(metrics, ExecutionMetrics)
        else ExecutionMetrics().to_dict()
    )
    articles = state.get("articles")
    payload["articles"] = (
        [a.to_dict() for a in articles] if articles else articles
    )
    payload["messages"] = _serialize_messages(state.get("messages"))

    return {
        "version": CHECKPOINT_VERSION,
        "last_event_seq": last_event_seq,
        "prompt_version": prompt_version,
        "config_version": config_version,
        "state": payload,
    }


def restore_workflow_state(
    checkpoint: dict[str, Any],
    *,
    progress_callback: Any = None,
    tool_registry: Any = None,
) -> dict[str, Any]:
    """Restore a ``WorkflowState`` from a checkpoint, ready to resume.

    Reconstructs the typed collections (hypotheses, metrics, articles),
    re-injects the excluded runtime handles from the live run, and sets the
    ``resume`` flag so the graph's conditional entry routes to the
    orchestrator rather than re-running from the supervisor.

    Args:
        checkpoint: A checkpoint produced by :func:`serialize_workflow_state`.
        progress_callback: The live progress callback to re-inject.
        tool_registry: The live tool registry to re-inject.

    Returns:
        A ``WorkflowState``-shaped dict with ``resume=True``.

    Raises:
        CheckpointSchemaError: If the checkpoint version is incompatible.
    """
    version = checkpoint.get("version")
    if version != CHECKPOINT_VERSION:
        raise CheckpointSchemaError(
            f"checkpoint version {version!r} is incompatible with "
            f"CHECKPOINT_VERSION {CHECKPOINT_VERSION}"
        )

    payload = dict(checkpoint.get("state", {}))
    payload["hypotheses"] = [
        Hypothesis.from_dict(h) for h in payload.get("hypotheses", [])
    ]
    payload["metrics"] = ExecutionMetrics.from_dict(
        payload.get("metrics") or {}
    )
    articles = payload.get("articles")
    payload["articles"] = (
        [Article.from_dict(a) for a in articles] if articles else articles
    )
    payload["messages"] = _deserialize_messages(payload.get("messages"))
    # Rebase the start timestamp so elapsed time counts only active seconds,
    # excluding the real-world gap between checkpoint and resume. The
    # fallback keeps CHECKPOINT_VERSION 1 backward compatible (no bump
    # needed): an older version-1 checkpoint carries ``start_time`` verbatim
    # and no ``elapsed_active_s`` key, and restores with its original value.
    elapsed_active_s = payload.pop("elapsed_active_s", None)
    if elapsed_active_s is not None:
        payload["start_time"] = time.time() - float(elapsed_active_s)
    for key in _EXCLUDED_RUNTIME_KEYS:
        payload.pop(key, None)
    payload["progress_callback"] = progress_callback
    payload["tool_registry"] = tool_registry
    # Route the graph's conditional entry to the orchestrator on resume.
    payload["resume"] = True
    return payload


def last_event_seq(checkpoint: dict[str, Any]) -> int:
    """Return the checkpoint's last durable event sequence (0 if absent)."""
    return int(checkpoint.get("last_event_seq", 0))

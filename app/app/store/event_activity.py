"""Closed-vocabulary ``activity`` discriminator for run_events payloads.

A ``run_events`` row's ``type`` column already carries an agent/node name
(``"generate"``, ``"ranking"``, ...) or, for the durable path's
``scientific_task`` completions, carries the node name nested in
``payload["task"]``. Either way a client wanting a per-kind icon has to
parse that free text. This module adds a small, closed ``activity`` value
computed once here and merged into every event's payload -- see
``app.store.events._append_event`` -- so the vocabulary lives in one place
and can never drift from what the engine's node graph actually reports.

Derived from ``co_scientist.agents.NODE_TO_AGENT`` (the engine's own
node -> agent grouping) rather than duplicated by hand, with two node-level
overrides where the ``generation`` agent's two nodes -- literature search
and drafting -- need different activities. Any node absent from the
mapping, or any event type this module does not recognize, resolves to the
catch-all ``ACTIVITY_OTHER`` rather than raising, so a node added to the
engine without a matching entry here degrades gracefully instead of
breaking the event stream.
"""

from __future__ import annotations

from typing import Any, cast

ACTIVITY_PLANNING = "planning"
ACTIVITY_LITERATURE_SEARCH = "literature_search"
ACTIVITY_DRAFTING = "drafting"
ACTIVITY_REVIEW = "review"
ACTIVITY_TOURNAMENT = "tournament"
ACTIVITY_EVOLUTION = "evolution"
ACTIVITY_DEDUPLICATION = "deduplication"
ACTIVITY_SAFETY = "safety"
ACTIVITY_SYNTHESIS = "synthesis"
ACTIVITY_OTHER = "other"

ACTIVITY_VALUES: frozenset[str] = frozenset(
    {
        ACTIVITY_PLANNING,
        ACTIVITY_LITERATURE_SEARCH,
        ACTIVITY_DRAFTING,
        ACTIVITY_REVIEW,
        ACTIVITY_TOURNAMENT,
        ACTIVITY_EVOLUTION,
        ACTIVITY_DEDUPLICATION,
        ACTIVITY_SAFETY,
        ACTIVITY_SYNTHESIS,
        ACTIVITY_OTHER,
    }
)

# Engine agent name (a NODE_TO_AGENT value) -> activity. Covers every node
# whose whole owning agent shares one activity.
_AGENT_ACTIVITY: dict[str, str] = {
    "supervisor": ACTIVITY_PLANNING,
    "reflection": ACTIVITY_REVIEW,
    "ranking": ACTIVITY_TOURNAMENT,
    "evolution": ACTIVITY_EVOLUTION,
    "proximity": ACTIVITY_DEDUPLICATION,
    "meta_review": ACTIVITY_SYNTHESIS,
    "safety": ACTIVITY_SAFETY,
}

# Node-level overrides: the ``generation`` agent owns both the literature
# search and the drafting node, which are two different activities, so the
# agent-level table above cannot resolve them on its own.
_NODE_ACTIVITY_OVERRIDES: dict[str, str] = {
    "literature_review": ACTIVITY_LITERATURE_SEARCH,
    "generate": ACTIVITY_DRAFTING,
}

# The canonical event vocabulary (app.engine_adapter.events) renames the
# ``supervisor`` node to ``supervisor.plan`` wherever it appears as a run
# event's own type (the demo/seed path writes canonical node names
# directly). Resolved back to the node name before the lookup below.
_TYPE_TO_NODE_ALIASES: dict[str, str] = {"supervisor.plan": "supervisor"}


def _node_to_agent() -> dict[str, str]:
    """Return the engine's node -> agent table.

    Imported lazily so this lightweight, store-layer module never forces an
    eager import of the engine package at ``app.store`` import time. The
    engine package is exempted from mypy's ``follow_imports`` here (see
    ``app/pyproject.toml``), so the cast restates the type its own
    annotation already declares.
    """
    from co_scientist.agents import NODE_TO_AGENT

    return cast("dict[str, str]", NODE_TO_AGENT)


def _activity_for_node(node_name: str) -> str:
    """Resolve one engine node name to its activity, or the catch-all."""
    override = _NODE_ACTIVITY_OVERRIDES.get(node_name)
    if override is not None:
        return override
    agent = _node_to_agent().get(node_name)
    if agent is None:
        return ACTIVITY_OTHER
    return _AGENT_ACTIVITY.get(agent, ACTIVITY_OTHER)


def activity_for_event(type_: str, payload: dict[str, Any]) -> str:
    """Resolve a run_events row's ``type``/payload to its activity.

    Args:
        type_: The event's ``type`` column value.
        payload: The event's payload, consulted only for the durable path's
            ``scientific_task`` completions, whose actual node name lives
            in ``payload["task"]`` rather than in ``type_`` itself.

    Returns:
        One of ``ACTIVITY_VALUES``; ``ACTIVITY_OTHER`` for any event type
        or node this module does not recognize -- never raises.
    """
    if type_ == "scientific_task":
        task = payload.get("task")
        return _activity_for_node(str(task)) if task else ACTIVITY_OTHER
    if type_.startswith("safety"):
        return ACTIVITY_SAFETY
    node_name = _TYPE_TO_NODE_ALIASES.get(type_, type_)
    return _activity_for_node(node_name)

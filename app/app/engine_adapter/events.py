"""Engine-event translation into the canonical mock event vocabulary.

Maps streamed engine node names to canonical event types, projects each
node's state snapshot into a mock-shaped event payload, and formats the
user-facing milestone messages surfaced for key events.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.report_render import article_stub, hypothesis_stub, match_stub


def _canonical_event_type(node_name: str) -> str:
    """Map an engine node name to the canonical mock event vocabulary.

    Only ``supervisor`` diverges from its node name (it emits
    ``supervisor.plan``). Every other node -- including any with no mock
    counterpart, such as ``review`` -- keeps its unprefixed node name, so it
    renders via the frontend's prettify fallback rather than a legacy
    ``engine.`` prefix.

    Args:
        node_name: The engine graph node name streamed by the generator.

    Returns:
        The canonical event type used across the mock, adapter, and frontend.
    """
    return "supervisor.plan" if node_name == "supervisor" else node_name


# Canonical pipeline stages the real engine runs, surfaced in the
# ``supervisor.plan`` payload's ``agents`` key so the frontend summary matches
# the mock's shape. Derived from the engine's actual graph nodes rather than
# copying the mock's list (which carries stages the engine never emits).
_ENGINE_PIPELINE_AGENTS: list[str] = [
    "supervisor",
    "literature_review",
    "generate",
    "reflection",
    "review",
    "ranking",
    "proximity",
    "evolve",
    "meta_review",
    "deep_verification",
    "research_overview",
]


def _generate_payload_extra(state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``generate`` node's payload keys."""
    hyps: list[dict[str, Any]] = state.get("hypotheses") or []
    return {
        "count": len(hyps),
        "hypotheses": [hypothesis_stub(h) for h in hyps],
    }


def _literature_review_payload_extra(state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``literature_review`` node's payload keys."""
    articles: list[dict[str, Any]] = state.get("articles") or []
    return {
        "count": len(articles),
        "evidence": [article_stub(a) for a in articles],
    }


def _ranking_payload_extra(state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``ranking`` node's payload keys."""
    matchups: list[dict[str, Any]] = state.get("tournament_matchups") or []
    return {"matches": [match_stub(m) for m in matchups]}


def _evolve_payload_extra(state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``evolve`` node's payload keys."""
    hyps: list[dict[str, Any]] = state.get("hypotheses") or []
    return {
        "children": [
            hypothesis_stub(h) for h in hyps if h.get("evolution_history")
        ]
    }


def _supervisor_plan_payload_extra(
    unused_state: dict[str, Any],
) -> dict[str, Any]:
    """Build the ``supervisor.plan`` node's payload keys."""
    del unused_state
    return {"agents": list(_ENGINE_PIPELINE_AGENTS)}


# Per-node-type payload builders, keyed by the canonical event type. Nodes
# with no entry (e.g. ``reflection``, ``review``) get no extra payload keys
# beyond the common ``node``/``iteration`` pair built in
# ``_canonical_engine_payload``.
_PAYLOAD_BUILDERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "generate": _generate_payload_extra,
    "literature_review": _literature_review_payload_extra,
    "ranking": _ranking_payload_extra,
    "evolve": _evolve_payload_extra,
    "supervisor.plan": _supervisor_plan_payload_extra,
}


def _canonical_engine_payload(
    node_name: str, node_type: str, state: dict[str, Any]
) -> dict[str, Any]:
    """Build a canonical event payload for a streamed engine node.

    Per-stage keys match the mock's payload shape (``count``, ``hypotheses``,
    ``evidence``, ``matches``, ``children``, ``agents``) so a single
    vocabulary drives ``_format_milestone`` and the raw event log console.

    The list-shaped keys are projected to minimal stubs rather than carrying
    raw engine-state objects: every consumer reads only their ``length``, and
    ``store.append_event`` JSON-serializes the payload with no fallback
    handler, so raw hypothesis/article dicts (which may carry non-serializable
    fields such as embeddings) must never be embedded whole. This mirrors the
    projection discipline in ``_persist_final_state``.

    Args:
        node_name: The engine graph node name.
        node_type: The canonical event type for ``node_name``.
        state: The cumulative engine state snapshot for this node.

    Returns:
        The event payload dict (JSON-serializable; only plain dicts/lists).
    """
    payload: dict[str, Any] = {
        "node": node_name,
        "iteration": state.get("current_iteration", 0),
    }
    builder = _PAYLOAD_BUILDERS.get(node_type)
    if builder is not None:
        payload.update(builder(state))
    return payload


def _milestone_supervisor_plan(unused_payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed supervisor plan."""
    del unused_payload
    return "Research plan ready — supervisor complete"


def _milestone_generate(payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed generation round."""
    count = payload.get("count", 0)
    itr = payload.get("iteration", 0)
    label = f"iteration {itr}" if itr else "initial"
    return f"{count} hypotheses generated ({label})"


def _milestone_ranking(payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed ranking round."""
    count = len(payload.get("matches") or [])
    itr = payload.get("iteration", 0)
    return f"Tournament complete (iteration {itr}, {count} matches)"


def _milestone_meta_review(unused_payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed meta-review."""
    del unused_payload
    return "Meta-review complete"


def _milestone_evolve(payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed evolve round."""
    count = len(payload.get("children") or [])
    itr = payload.get("iteration", 0)
    return f"{count} hypotheses evolved (iteration {itr})"


# Per-node-type milestone builders, keyed by the canonical event type. Nodes
# with no entry (e.g. ``reflection``, ``review``) generate no milestone,
# mirroring ``_PAYLOAD_BUILDERS``'s dispatch shape above.
_MILESTONE_BUILDERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "supervisor.plan": _milestone_supervisor_plan,
    "generate": _milestone_generate,
    "ranking": _milestone_ranking,
    "meta_review": _milestone_meta_review,
    "evolve": _milestone_evolve,
}


def _format_milestone(node_type: str, payload: dict[str, Any]) -> str | None:
    """Return a human-readable milestone string for key node events, or None.

    Reads the single canonical (mock-shaped) payload vocabulary. Unknown or
    legacy types (e.g. old persisted ``engine.*`` events) fall through to
    ``None``, so no milestone is generated — the same behaviour today's code
    has for unmatched types.
    """
    builder = _MILESTONE_BUILDERS.get(node_type)
    return builder(payload) if builder is not None else None

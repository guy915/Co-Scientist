"""Tests for the engine adapter's canonical event vocabulary.

The engine node -> canonical event mapping in ``engine_adapter.events`` is
what the durable node executor (``engine_tasks_emit``) emits through: every
engine node is normalized into the canonical event type + payload shape the
frontend reads, and the milestone side-messages are derived from that same
payload. CI only exercises the offline path, so these tests are the sole
guard on the node->type mapping, the normalized payload shape, and the
milestone messages -- exercised directly against the mapping functions rather
than through any run driver, so they stay fast and deterministic.

The end-to-end emission of these events (and the post-drain stage events and
metrics) is covered by the durable-path tests in ``test_engine_tasks_dispatch``
and ``test_offline_workflow``.
"""

from __future__ import annotations

from typing import Any

from app import store
from app.engine_adapter.events import (
    _canonical_engine_payload,
    _canonical_event_type,
    append_node_milestone,
)

# Node names the real engine registers (generator.py ``add_node`` calls) and
# the canonical event type each must be normalized to by the adapter.
_ENGINE_NODES = [
    "supervisor",
    "literature_review",
    "generate",
    "reflection",
    "review",
    "ranking",
    "deep_verification",
    "meta_review",
    "evolve",
    "proximity",
    "research_overview",
]
_EXPECTED_TYPES = {
    "supervisor": "supervisor.plan",
    "literature_review": "literature_review",
    "generate": "generate",
    "reflection": "reflection",
    "review": "review",  # no mock counterpart — keeps its node name
    "ranking": "ranking",
    "deep_verification": "deep_verification",
    "meta_review": "meta_review",
    "evolve": "evolve",
    "proximity": "proximity",
    "research_overview": "research_overview",
}


def _streaming_hypotheses() -> list[dict[str, Any]]:
    """The two streamed hypotheses (only the first carries review/probes)."""
    return [
        {
            "id": "eng-h1",
            "text": "H1: a mechanistic claim about the pathway.",
            "elo_rating": 1300,
            "win_count": 2,
            "loss_count": 0,
            "evolution_history": [],
            "reviews": [{"review_summary": "Sound mechanism."}],
            "deep_verification_verdict": "verified",
            "deep_verification_probes": [
                {"question": "Does X cause Y?", "answer": "Yes, via Z."}
            ],
        },
        {
            "id": "eng-h2",
            "text": "H2: an evolved variant of the leading claim.",
            "elo_rating": 1250,
            "win_count": 1,
            "loss_count": 1,
            "evolution_history": [{"round": 1}],
            "reviews": [],
        },
    ]


def _streaming_research_overview() -> dict[str, Any]:
    """The streamed research-overview sub-state."""
    return {
        "overview": {"summary": "Targeting the pathway looks promising."},
        "nih_specific_aims": {"introduction": "Background.", "aims": []},
    }


def _streaming_proximity_graph() -> dict[str, Any]:
    """The streamed one-edge proximity graph."""
    return {
        "edges": [
            {
                "source": "eng-h1",
                "target": "eng-h2",
                "similarity": 0.8,
                "cluster_id": "cluster-0",
            }
        ],
        "meta": {"method": "embedding", "version": 1},
    }


def _engine_streaming_state() -> dict[str, Any]:
    """A plain-dict engine snapshot the fake generator yields for every node."""
    return {
        "hypotheses": _streaming_hypotheses(),
        "articles": [
            {
                "title": "A1",
                "url": "https://example.org/a1",
                "abstract": (
                    "H1: a mechanistic claim about the pathway. H2: an "
                    "evolved variant of the leading claim."
                ),
            }
        ],
        "tournament_matchups": [
            {
                "hypothesis_a": "H1: a mechanistic claim about the pathway.",
                "hypothesis_b": "H2: an evolved variant of the leading claim.",
                "hypothesis_a_id": "eng-h1",
                "hypothesis_b_id": "eng-h2",
                "winner_id": "eng-h1",
                "winner": "a",
            }
        ],
        "meta_review": {
            "summary": "Leading hypotheses converge on one mechanism.",
            "common_strengths": ["Clear mechanism"],
            "common_weaknesses": ["Thin evidence"],
        },
        "evolution_details": [],
        "research_overview": _streaming_research_overview(),
        "proximity_graph": _streaming_proximity_graph(),
        "current_iteration": 1,
    }


def _payloads_by_type() -> dict[str, dict[str, Any]]:
    """Map every engine node through the shared adapter into canonical events.

    Mirrors what ``engine_tasks_emit`` does per node: resolve the canonical
    type, then project the snapshot into the frontend-facing payload.
    """
    state = _engine_streaming_state()
    by_type: dict[str, dict[str, Any]] = {}
    for node in _ENGINE_NODES:
        node_type = _canonical_event_type(node)
        by_type[node_type] = _canonical_engine_payload(node, node_type, state)
    return by_type


def _assert_canonical_event_types(types_emitted: list[str]) -> None:
    """No engine.* leaks; every node maps to its canonical type."""
    # No legacy engine.* types leak out of the adapter.
    assert not any(t.startswith("engine.") for t in types_emitted)

    # Every engine node maps to its canonical type.
    for node, expected in _EXPECTED_TYPES.items():
        assert expected in types_emitted, f"{node} -> {expected} missing"


def _assert_normalized_payloads(by_type: dict[str, Any]) -> None:
    """Payload keys are normalized to the mock's shape the frontend reads."""
    generate = by_type["generate"]
    assert generate["count"] == 2
    assert len(generate["hypotheses"]) == 2
    assert isinstance(by_type["ranking"]["matches"], list)
    assert len(by_type["ranking"]["matches"]) == 1
    assert len(by_type["evolve"]["children"]) == 1  # only the evolved variant
    assert by_type["literature_review"]["count"] == 1
    assert len(by_type["literature_review"]["evidence"]) == 1
    assert by_type["supervisor.plan"]["agents"]


def _assert_full_fidelity_payloads(by_type: dict[str, Any]) -> None:
    """Full-fidelity payloads: only eng-h1 carries reviews/deep-verification."""
    assert by_type["reflection"]["reviewed"] == 1
    assert by_type["proximity"]["clusters"] == {"cluster-0": 2}
    assert (
        by_type["meta_review"]["critique"]
        == "Leading hypotheses converge on one mechanism."
    )
    assert by_type["meta_review"]["top_k_ids"] == ["eng-h1", "eng-h2"]
    assert by_type["deep_verification"]["verified"] == 1
    assert by_type["deep_verification"]["probes"] == [
        {
            "hypothesis_id": "eng-h1",
            "verdict": "verified",
            "probes": [
                {"question": "Does X cause Y?", "answer": "Yes, via Z."}
            ],
        }
    ]
    assert (
        by_type["research_overview"]["research_overview"]
        == _streaming_research_overview()
    )


def test_engine_adapter_emits_canonical_event_types(isolated_db: str) -> None:
    """The adapter maps every node to the canonical vocabulary, never engine.*.

    CI only exercises the offline path, so this is the sole guard on the
    node->type mapping and the frontend-facing payload shape.
    """
    by_type = _payloads_by_type()

    _assert_canonical_event_types(list(by_type))
    _assert_normalized_payloads(by_type)
    _assert_full_fidelity_payloads(by_type)


def test_engine_adapter_generates_canonical_milestones(
    isolated_db: str,
) -> None:
    """Milestone messages are produced from the canonical payload shape."""
    run = store.create_run("Milestone goal", "standard", "engine", {})
    for node_type, payload in _payloads_by_type().items():
        append_node_milestone(run.id, node_type, payload, db_path=isolated_db)

    msgs = store.list_messages(run.id, db_path=isolated_db)
    milestones = [m for m in msgs if m.kind == "milestone"]
    text = " | ".join(m.content for m in milestones)
    assert "Research plan ready" in text
    assert "2 hypotheses generated" in text
    assert "1 matches" in text  # ranking milestone counts len(matches)
    # Milestones for the newly-enriched node types, derived from the same
    # canonical payloads the builders emit (only eng-h1 carries a review /
    # deep-verification probe in the fixture).
    assert "1 hypotheses reviewed" in text
    assert "1 clusters identified" in text
    assert "1 hypotheses verified" in text
    assert "Research overview ready" in text


def test_a_retrieval_outage_rides_every_event_after_it() -> None:
    """The lost work emits nothing, so the loss has to travel on what does.

    A run with no reachable source is routed around the literature review
    and the observation reviews, which means the absence of those events
    is the only live signal -- and an absence looks exactly like a run
    that has not got there yet. Carrying the fact forward is what lets a
    watcher see it while the run is going.
    """
    state: dict[str, Any] = {
        "current_iteration": 1,
        "retrieval_degradation": {
            "reason": "mcp_unreachable",
            "lost": ["literature_review"],
            "floor": "none",
        },
    }

    payload = _canonical_engine_payload("generate", "generate", state)

    assert payload["retrieval_degraded"]["reason"] == "mcp_unreachable"


def test_a_healthy_run_carries_no_outage_key() -> None:
    """Every ordinary event stays the shape its consumers already read."""
    payload = _canonical_engine_payload(
        "generate", "generate", {"current_iteration": 1}
    )

    assert "retrieval_degraded" not in payload

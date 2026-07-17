"""Tests for the real-engine adapter's streamed event vocabulary.

The real-engine branch of ``engine_adapter.run_workflow`` normalizes each
engine node's snapshot into the canonical event type + payload shape the
frontend reads. CI only exercises the mock path, so these fake-driven tests are
the sole guard on the node->type mapping, the normalized payload shape, and the
milestone messages derived from it.

The shared ``drain`` helper (collect an async generator into a list) comes
from ``tests._client``.
"""

from __future__ import annotations

import sys
import types
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app import engine_adapter, store
from tests._client import drain as _drain

# Node names streamed by the real engine (generator.py ``add_node`` calls) and
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


def _engine_streaming_state() -> dict[str, Any]:
    """A plain-dict engine snapshot the fake generator yields for every node."""
    return {
        "hypotheses": [
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
        ],
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
        "research_overview": {
            "overview": {"summary": "Targeting the pathway looks promising."},
            "nih_specific_aims": {"introduction": "Background.", "aims": []},
        },
        "proximity_graph": {
            "edges": [
                {
                    "source": "eng-h1",
                    "target": "eng-h2",
                    "similarity": 0.8,
                    "cluster_id": "cluster-0",
                }
            ],
            "meta": {"method": "embedding", "version": 1},
        },
        "current_iteration": 1,
    }


class _FakeGenerator:
    """Stand-in for the engine's HypothesisGenerator, no LLM required."""

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def generate_hypotheses(
        self,
        *,
        research_goal: str,
        stream: bool,
        run_id: str,
        opts: dict[str, Any] | None = None,
        checkpoint_callback: Any = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        _ = (research_goal, stream, run_id, opts, checkpoint_callback)
        state = _engine_streaming_state()
        for node in _ENGINE_NODES:
            yield node, state


def _run_fake_engine(
    monkeypatch: pytest.MonkeyPatch,
    goal: str,
    generator_cls: type[_FakeGenerator] = _FakeGenerator,
) -> tuple[Any, list[Any]]:
    """Patch in the fake generator and drain a full engine-provider run.

    Resolves the lazy ``from co_scientist import HypothesisGenerator`` to the
    fake regardless of whether the real engine is installed.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        goal: The research goal to create the run with.
        generator_cls: The fake generator class to install as the engine.

    Returns:
        A tuple of the created run and its drained events.
    """
    fake_module = types.SimpleNamespace(HypothesisGenerator=generator_cls)
    monkeypatch.setitem(sys.modules, "co_scientist", fake_module)
    # This suite validates the engine event vocabulary, not the safety gate;
    # keep the app-level semantic screen offline so its real provider call
    # cannot flake these deterministic assertions.
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)

    run = store.create_run(goal, "standard", "engine", {})
    events = _drain(
        engine_adapter.run_workflow(
            run.id,
            run.research_goal,
            run.config,
            force_provider="engine",
            sleep_seconds=0,
        )
    )
    return run, events


def test_engine_adapter_emits_canonical_event_types(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real-engine branch emits the canonical vocabulary, never engine.*.

    CI only exercises the mock path, so this fake-driven test is the sole guard
    on the node→type mapping and the frontend-facing payload shape.
    """
    _, events = _run_fake_engine(monkeypatch, "Canonical vocab goal")

    types_emitted = [e["type"] for e in events]

    # No legacy engine.* types leak out of the adapter.
    assert not any(t.startswith("engine.") for t in types_emitted)

    # Every engine node maps to its canonical type.
    for node, expected in _EXPECTED_TYPES.items():
        assert expected in types_emitted, f"{node} -> {expected} missing"

    # Lifecycle + report events remain canonical too. Intake screening runs at
    # the shared boundary, so it leads, then the engine marks the run running.
    assert types_emitted[0] == "safety.intake"
    assert types_emitted[1] == "status"  # running
    assert "report" in types_emitted
    assert types_emitted[-1] == "status"  # completed

    by_type = {e["type"]: e["payload"] for e in events}

    # Payload keys are normalized to the mock's shape the frontend reads.
    generate = by_type["generate"]
    assert generate["count"] == 2
    assert len(generate["hypotheses"]) == 2
    assert isinstance(by_type["ranking"]["matches"], list)
    assert len(by_type["ranking"]["matches"]) == 1
    assert len(by_type["evolve"]["children"]) == 1  # only the evolved variant
    assert by_type["literature_review"]["count"] == 1
    assert len(by_type["literature_review"]["evidence"]) == 1
    assert by_type["supervisor.plan"]["agents"]

    # Full-fidelity payloads: only eng-h1 carries reviews/deep-verification.
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
    assert by_type["research_overview"]["research_overview"] == {
        "overview": {"summary": "Targeting the pathway looks promising."},
        "nih_specific_aims": {"introduction": "Background.", "aims": []},
    }

    # Post-drain stage events: emitted once after the engine's own node
    # stream finishes, from counts the drain computed while persisting.
    for stage_type in (
        "safety.hypothesis",
        "citation.grounding",
        "citation_audit",
    ):
        assert stage_type in types_emitted

    safety_payload = by_type["safety.hypothesis"]
    assert set(safety_payload) == {"screened", "blocked", "eligible"}
    assert safety_payload["screened"] == 2  # both persisted hypotheses
    assert (
        safety_payload["eligible"]
        == safety_payload["screened"] - safety_payload["blocked"]
    )

    grounding_payload = by_type["citation.grounding"]
    assert set(grounding_payload) == {"grounded", "blocked", "eligible"}
    assert (
        grounding_payload["eligible"]
        == grounding_payload["grounded"] - grounding_payload["blocked"]
    )

    citation_audit_payload = by_type["citation_audit"]
    # No citation_map on the fake hypotheses, so every state count is zero,
    # but the full citation-state vocabulary is still present.
    assert citation_audit_payload
    assert all(isinstance(v, int) for v in citation_audit_payload.values())


def test_engine_adapter_generates_canonical_milestones(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Milestone messages are produced from the canonical payload shape."""
    run, _ = _run_fake_engine(monkeypatch, "Milestone goal")

    msgs = store.list_messages(run.id, db_path=isolated_db)
    milestones = [m for m in msgs if m.kind == "milestone"]
    text = " | ".join(m.content for m in milestones)
    assert "Research plan ready" in text
    assert "2 hypotheses generated" in text
    assert "1 matches" in text  # ranking milestone counts len(matches)


def test_engine_adapter_persists_streamed_metrics(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last streamed cumulative metrics dict lands in the store.

    ``total_time`` is absent from the snapshot, so the adapter must fill it
    from its own wall clock.
    """
    streamed_metrics = {
        "hypothesis_count": 2,
        "reviews_count": 3,
        "tournaments_count": 1,
        "evolutions_count": 1,
        "llm_calls": 9,
        "phase_times": {"generate": 1.5, "ranking": 0.5},
    }
    state = _engine_streaming_state()
    state["metrics"] = streamed_metrics

    class _MetricsGenerator(_FakeGenerator):
        async def generate_hypotheses(
            self,
            *,
            research_goal: str,
            stream: bool,
            run_id: str,
            opts: dict[str, Any] | None = None,
            checkpoint_callback: Any = None,
        ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
            _ = (research_goal, stream, run_id, opts, checkpoint_callback)
            for node in _ENGINE_NODES:
                yield node, state

    # Route through _run_fake_engine rather than draining inline: it also
    # forces the semantic intake screen offline. Without that, a real
    # provider call classifies the goal and intermittently withholds the
    # run at intake, so no metrics ever land (the historical flake here).
    run, _ = _run_fake_engine(
        monkeypatch, "Metrics persistence goal", _MetricsGenerator
    )

    persisted = store.get_run_metrics(run.id, db_path=isolated_db)
    assert persisted is not None
    for key, value in streamed_metrics.items():
        assert persisted[key] == value
    assert persisted["total_time"] > 0

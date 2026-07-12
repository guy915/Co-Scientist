"""Tests for versioned workflow checkpoint serialize/restore (Milestone 4).

The checkpoint boundary is topology-independent, so these prove the core M4
invariant — a curated ``WorkflowState`` round-trips byte-for-byte (via its
serializable projection), non-serializable runtime handles are excluded and
re-injected, and an incompatible version fails closed — without running the
graph.
"""

import types

import pytest

import co_scientist.checkpoint as checkpoint_module
from co_scientist.checkpoint import (
    CHECKPOINT_VERSION,
    CheckpointSchemaError,
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.models import (
    ExecutionMetrics,
    Hypothesis,
    HypothesisOrigin,
    HypothesisReview,
)


def _rich_state() -> dict[str, object]:
    """A workflow state carrying every non-trivial checkpoint field."""
    parent = Hypothesis(text="parent hypothesis", elo_rating=1240)
    child = Hypothesis(
        text="child hypothesis",
        parent_id=parent.id,
        generation=1,
        origin=HypothesisOrigin.EVOLUTION,
        reviews=[
            HypothesisReview(
                review_summary="ok",
                scores={"novelty": 4},
                safety_ethical_concerns="none",
                detailed_feedback={"a": "b"},
                constructive_feedback="tighten",
                overall_score=4.0,
            )
        ],
        win_count=2,
        loss_count=1,
    )
    return {
        "research_goal": "Explain X",
        "model_name": "fake/model",
        "supervisor_model_name": "fake/model",
        "max_iterations": 3,
        "hypotheses": [parent, child],
        "current_iteration": 2,
        "task_history": [{"task_type": "evolve", "reason": "leaders"}],
        "next_task": "generate",
        "termination_reason": None,
        "budget": {"max_iterations": 3, "max_llm_calls": 100},
        "orchestrator_state": {"prev_top_elo": 1240, "rank_stable_cycles": 1},
        "meta_review": {"summary": "s"},
        "proximity_graph": {"edges": [], "meta": {"edge_count": 0}},
        "tournament_matchups": [{"winner": "a"}],
        "metrics": ExecutionMetrics(llm_calls=17, reviews_count=4),
        "start_time": 1000.0,
        "run_id": "run-123",
        "messages": [{"role": "assistant", "content": "hi"}],
        # Runtime handles that must NOT be serialized.
        "progress_callback": lambda *a: None,
        "tool_registry": object(),
    }


def test_round_trip_preserves_serializable_state() -> None:
    """Serialize then restore reproduces the pool, lineage, metrics, ledger."""
    state = _rich_state()
    checkpoint = serialize_workflow_state(state, last_event_seq=42)
    restored = restore_workflow_state(checkpoint)

    assert restored["research_goal"] == "Explain X"
    assert restored["current_iteration"] == 2
    assert restored["next_task"] == "generate"
    assert restored["budget"] == {"max_iterations": 3, "max_llm_calls": 100}
    assert restored["task_history"] == state["task_history"]
    assert restored["orchestrator_state"] == state["orchestrator_state"]

    # Hypotheses and their lineage round-trip.
    hyps = restored["hypotheses"]
    assert [h.text for h in hyps] == ["parent hypothesis", "child hypothesis"]
    child = hyps[1]
    assert child.parent_id == hyps[0].id
    assert child.generation == 1
    assert child.origin is HypothesisOrigin.EVOLUTION
    assert child.win_count == 2 and child.loss_count == 1
    assert child.reviews[0].overall_score == 4.0

    # Metrics round-trip.
    assert restored["metrics"].llm_calls == 17
    assert restored["metrics"].reviews_count == 4


def test_runtime_handles_excluded_and_reinjected() -> None:
    """The callback/registry are not serialized but are re-injected."""
    state = _rich_state()
    checkpoint = serialize_workflow_state(state, last_event_seq=1)

    # Not present in the serialized envelope.
    assert "progress_callback" not in checkpoint["state"]
    assert "tool_registry" not in checkpoint["state"]

    sentinel_cb = lambda *a: "cb"  # noqa: E731
    sentinel_registry = object()
    restored = restore_workflow_state(
        checkpoint,
        progress_callback=sentinel_cb,
        tool_registry=sentinel_registry,
    )
    assert restored["progress_callback"] is sentinel_cb
    assert restored["tool_registry"] is sentinel_registry


def test_restore_sets_resume_flag() -> None:
    """A restored state carries resume=True so the graph resumes."""
    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=1)
    assert restore_workflow_state(checkpoint)["resume"] is True


def _freeze_time(monkeypatch: pytest.MonkeyPatch, now: float) -> None:
    """Pin the checkpoint module's clock to a fixed timestamp."""
    monkeypatch.setattr(
        checkpoint_module, "time", types.SimpleNamespace(time=lambda: now)
    )


def test_restore_rebases_start_time_excluding_idle_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Elapsed time after resume counts active seconds, not the paused gap.

    A run checkpointed after 300 active seconds and resumed much later must
    not immediately trip ``max_wall_clock_s``: the checkpoint stores consumed
    time, and restore rebases ``start_time`` against the resume clock.
    """
    state = _rich_state()
    state["start_time"] = 1000.0
    _freeze_time(monkeypatch, 1300.0)
    checkpoint = serialize_workflow_state(state, last_event_seq=1)

    # The envelope carries consumed active time, not the raw timestamp.
    assert "start_time" not in checkpoint["state"]
    assert checkpoint["state"]["elapsed_active_s"] == pytest.approx(300.0)

    # Resume after a large real-world gap.
    _freeze_time(monkeypatch, 500_000.0)
    restored = restore_workflow_state(checkpoint)
    assert 500_000.0 - restored["start_time"] == pytest.approx(300.0)


def test_restore_legacy_checkpoint_keeps_verbatim_start_time() -> None:
    """A version-1 checkpoint without elapsed_active_s restores unchanged.

    Older checkpoints carried ``start_time`` verbatim; the fallback preserves
    that value so no version bump was needed for the rebasing change.
    """
    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=1)
    del checkpoint["state"]["elapsed_active_s"]
    checkpoint["state"]["start_time"] = 1234.5

    restored = restore_workflow_state(checkpoint)
    assert restored["start_time"] == 1234.5


def test_checkpoint_records_last_event_seq() -> None:
    """The checkpoint carries the last durable event seq (high-water mark)."""
    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=99)
    assert checkpoint["last_event_seq"] == 99


def test_incompatible_version_fails_closed() -> None:
    """Restoring a mismatched-version checkpoint raises, never loads."""
    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=1)
    checkpoint["version"] = CHECKPOINT_VERSION + 1
    with pytest.raises(CheckpointSchemaError):
        restore_workflow_state(checkpoint)


def test_checkpoint_is_json_serializable() -> None:
    """The envelope must be JSON-serializable for durable SQLite storage."""
    import json

    checkpoint = serialize_workflow_state(_rich_state(), last_event_seq=1)
    dumped = json.dumps(checkpoint)
    reloaded = json.loads(dumped)
    restored = restore_workflow_state(reloaded)
    assert restored["run_id"] == "run-123"


def test_langchain_messages_round_trip_through_json() -> None:
    """LangChain messages (added by ``add_messages``) survive JSON persistence.

    At runtime the ``messages`` channel holds ``BaseMessage`` objects, which
    are not JSON-serializable; the serializer must convert them so the app
    store can ``json.dumps`` the envelope, and restore them on the way back.
    """
    import json

    from langchain_core.messages import AIMessage, HumanMessage

    state = _rich_state()
    state["messages"] = [
        HumanMessage(content="goal"),
        AIMessage(content="hypothesis drafted"),
    ]

    checkpoint = serialize_workflow_state(state, last_event_seq=1)
    # The envelope is genuinely JSON-serializable (no BaseMessage leaks).
    reloaded = json.loads(json.dumps(checkpoint))
    restored = restore_workflow_state(reloaded)

    messages = restored["messages"]
    assert [type(m).__name__ for m in messages] == [
        "HumanMessage",
        "AIMessage",
    ]
    assert [m.content for m in messages] == ["goal", "hypothesis drafted"]

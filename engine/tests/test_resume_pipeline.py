"""Engine-level checkpoint/resume proof (Milestone 4, tier 1).

Interrupts a real graph run at a safe boundary (a full post-node state right
before the orchestrator would run), checkpoints that state, restores it in a
freshly rebuilt generator (simulating a process restart), and resumes to
completion. Asserts the resume mechanism's invariants: the checkpointed
hypotheses are preserved byte-for-byte (same ids and texts — resume re-enters
at the orchestrator and never re-runs a completed node), nothing is duplicated
or lost, and the run reaches a proper terminal state.

Byte-identical whole-run determinism (the acceptance's "same as an
uninterrupted control") is proven separately at the app level with the
deterministic mock workflow; the engine's fake LLM uses a process-global
counter, so two independent runs draw different stub texts — that is a test
harness artifact, not a resume defect, which is why this test compares against
the checkpointed pool rather than a second run.
"""

from typing import Any

import pytest

from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.generator import (
    GeneratorOptions,
    HypothesisGenerator,
)
from tests._llm_fake import install_fake_llm


def _make() -> HypothesisGenerator:
    return HypothesisGenerator(
        model_name="fake/model",
        max_iterations=2,
        initial_hypotheses_count=2,
        evolution_max_count=2,
        options=GeneratorOptions(
            tournament_pairs=2,
            enable_cache=False,
        ),
    )


def _pre_orchestrator_index(states: list[dict[str, Any]]) -> int:
    """Return the first full state right before the orchestrator runs.

    That boundary has every hypothesis reviewed and a tournament recorded, but
    no scheduling decision yet (``next_task`` is None). Resuming from it
    re-enters the orchestrator for the first time — no completed node re-runs.
    """
    for i, s in enumerate(states):
        hyps = s.get("hypotheses") or []
        if (
            hyps
            and all(h.reviews for h in hyps)
            and s.get("tournament_matchups")
            and not s.get("next_task")
        ):
            return i
    raise AssertionError("no pre-orchestrator boundary found in the stream")


async def _stream_states(
    gen: HypothesisGenerator, goal: str
) -> list[dict[str, Any]]:
    """Run the graph in values mode, returning every full post-node state."""
    initial = await gen._prepare_generation(
        goal, opts={"enable_literature_review_node": False}
    )
    assert gen._graph is not None
    states: list[dict[str, Any]] = []
    async for full_state in gen._graph.astream(
        initial, stream_mode="values", config={"recursion_limit": 100}
    ):
        states.append(full_state)
    return states


def _assert_preserves_and_completes(
    boundary: dict[str, Any], final: dict[str, Any]
) -> None:
    """Assert resume preserved the checkpointed pool and completed cleanly."""
    boundary_by_id = {h.id: h for h in boundary["hypotheses"]}
    final_ids = [h.id for h in final["hypotheses"]]

    # No duplicated hypotheses.
    assert len(final_ids) == len(set(final_ids))
    # Every checkpointed hypothesis survives byte-for-byte (id + text).
    for hyp in final["hypotheses"]:
        if hyp.id in boundary_by_id:
            assert hyp.text == boundary_by_id[hyp.id].text
    # Nothing checkpointed was lost.
    assert set(boundary_by_id) <= set(final_ids)
    # The resumed run reached a proper terminal state.
    assert final.get("termination_reason")
    assert final.get("research_overview")


async def test_resume_preserves_checkpointed_pool_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interrupt at a safe boundary, resume in a rebuilt generator, complete."""
    install_fake_llm(monkeypatch)

    states = await _stream_states(_make(), "Explain how protein X folds")
    boundary = states[_pre_orchestrator_index(states)]
    checkpoint = serialize_workflow_state(boundary, last_event_seq=10)

    # Simulate a process restart: a fresh generator rebuilds the graph.
    restarted = _make()
    await restarted._prepare_generation(
        "Explain how protein X folds",
        opts={"enable_literature_review_node": False},
    )
    resumed_state = restore_workflow_state(
        checkpoint, tool_registry=restarted._tool_registry
    )
    assert resumed_state["resume"] is True
    assert restarted._graph is not None
    resumed_final = await restarted._graph.ainvoke(
        resumed_state, config={"recursion_limit": 100}
    )

    _assert_preserves_and_completes(boundary, resumed_final)


async def test_double_restart_preserves_pool_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive checkpoint/restore cycles still preserve and complete."""
    install_fake_llm(monkeypatch)

    gen = _make()
    states = await _stream_states(gen, "goal")
    boundary = states[_pre_orchestrator_index(states)]

    cp1 = serialize_workflow_state(boundary, last_event_seq=1)
    r1 = restore_workflow_state(cp1)
    cp2 = serialize_workflow_state(r1, last_event_seq=2)
    r2 = restore_workflow_state(cp2)

    assert gen._graph is not None
    final = await gen._graph.ainvoke(r2, config={"recursion_limit": 100})
    _assert_preserves_and_completes(boundary, final)

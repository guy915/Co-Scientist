from __future__ import annotations

import asyncio
import json
import random
from typing import Any, cast

import jsonschema

from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.llm.structured.validate import get_fallback_response
from co_scientist.models import ExecutionMetrics
from co_scientist.offline import llm as offline_llm
from co_scientist.offline.llm import (
    _GENERATED_VOCABULARY,
    leaf_text,
    subject_terms,
)
from co_scientist.progress import _ACTIVE_WORKFLOW_STATE, emit_progress
from co_scientist.schemas.synthesis import RESEARCH_OVERVIEW_SCHEMA
from co_scientist.state import WorkflowState


def test_generated_text_is_never_mined_as_subject_matter() -> None:
    """Mining generated parent text compounds filler across evolution cycles."""
    rng = random.Random(0)
    generated = leaf_text(rng, 1, "statement", ("resistance", "biofilms"))

    terms = subject_terms(f"Original Hypothesis: {generated}")

    assert not set(terms) & _GENERATED_VOCABULARY


def test_one_goal_yields_many_distinct_token_bags() -> None:
    """Evolution dedup uses token coverage; term permutations are not new.
    Cold caches are required when comparing alternative offline generators."""
    terms = subject_terms("Research Goal: cardiac fibrosis dynamics\n\n")
    assert len(terms) == 3, terms

    bags = {
        frozenset(
            leaf_text(random.Random(seed), 1, "hypothesis", terms)
            .lower()
            .replace(",", " ")
            .split()
        )
        for seed in range(5000)
    }

    assert len(bags) > 300, len(bags)


async def test_offline_acompletion_sizes_directions_past_the_preview_gate() -> (
    None
):
    """The overview preview requires at least two named directions."""
    schema = RESEARCH_OVERVIEW_SCHEMA["schema"]

    response = await offline_llm.offline_acompletion(
        model=offline_llm.DEFAULT_OFFLINE_MODEL,
        messages=[
            {
                "role": "user",
                "content": "Top-ranked hypotheses (highest Elo first):\n"
                "1. (Elo 1200) first.\n",
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "research_overview",
                "schema": schema,
            },
        },
    )

    parsed = json.loads(response.choices[0].message.content)
    jsonschema.validate(instance=parsed, schema=schema)
    directions = parsed["overview"]["research_directions"]
    assert len(directions) >= 2
    titles = [d["title"] for d in directions]
    assert all(titles)
    assert len(set(titles)) == len(titles)


def _fresh_state(**extra: Any) -> WorkflowState:
    state: dict[str, Any] = {"degraded_nodes": []}
    state.update(extra)
    return cast(WorkflowState, state)


async def test_degradations_accumulate_in_serve_order() -> None:
    state = cast(WorkflowState, {})
    await emit_progress(state, "phase", "working", 10)

    get_fallback_response({"name": "meta_review"})
    get_fallback_response({"name": "research_overview"})

    assert state["degraded_nodes"] == ["meta_review", "research_overview"]


async def test_degradation_emits_progress_event() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    async def callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    state = _fresh_state(progress_callback=callback)
    await emit_progress(state, "phase", "working", 10)

    get_fallback_response({"name": "research_overview"})
    await asyncio.sleep(0)

    degraded_events = [e for e in events if e[0] == "schema_degraded"]
    assert len(degraded_events) == 1
    payload = degraded_events[0][1]
    assert payload["schema"] == "research_overview"
    assert "research_overview" in payload["message"]


async def test_degradation_event_failure_cannot_break_the_run() -> None:

    async def callback(event: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("listener exploded")

    state = _fresh_state()
    await emit_progress(state, "phase", "working", 10)
    # Installed after the stash so the raising listener only hears the
    # degradation event under test.
    state["progress_callback"] = callback

    fallback = get_fallback_response({"name": "meta_review"})
    await asyncio.sleep(0)

    assert fallback is not None
    assert state["degraded_nodes"] == ["meta_review"]


def test_durable_commit_captures_recorded_degradation() -> None:
    """Mid-node fallback appends must survive whole-state checkpoint commits."""
    from co_scientist.task_runtime import apply_task_update

    state = _fresh_state()
    _ACTIVE_WORKFLOW_STATE.set(state)

    get_fallback_response({"name": "meta_review"})
    committed = apply_task_update(state, {"meta_review": {}})

    assert committed["degraded_nodes"] == ["meta_review"]


def test_checkpoint_round_trips_degraded_nodes() -> None:
    state: dict[str, Any] = {
        "hypotheses": [],
        "articles": None,
        "messages": [],
        "metrics": ExecutionMetrics(),
        "degraded_nodes": ["meta_review", "research_overview"],
    }

    envelope = serialize_workflow_state(state, last_event_seq=3)
    assert envelope["state"]["degraded_nodes"] == [
        "meta_review",
        "research_overview",
    ]

    restored = restore_workflow_state(envelope)
    assert restored["degraded_nodes"] == [
        "meta_review",
        "research_overview",
    ]

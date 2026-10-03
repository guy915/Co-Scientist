"""Offline contracts for offline content."""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, cast

import jsonschema
import pytest

from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.generator.initial_state import (
    RunCapabilities,
    RunIdentity,
    _build_initial_state,
)
from co_scientist.generator.streaming import (
    _build_generation_result,
    _initial_cumulative_stream_state,
)
from co_scientist.llm.structured.validate import get_fallback_response
from co_scientist.models import ExecutionMetrics
from co_scientist.offline import llm as offline_llm
from co_scientist.offline.llm import (
    _CRITIQUE_TEMPLATES,
    _EXPERIMENT_TEMPLATES,
    _GENERATED_VOCABULARY,
    _GO_NO_GO_TEMPLATES,
    _PHASE_LABEL_TEMPLATES,
    _RECOMMENDED_IDEA_TEMPLATES,
    _SCOPE_CLAUSES,
    _TIME_ESTIMATE_TEMPLATES,
    _goal_text,
    leaf_text,
    subject_terms,
)
from co_scientist.progress import _ACTIVE_WORKFLOW_STATE, emit_progress
from co_scientist.schemas.synthesis import RESEARCH_OVERVIEW_SCHEMA
from co_scientist.state import WorkflowState

_GOAL_PROMPT = """# Generation Agent

The overarching objective is to develop a novel hypothesis.

Research Goal: What mechanisms drive antibiotic resistance in
Staphylococcus aureus biofilms?

Criteria for a high-quality hypothesis:
Run setup:
- Focus: Balance -- weigh evidence, novelty and feasibility evenly.
- Requirements: cite sources in author-year form.
"""


def test_the_goal_span_stops_before_the_surrounding_boilerplate() -> None:
    """Only the goal is scanned, not the template it is embedded in.

    A goal is one or two sentences inside a prompt that is mostly
    scaffolding, so an unbounded scan is dominated by the scaffolding:
    offline runs came out talking about "author-year" and "requirements"
    whatever they were actually about.
    """
    span = _goal_text(_GOAL_PROMPT)

    assert "antibiotic resistance" in span
    assert "author-year" not in span
    assert "Requirements" not in span


def test_terms_come_from_the_goal() -> None:
    """The run's own subject drives the vocabulary."""
    terms = subject_terms(_GOAL_PROMPT)

    assert "antibiotic" in terms
    assert "biofilms" in terms
    assert "requirements" not in terms


def test_a_prompt_with_no_goal_falls_back_rather_than_inventing() -> None:
    """With nothing to ground on, generic terms beat prompt scaffolding."""
    terms = subject_terms("Some text with no labelled goal at all here.")

    assert "pathway flux" in terms


def test_generated_text_is_never_mined_as_subject_matter() -> None:
    """This module must not feed on its own output.

    The evolution prompt hands back a parent hypothesis this module wrote,
    so without the exclusion the vocabulary compounds on itself and
    produces "Sustained modulation of modulation suppresses conditions".
    """
    rng = random.Random(0)
    generated = leaf_text(rng, 1, "statement", ("resistance", "biofilms"))

    terms = subject_terms(f"Original Hypothesis: {generated}")

    assert not set(terms) & _GENERATED_VOCABULARY


def _openings(templates: tuple[str, ...]) -> set[str]:
    """Every way a family can begin, for the fixed terms below."""
    return {
        f"{filled[:1].upper()}{filled[1:]}"
        for template in templates
        for a, b in (("resistance", "biofilms"), ("biofilms", "resistance"))
        for filled in (template.format(term_a=a, term_b=b),)
    }


@pytest.mark.parametrize(
    ("field", "family", "foreign"),
    [
        ("experimental_context", _EXPERIMENT_TEMPLATES, _CRITIQUE_TEMPLATES),
        ("constructive_feedback", _CRITIQUE_TEMPLATES, _EXPERIMENT_TEMPLATES),
    ],
    ids=["experiment_reads_as_a_protocol", "feedback_reads_as_a_critique"],
)
def test_leaves_vary_by_the_field_they_land_in(
    field: str, family: tuple[str, ...], foreign: tuple[str, ...]
) -> None:
    """One sentence shape across every field renders a run as filler.

    ``_fill_schema`` reaches a title, a mechanism and a reviewer's critique
    through the same code path, so the property name is what distinguishes
    them.

    Asserted as family membership over many draws rather than one phrase at
    one seed. The single-phrase form passed only while that phrase's
    template happened to be the one that seed selected, so widening a family
    broke it without anything being wrong.
    """
    mine, theirs = _openings(family), _openings(foreign)

    for seed in range(200):
        text = leaf_text(
            random.Random(seed), 1, field, ("resistance", "biofilms")
        )
        assert any(text.startswith(opening) for opening in mine), text
        assert not any(text.startswith(opening) for opening in theirs), text


def test_one_goal_yields_many_distinct_token_bags() -> None:
    """A short goal must still give evolution room to differ from its peers.

    The near-duplicate guard compares token *coverage*, so two sentences
    built from the same template with the terms swapped are the same bag of
    words and count as one. That made the reachable count
    ``templates * C(terms, 2)``: measured at 9 bags for the three-term goal
    below, 18 for a four-term goal and 30 for a five-term one. Each evolved
    child is checked against up to fifteen peers, so it had a majority
    chance of matching one and being discarded -- whole offline runs
    finished with every child rejected and no lineage to show, which is
    what a demo renders.

    A short goal is the case that matters, because that is what demos use.
    The floor sits well under what the clause pool actually delivers
    (measured 460 here) so adding a template or a clause can never fail it,
    while removing the independent draw would.

    The end-to-end effect is measured too, at 150 offline runs per arm of
    this goal: the narrow space published no evolved idea in 10 of 150 runs
    and the widened one in 0 of 150 (Fisher one-sided p = 0.0008). That
    comparison is only valid with a cold LLM cache per arm -- run against
    the shared one it reports no difference at all, because the second arm
    is served the first arm's responses. ``tests/test_cache_isolation.py``
    in the app suite is what keeps that from happening silently.
    """
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


@pytest.mark.parametrize(
    ("field", "family"),
    [
        ("go_no_go_recommendation", _GO_NO_GO_TEMPLATES),
        ("time_to_verdict", _TIME_ESTIMATE_TEMPLATES),
        ("time_estimate", _TIME_ESTIMATE_TEMPLATES),
        ("phase_label", _PHASE_LABEL_TEMPLATES),
        ("recommended_idea", _RECOMMENDED_IDEA_TEMPLATES),
    ],
)
def test_standalone_fields_stay_a_short_label(
    field: str, family: tuple[str, ...]
) -> None:
    """The five fields _STANDALONE_TEMPLATES exempts never grow a clause.

    Guards the offline.content fix (docs/decisions/2026-09-02-offline-
    optional-field-reach.md): before it, these fields matched no
    ``_FIELD_TEMPLATES`` fragment, fell through to ``_SUMMARY_TEMPLATES``,
    and grew a trailing ``_SCOPE_CLAUSES`` sentence -- turning "Verdict:"
    or a roadmap phase prefix into a mechanism-argument run-on. Nothing
    else pins the shape: the offline-filler tests that cover these fields
    only assert ``isinstance(str) and truthy``, which the run-on also
    satisfies, so dropping a ``_FIELD_TEMPLATES`` entry or the
    ``_STANDALONE_TEMPLATES`` branch in ``leaf_text`` would regress here
    silently.
    """
    openings = _openings(family)

    for seed in range(50):
        text = leaf_text(
            random.Random(seed), 1, field, ("resistance", "biofilms")
        )
        assert text in openings, text
        assert not any(clause in text for clause in _SCOPE_CLAUSES), text


def test_identical_inputs_are_byte_identical() -> None:
    """The determinism contract the offline router depends on."""
    args = (1, "statement", ("resistance", "biofilms"))

    assert leaf_text(random.Random(7), *args) == leaf_text(
        random.Random(7), *args
    )


async def test_offline_acompletion_sizes_directions_past_the_preview_gate() -> (
    None
):
    """``research_directions`` is sized past the report's preview gate.

    ``report/markdown/overview.py::_render_directions_preview`` renders
    nothing below two named directions, so a single-item array would make
    the overview's preview list silently vanish on every offline run.
    """
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


async def test_offline_acompletion_sizes_unexpected_research_directions() -> (
    None
):
    """``unexpected_research_directions`` is sized past the one-item default.

    Task B: without this hint an offline run's demo would show exactly
    one unexpected direction, from the generic filler's default -- this
    sizes it to the schema's own bound instead, matching MASH's own
    published exemplar (three named bullets).
    """
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
    directions = parsed["unexpected_research_directions"]
    assert len(directions) == 3
    titles = [d["title"] for d in directions]
    assert all(titles)
    assert len(set(titles)) == len(titles)


def _fresh_state(**extra: Any) -> WorkflowState:
    """Build a minimal workflow-state dict for recorder tests."""
    state: dict[str, Any] = {"degraded_nodes": []}
    state.update(extra)
    return cast(WorkflowState, state)


async def test_fallback_records_degradation_into_active_state() -> None:
    """A served fallback appends its schema name to the active state."""
    state = _fresh_state()
    await emit_progress(state, "meta_review_start", "working", 45)

    fallback = get_fallback_response({"name": "meta_review"})

    assert fallback is not None
    assert state["degraded_nodes"] == ["meta_review"]


async def test_degradations_accumulate_in_serve_order() -> None:
    """Repeated degradations append, keeping the order they happened in."""
    state = _fresh_state()
    await emit_progress(state, "phase", "working", 10)

    get_fallback_response({"name": "meta_review"})
    get_fallback_response({"name": "research_overview"})

    assert state["degraded_nodes"] == ["meta_review", "research_overview"]


async def test_fallback_without_active_state_still_serves() -> None:
    """No active state: the fallback is served, nothing is recorded."""
    _ACTIVE_WORKFLOW_STATE.set(None)

    fallback = get_fallback_response({"name": "hypothesis_batch_review"})

    assert fallback == {"reviews": []}


async def test_fallback_records_into_restored_state_lacking_key() -> None:
    """A checkpoint-restored state predating the key still records."""
    state = cast(WorkflowState, {})
    await emit_progress(state, "phase", "working", 10)

    get_fallback_response({"name": "deep_verification"})

    assert state["degraded_nodes"] == ["deep_verification"]


async def test_degradation_emits_progress_event() -> None:
    """A listening progress callback receives a schema_degraded event."""
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
    """A raising progress callback does not disturb fallback service."""

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


def test_critical_node_fallback_records_nothing() -> None:
    """Foundational nodes raise instead of degrading; nothing records."""
    state = _fresh_state()
    _ACTIVE_WORKFLOW_STATE.set(state)

    assert get_fallback_response({"name": "hypothesis_generation"}) is None
    assert state["degraded_nodes"] == []


def test_initial_state_seeds_empty_degraded_nodes() -> None:
    """Every fresh run starts with an empty degraded_nodes list."""
    state = _build_initial_state(
        config_fields={},
        identity=RunIdentity(
            research_goal="goal", start_time=0.0, run_id="run-1"
        ),
        capabilities=RunCapabilities(),
        opts={},
        user_inputs={},
    )

    assert state["degraded_nodes"] == []


def test_streaming_cumulative_state_seeds_degraded_nodes() -> None:
    """The streamed snapshot shape carries the key from the first node."""
    assert _initial_cumulative_stream_state()["degraded_nodes"] == []


def test_generation_result_carries_degraded_nodes() -> None:
    """The non-streaming result dict surfaces the run's degraded nodes."""
    final_state = cast(
        WorkflowState,
        {
            "hypotheses": [],
            "metrics": ExecutionMetrics(),
            "degraded_nodes": ["proximity_analysis"],
        },
    )

    result = _build_generation_result(final_state, execution_time=1.0)

    assert result["degraded_nodes"] == ["proximity_analysis"]


def test_generation_result_defaults_to_empty_degraded_nodes() -> None:
    """A final state without the key yields an empty list, not a KeyError."""
    final_state = cast(
        WorkflowState, {"hypotheses": [], "metrics": ExecutionMetrics()}
    )

    result = _build_generation_result(final_state, execution_time=1.0)

    assert result["degraded_nodes"] == []


def test_durable_commit_captures_recorded_degradation() -> None:
    """The durable path's commit keeps a mid-node fallback recording.

    Mirrors ``task_runtime.execute_task_node``: the node reports progress
    (stashing its state), its LLM call degrades, and the commit copies the
    whole state dict -- so the in-place ``degraded_nodes`` append survives
    into the checkpointed state without the node returning it.
    """
    from co_scientist.task_runtime import apply_task_update

    state = _fresh_state()
    _ACTIVE_WORKFLOW_STATE.set(state)

    get_fallback_response({"name": "meta_review"})
    committed = apply_task_update(state, {"meta_review": {}})

    assert committed["degraded_nodes"] == ["meta_review"]


def test_checkpoint_round_trips_degraded_nodes() -> None:
    """The durable path persists degraded nodes across a checkpoint."""
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

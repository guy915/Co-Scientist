"""Tests for the real-engine final-state drain in engine_adapter.

The drain runs only on the real-engine branch, which the mock-forced test
fixtures never reach. To keep it verifiable without an LLM, the drain is a
module-level helper (`_persist_final_state`) that takes a synthetic final
state and writes hypotheses, evidence, matches, reviews, and the report into
the store. These tests exercise the two canonical-fidelity additions:

- The research overview is written into the report payload and markdown.
- Each hypothesis's deep-verification probes are written into the reviews
  table as ``reviewer_agent="deep_verification"`` rows.
"""
from __future__ import annotations

import asyncio
import sys
import types
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app import engine_adapter, store


def _final_state_with_features() -> dict[str, Any]:
    """Build a synthetic engine final state carrying the new features."""
    return {
        "hypotheses": [
            {
                "text":
                    "Reparixin inhibits CXCR1 to suppress breast cancer "
                    "stem cells.",
                "explanation":
                    "Blocking CXCR1 reduces the stem-cell pool.",
                "literature_grounding":
                    "CXCR1 is enriched in breast CSCs.",
                "experiment":
                    "Treat patient-derived xenografts with reparixin.",
                "elo_rating":
                    1320,
                "win_count":
                    4,
                "loss_count":
                    1,
                "score":
                    0.8,
                "reviews": [],
                "citation_map": {},
                "evolution_history": [],
                "deep_verification_probes": [
                    {
                        "question":
                            "Does CXCR1 signaling drive the stem-cell "
                            "phenotype?",
                        "answer":
                            "Partially; redundant chemokine receptors "
                            "exist.",
                        "reasoning":
                            "CXCR2 can compensate when CXCR1 is blocked.",
                        "assumption_is_fundamental":
                            True,
                    },
                    {
                        "question": "Is reparixin selective for CXCR1?",
                        "answer": "It also antagonizes CXCR2 at high doses.",
                        "reasoning": "Off-target effects may confound.",
                        "assumption_is_fundamental": False,
                    },
                ],
                "deep_verification_verdict":
                    "weakened",
            },
            {
                "text": "A control hypothesis with no probes.",
                "explanation": "",
                "literature_grounding": "",
                "experiment": "",
                "elo_rating": 1180,
                "win_count": 1,
                "loss_count": 3,
                "reviews": [],
                "citation_map": {},
                "evolution_history": [],
                "deep_verification_probes": [],
                "deep_verification_verdict": None,
            },
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {
            "overview": {
                "summary":
                    "Targeting CXCR1 is a promising but redundant pathway.",
                "research_directions": [{
                    "title":
                        "Dual CXCR1/CXCR2 blockade",
                    "importance":
                        "Overcomes compensatory signaling.",
                    "suggested_experiments": [
                        "Combine reparixin with a CXCR2 antagonist.",
                        "Measure CSC frequency by flow cytometry.",
                    ],
                },],
            },
            "nih_specific_aims": {
                "introduction": "Breast cancer stem cells drive recurrence.",
                "aims": [{
                    "aim": "Aim 1: Quantify CXCR1 dependence.",
                    "rationale": "Establish the mechanistic baseline.",
                    "approach": "shRNA knockdown in PDX models.",
                },],
                "impact": "Could yield a combination therapy for TNBC.",
            },
        },
    }


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
                "text": "H1: a mechanistic claim about the pathway.",
                "elo_rating": 1300,
                "win_count": 2,
                "loss_count": 0,
                "evolution_history": [],
            },
            {
                "text": "H2: an evolved variant of the leading claim.",
                "elo_rating": 1250,
                "win_count": 1,
                "loss_count": 1,
                "evolution_history": [{
                    "round": 1
                }],
            },
        ],
        "articles": [{
            "title": "A1",
            "url": "https://example.org/a1"
        }],
        "tournament_matchups": [{
            "hypothesis_a": "H1: a mechanistic claim about the pathway.",
            "hypothesis_b": "H2: an evolved variant of the leading claim.",
            "winner": "a",
        }],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
        "current_iteration": 1,
    }


class _FakeGenerator:
    """Stand-in for the engine's HypothesisGenerator, no LLM required."""

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def generate_hypotheses(  # noqa: D401 - fake
        self,
        *,
        research_goal: str,
        stream: bool,
        run_id: str,
        opts: dict[str, Any] | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        _ = (research_goal, stream, run_id, opts)
        state = _engine_streaming_state()
        for node in _ENGINE_NODES:
            yield node, state


def _drain(gen: AsyncIterator[Any]) -> list[Any]:

    async def _run() -> list[Any]:
        return [e async for e in gen]

    return asyncio.run(_run())


def test_engine_adapter_emits_canonical_event_types(
        isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real-engine branch emits the canonical vocabulary, never engine.*.

    CI only exercises the mock path, so this fake-driven test is the sole guard
    on the node→type mapping and the frontend-facing payload shape.
    """
    # Resolve the lazy ``from co_scientist import HypothesisGenerator`` to the
    # fake regardless of whether the real engine is installed.
    fake_module = types.SimpleNamespace(HypothesisGenerator=_FakeGenerator)
    monkeypatch.setitem(sys.modules, "co_scientist", fake_module)

    run = store.create_run("Canonical vocab goal", "standard", "engine", {})
    events = _drain(
        engine_adapter.run_workflow(
            run.id,
            run.research_goal,
            "standard",
            run.config,
            force_provider="engine",
            sleep_seconds=0,
        ))

    types_emitted = [e["type"] for e in events]

    # No legacy engine.* types leak out of the adapter.
    assert not any(t.startswith("engine.") for t in types_emitted)

    # Every engine node maps to its canonical type.
    for node, expected in _EXPECTED_TYPES.items():
        assert expected in types_emitted, f"{node} -> {expected} missing"

    # Lifecycle + report events remain canonical too.
    assert types_emitted[0] == "status"  # running
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

    # Live standings ride node events for the leaderboard reader.
    assert by_type["ranking"]["leaderboard"]


def test_engine_adapter_generates_canonical_milestones(
        isolated_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Milestone messages are produced from the canonical payload shape."""
    fake_module = types.SimpleNamespace(HypothesisGenerator=_FakeGenerator)
    monkeypatch.setitem(sys.modules, "co_scientist", fake_module)

    run = store.create_run("Milestone goal", "standard", "engine", {})
    _drain(
        engine_adapter.run_workflow(
            run.id,
            run.research_goal,
            "standard",
            run.config,
            force_provider="engine",
            sleep_seconds=0,
        ))

    msgs = store.list_messages(run.id, db_path=isolated_db)
    milestones = [m for m in msgs if m.kind == "milestone"]
    text = " | ".join(m.content for m in milestones)
    assert "Research plan ready" in text
    assert "2 hypotheses generated" in text
    assert "1 matches" in text  # ranking milestone counts len(matches)


def test_persist_writes_research_overview_into_report(isolated_db: str) -> None:
    """The research overview rides the report payload and markdown."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(  # pylint: disable=protected-access
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        final_state=_final_state_with_features(),
        execution_time=1.0,
        db_path=isolated_db,
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    overview = report["payload"].get("research_overview")
    assert overview is not None
    assert overview["overview"]["summary"].startswith("Targeting CXCR1")
    assert overview["nih_specific_aims"]["aims"][0]["aim"].startswith("Aim 1")

    markdown = report["markdown_text"]
    assert "## Research Overview" in markdown
    assert "Dual CXCR1/CXCR2 blockade" in markdown
    assert "Combine reparixin with a CXCR2 antagonist." in markdown
    assert "## NIH Specific Aims" in markdown
    assert "Aim 1: Quantify CXCR1 dependence." in markdown
    assert "Could yield a combination therapy for TNBC." in markdown


def test_persist_writes_deep_verification_reviews(isolated_db: str) -> None:
    """Hypotheses with probes get a deep_verification review row."""
    run = store.create_run("CSC goal", "standard", "engine", {})
    engine_adapter._persist_final_state(  # pylint: disable=protected-access
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        final_state=_final_state_with_features(),
        execution_time=1.0,
        db_path=isolated_db,
    )

    reviews = store.list_reviews(run.id, db_path=isolated_db)
    deep = [r for r in reviews if r["reviewer_agent"] == "deep_verification"]
    # Only the first hypothesis has probes.
    assert len(deep) == 1
    critique = deep[0]["critique"]
    assert "Does CXCR1 signaling drive the stem-cell phenotype?" in critique
    assert "CXCR2 can compensate when CXCR1 is blocked." in critique
    assert "weakened" in deep[0]["summary"].lower(
    ) or "weakened" in critique.lower()
    # Score columns are not produced by deep verification.
    assert deep[0]["novelty"] is None
    assert deep[0]["overall"] is None


def test_persist_handles_missing_research_overview(isolated_db: str) -> None:
    """Older runs without a research overview do not crash or emit a header."""
    state = _final_state_with_features()
    del state["research_overview"]
    run = store.create_run("No overview", "standard", "engine", {})
    engine_adapter._persist_final_state(  # pylint: disable=protected-access
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        final_state=state,
        execution_time=1.0,
        db_path=isolated_db,
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert not report["payload"].get("research_overview")
    assert "## Research Overview" not in report["markdown_text"]
    assert "## NIH Specific Aims" not in report["markdown_text"]


def test_persist_handles_empty_research_overview(isolated_db: str) -> None:
    """An overview with empty sub-dicts emits no empty headers."""
    state = _final_state_with_features()
    state["research_overview"] = {"overview": {}, "nih_specific_aims": {}}
    run = store.create_run("Empty overview", "standard", "engine", {})
    engine_adapter._persist_final_state(  # pylint: disable=protected-access
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        final_state=state,
        execution_time=1.0,
        db_path=isolated_db,
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "## Research Overview" not in report["markdown_text"]
    assert "## NIH Specific Aims" not in report["markdown_text"]

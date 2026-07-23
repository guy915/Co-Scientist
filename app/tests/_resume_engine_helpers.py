"""Shared builders for the real-engine resume test modules.

Not a test module (underscore prefix), so pytest does not collect it. It loads
the engine's LLM fake by file path, installs it, and provides the small
stream/drain/boundary helpers shared across ``test_resume_engine.py``.
"""

from __future__ import annotations

import importlib.util
import pathlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from app import engine_adapter, store
from app.run_modes import resolved_run_config

# Load the engine's LLM fake by file path: it lives under engine/tests, which
# is not importable as a package from the app's own ``tests`` namespace.
_ENGINE_FAKE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "_llm_fake.py"
)


def _load_engine_fake() -> Any:
    spec = importlib.util.spec_from_file_location(
        "engine_llm_fake", _ENGINE_FAKE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_fake_engine_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake the engine's LLM boundary and force literature review off."""
    _load_engine_fake().install_fake_llm(monkeypatch)
    # Hard kill switch: never probe the (possibly live) local MCP server.
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "0")
    # These tests exercise engine resume, not the safety gate; keep the
    # app-level semantic screen offline (it makes a real provider call) so a
    # rate-limited or degraded assessment cannot spuriously hold the run.
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)


def _engine_cfg() -> dict[str, Any]:
    return resolved_run_config(
        {
            "max_iterations": 1,
            "initial_hypotheses_count": 2,
            "evolution_max_count": 2,
            "tournament_pairs": 2,
        }
    )


async def _drain_all(
    gen: AsyncIterator[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [e async for e in gen]


async def _drain_until(
    gen: AsyncIterator[dict[str, Any]],
    predicate: Callable[[list[dict[str, Any]]], bool],
) -> list[dict[str, Any]]:
    """Consume events until ``predicate`` holds, then abandon the stream.

    Abandoning the async generator suspends it permanently (a simulated
    process kill) — no terminal event is emitted, mirroring a crash.
    """
    seen: list[dict[str, Any]] = []
    async for event in gen:
        seen.append(event)
        if predicate(seen):
            break
    return seen


def _engine_stream(
    run_id: str, goal: str, cfg: dict[str, Any], *, resume: bool = False
) -> AsyncIterator[dict[str, Any]]:
    return engine_adapter.run_workflow(
        run_id,
        goal,
        cfg,
        engine_adapter.WorkflowOptions(
            force_provider="engine", sleep_seconds=0, resume=resume
        ),
    )


def _latest_checkpoint(run_id: str) -> dict[str, Any]:
    """Return the run's latest checkpoint, asserting one exists."""
    checkpoint = store.get_latest_checkpoint(run_id)
    assert checkpoint is not None
    return checkpoint


def _assert_published_report(run_id: str) -> dict[str, Any]:
    """Assert a report exists with a populated leaderboard, and return it."""
    report = store.get_latest_report(run_id)
    assert report is not None
    assert report["payload"]["leaderboard"]  # ranked ideas were published
    return report


def _assert_unique_ids(items: list[dict[str, Any]]) -> None:
    """Assert every item carries a distinct id (no duplication)."""
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids))


def _assert_events_unique_and_monotonic(run_id: str) -> None:
    """Assert the run's event seqs are globally unique and sorted."""
    seqs = [e["seq"] for e in store.list_events(run_id)]
    assert len(seqs) == len(set(seqs))
    assert seqs == sorted(seqs)


def _reviewed_boundary(
    run_id: str,
) -> Callable[[list[dict[str, Any]]], bool]:
    """Build a ``_drain_until`` predicate for the engine's resume boundary.

    True once a checkpoint exists whose hypotheses are all reviewed — the
    engine's pre-orchestrator safe-resume boundary.
    """

    def _safe_boundary(_seen: list[dict[str, Any]]) -> bool:
        cp = store.get_latest_checkpoint(run_id)
        if cp is None:
            return False
        hyps = cp["state"].get("state", {}).get("hypotheses", [])
        return bool(hyps) and all(h.get("reviews") for h in hyps)

    return _safe_boundary


def _post_generate_boundary(
    run_id: str,
) -> Callable[[list[dict[str, Any]]], bool]:
    """Build a predicate: checkpoint exists, hypotheses present, none reviewed.

    The post-generate boundary — the model has drafted hypotheses but the
    review node has not run yet.
    """

    def _boundary(_seen: list[dict[str, Any]]) -> bool:
        cp = store.get_latest_checkpoint(run_id)
        if cp is None:
            return False
        hyps = cp["state"].get("state", {}).get("hypotheses", [])
        return bool(hyps) and all(not h.get("reviews") for h in hyps)

    return _boundary

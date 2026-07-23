"""End-to-end proof of the offline-backed real-engine path.

Task 2 adds a working engine+offline backend alongside the mock without
making it the default. This suite drives a ``force_provider="engine"`` run
whose generator is built against the deterministic offline router (the REAL
``HypothesisGenerator``, not a fake stub) and proves it completes with a
persisted report, records ``llm_backend == "offline"``, and never reaches a
real provider -- every LLM call is answered by ``offline_acompletion``.

The recording-stub / router-isolation pattern mirrors the engine's own
``tests/test_offline_llm.py`` end-to-end test, re-homed at the app's shared
``run_workflow`` boundary.
"""

from __future__ import annotations

from typing import Any

import litellm
import pytest
from co_scientist import llm_request, offline_llm

from app import engine_adapter, store
from app.store import RunStatus
from tests._client import drain as _drain


@pytest.fixture(autouse=True)
def _isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the router's install bookkeeping so each test installs fresh.

    ``install_offline_router`` mutates real module attributes directly (not
    through ``monkeypatch``), so recording their current values registers
    them for automatic restoration at teardown, and clearing the idempotency
    flag guarantees this test's ``install_offline_router`` wraps the recording
    stub installed below rather than no-opping over a prior install.
    """
    monkeypatch.setattr(litellm, "acompletion", litellm.acompletion)
    monkeypatch.setattr(
        llm_request,
        "_supports_json_schema_response_format",
        llm_request._supports_json_schema_response_format,
    )
    monkeypatch.setattr(offline_llm, "_installed", False)
    monkeypatch.setattr(offline_llm, "_original_acompletion", None)
    monkeypatch.setattr(offline_llm, "_original_supports_json_schema", None)


def _install_recording_router(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    """Install the offline router wrapping a call-recording original.

    Returns the list every escaped call is appended to; it stays empty when
    nothing bypasses the offline router. A leak is still answered offline so
    it cannot break the run -- recording turns it into an assertion failure
    rather than a silent real request.
    """
    escaped_calls: list[dict[str, Any]] = []

    async def _recording_original(**kwargs: Any) -> Any:
        escaped_calls.append(kwargs)
        return await offline_llm.offline_acompletion(**kwargs)

    monkeypatch.setattr(litellm, "acompletion", _recording_original)
    offline_llm.install_offline_router()
    return escaped_calls


def _persist_offline_run(isolated_db: str) -> tuple[Any, dict[str, Any]]:
    """Persist an offline-backed express run; return the run and its config.

    It carries the default mock provider but is driven on the engine below;
    the engine path keys the generator's model on the ``llm_backend`` column.
    """
    config: dict[str, Any] = {
        "tier": "express",
        "enable_literature_review": False,
    }
    run = store.create_run(
        "Explain how protein X folds under crowding.",
        "express",
        "mock",
        config,
        store.RunCreateOptions(
            client_id="offline-e2e", llm_backend="offline", db_path=isolated_db
        ),
    )
    return run, config


def _drive_offline_engine(
    run: Any, config: dict[str, Any], isolated_db: str
) -> list[dict[str, Any]]:
    """Drive the persisted run on the engine; return its emitted events."""
    return _drain(
        engine_adapter.run_workflow(
            run.id,
            run.research_goal,
            config,
            engine_adapter.WorkflowOptions(
                force_provider="engine", db_path=isolated_db, sleep_seconds=0
            ),
        )
    )


def test_offline_engine_run_completes_without_a_real_call(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A force-engine, offline-backed run finishes offline with a report.

    Records every call the router passes through to the original
    ``acompletion`` so "the run completed" becomes proof that zero calls
    escaped the offline router.
    """
    # The engine event vocabulary is not under test here; keep the app-level
    # semantic screen offline so its real provider call cannot flake the run.
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    escaped_calls = _install_recording_router(monkeypatch)
    run, config = _persist_offline_run(isolated_db)
    events = _drive_offline_engine(run, config, isolated_db)

    assert not escaped_calls, (
        "a call reached the original acompletion instead of the offline "
        f"router: {escaped_calls[0].get('model')!r}"
    )

    # The run finished on the engine and published a report.
    types_emitted = [e["type"] for e in events]
    assert "report" in types_emitted
    final = store.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    assert final.llm_backend == "offline"
    assert store.get_latest_report(run.id, db_path=isolated_db) is not None

    # The offline generator produced real (deterministic) hypotheses.
    hyps = store.list_hypotheses(run.id, db_path=isolated_db)
    assert hyps

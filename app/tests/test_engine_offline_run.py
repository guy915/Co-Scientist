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

    escaped_calls: list[dict[str, Any]] = []

    async def _recording_original(**kwargs: Any) -> Any:
        # Still answered offline so a leak would not break the run; recording
        # it turns a leak into a hard assertion failure rather than a silent
        # real request.
        escaped_calls.append(kwargs)
        return await offline_llm.offline_acompletion(**kwargs)

    monkeypatch.setattr(litellm, "acompletion", _recording_original)
    offline_llm.install_offline_router()

    # Persist an offline-backed run. It carries the default mock provider (the
    # Task 2 default is unchanged) but is driven on the engine below; the
    # engine path keys the generator's model on the ``llm_backend`` column.
    config = {"tier": "express", "enable_literature_review": False}
    run = store.create_run(
        research_goal="Explain how protein X folds under crowding.",
        profile="express",
        provider="mock",
        config=config,
        client_id="offline-e2e",
        llm_backend="offline",
        db_path=isolated_db,
    )

    events = _drain(
        engine_adapter.run_workflow(
            run.id,
            run.research_goal,
            config,
            force_provider="engine",
            db_path=isolated_db,
            sleep_seconds=0,
        )
    )

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

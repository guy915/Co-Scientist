"""Engine-drain tests for contextual safety-verdict escalation (J14).

Covers the drain's wiring of ``hypothesis_safety.escalate_held_hypotheses``
into ``engine_adapter.drain.persist_final_state``: a bulk engine-generated
hypothesis the deterministic screen holds UNCERTAIN now gets the same
contextual-escalation chance a scientist-authored hypothesis already had
(``app.human_input``). These mirror the fail-closed cases already pinned in
``test_hypothesis_safety_escalation.py``, but exercised through the real
drain -- persisted status, audit rows, and transaction boundaries included --
rather than the escalation function in isolation.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.llm import campaign_free_mode

from app import safety, store
from app.engine_adapter.drain import final_state as drain_final_state
from app.execution_policy import scoped_execution_policy
from app.hypothesis_screening import screen_hypotheses
from tests._drain_helpers import _engine_hypothesis, _persist
from tests._process_mode_helpers import FakeProcessMode

# A control-arm hard-split item the deterministic layer holds as UNCERTAIN
# via the benign-context marker check ("triage"/"disaster"), carrying
# needs_context=True -- the only shape escalation acts on. Matches the
# fixture in test_hypothesis_safety_escalation.py.
_HELD_TEXT = (
    "Improving hospital triage protocols and resource allocation for "
    "mass casualty events such as natural disasters."
)


def _escalation_state(held_text: str = _HELD_TEXT) -> dict[str, Any]:
    """A final state with one benign hypothesis and one held UNCERTAIN one."""
    return {
        "hypotheses": [
            _engine_hypothesis(
                "safe-1",
                "Inhibiting kinase X reduces AML growth via apoptosis.",
            ),
            _engine_hypothesis("held-1", held_text),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def _real_run(goal: str) -> store.RunRow:
    """A non-offline engine run: the default backend, eligible to escalate."""
    return store.create_run(goal, "standard", "engine", {})


def _fake_semantic_response(category: str) -> SimpleNamespace:
    """Build a minimal litellm response carrying one safety category."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=f'{{"category":"{category}","reason":"model"}}'
                )
            )
        ]
    )


def _stub_eligible(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """Make every hypothesis-stage escalation eligible to reach the model."""
    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online()


def _held_status(run_id: str, isolated_db: str) -> str:
    """Return the persisted safety_status of the run's held hypothesis."""
    by_id = {
        h["id"]: h for h in store.list_hypotheses(run_id, db_path=isolated_db)
    }
    return str(by_id["held-1"]["safety_status"])


def test_drain_escalates_and_raises_a_held_verdict(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    """The bulk drain path now raises a held UNCERTAIN too (FINDINGS.md J14).

    Not just the scientist-admission path. This is the test that fails on
    the unpatched tree: without wiring escalation into the drain, ``held-1``
    settles at ``uncertain`` no matter what the model would have said.
    """
    import litellm

    async def block_completion(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("prohibited")

    _stub_eligible(monkeypatch, fake_process_mode)
    monkeypatch.setattr(litellm, "acompletion", block_completion)
    run = _real_run("drain escalation raise")

    _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )

    assert _held_status(run.id, isolated_db) == "prohibited"
    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    raised = [
        d
        for d in decisions
        if d["stage"] == "hypothesis" and "prohibited" in d["reason"]
    ]
    assert raised, "expected an audit row recording the escalation's raise"


def test_campaign_scope_reaches_held_hypothesis_executor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real held-hypothesis escalation inherits campaign admission."""
    from app import hypothesis_safety_resolve

    seen: list[bool] = []

    async def resolve(review: Any, *_args: Any, **_kwargs: Any) -> Any:
        seen.append(campaign_free_mode())
        return review

    monkeypatch.setattr(hypothesis_safety_resolve, "resolve_hold", resolve)
    run = _real_run("campaign executor propagation")

    with scoped_execution_policy("campaign"):
        _persist(
            run_id=run.id,
            final_state=_escalation_state(),
            db_path=isolated_db,
        )

    assert seen and all(seen)


def test_rescreen_does_not_downgrade_an_escalation_raised_block(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    """A later whole-pool re-screen must not undo an escalation's raise.

    ``runs.contrib`` re-screens the whole pool whenever a scientist adds
    input. The deterministic layer alone would re-derive UNCERTAIN from
    ``held-1``'s unchanged text and, without ``_STICKY_STATUSES`` covering
    the escalation-raised outcome, silently clear the block back down.
    """
    import litellm

    async def block_completion(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("prohibited")

    _stub_eligible(monkeypatch, fake_process_mode)
    monkeypatch.setattr(litellm, "acompletion", block_completion)
    run = _real_run("drain escalation rescreen")

    _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )
    assert _held_status(run.id, isolated_db) == "prohibited"
    before = store.list_safety_decisions(run.id, db_path=isolated_db)

    # Simulate the scientist-input re-screen: same pool, re-screened.
    second = screen_hypotheses(
        run.id,
        store.list_hypotheses(run.id, db_path=isolated_db),
        db_path=isolated_db,
    )

    assert _held_status(run.id, isolated_db) == "prohibited"
    assert "held-1" in second.blocked_ids
    assert second.escalatable == ()
    after = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert len(after) == len(before), "re-screen must not duplicate audit rows"


def test_drain_escalation_fails_closed_on_missing_credential(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    """A configured-but-unreachable model leaves the hold in place."""
    monkeypatch.setattr(
        safety, "_should_escalate_to_semantic", lambda *a, **k: True
    )
    fake_process_mode.online(credential=False)
    run = _real_run("drain escalation no credential")

    _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )

    assert _held_status(run.id, isolated_db) == "uncertain"


def test_drain_escalation_fails_closed_on_provider_error(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    """A provider failure mid-call leaves the hold in place, not a block."""
    import litellm

    async def raise_completion(**_: object) -> None:
        raise RuntimeError("provider unavailable")

    _stub_eligible(monkeypatch, fake_process_mode)
    monkeypatch.setattr(litellm, "acompletion", raise_completion)
    run = _real_run("drain escalation provider error")

    _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )

    assert _held_status(run.id, isolated_db) == "uncertain"


def test_drain_skips_escalation_cleanly_when_offline(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offline-backed run never reaches the model and still settles.

    No eligibility stubbing here: the run's own persisted ``llm_backend``
    is what ``_should_escalate_to_semantic`` reads, so this exercises the
    real offline gate, not a monkeypatched stand-in for it. The provider
    call is patched to raise if it is ever reached at all, since a real
    offline run must never attempt one.
    """
    import litellm

    async def fail_if_called(**_: object) -> None:
        raise AssertionError("an offline-backed run must never call litellm")

    monkeypatch.setattr(litellm, "acompletion", fail_if_called)
    run = store.create_run(
        "drain escalation offline",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(llm_backend="offline", db_path=isolated_db),
    )

    drained = _persist(
        run_id=run.id, final_state=_escalation_state(), db_path=isolated_db
    )

    # The drain settles cleanly -- the run is not left half-finalized.
    assert drained.safety_counts["screened"] == 2
    assert _held_status(run.id, isolated_db) == "uncertain"


def test_escalation_does_not_hold_the_write_lock(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    """A concurrent write succeeds while escalation is in flight.

    AGENTS.md: nothing may hold SQLite's write lock across network I/O.
    The model call is stalled deliberately; if the drain held the lock
    across it, the concurrent ``create_run`` below would block for the
    busy-timeout instead of returning immediately.
    """
    import litellm

    call_started = threading.Event()
    release_call = threading.Event()

    async def slow_completion(**_: object) -> SimpleNamespace:
        call_started.set()
        assert release_call.wait(timeout=5), "test did not release the call"
        return _fake_semantic_response("allowed")

    _stub_eligible(monkeypatch, fake_process_mode)
    monkeypatch.setattr(litellm, "acompletion", slow_completion)
    run = _real_run("drain escalation lock check")

    errors: list[BaseException] = []

    def _run_drain() -> None:
        try:
            _persist(
                run_id=run.id,
                final_state=_escalation_state(),
                db_path=isolated_db,
            )
        except BaseException as exc:  # surfaced via the assert below
            errors.append(exc)

    worker = threading.Thread(target=_run_drain)
    worker.start()
    try:
        assert call_started.wait(timeout=5), "escalation call never started"
        start = time.monotonic()
        store.create_run(
            "concurrent write during escalation", "standard", "engine", {}
        )
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, (
            "a concurrent write blocked for "
            f"{elapsed:.2f}s -- the write lock is held across the call"
        )
    finally:
        release_call.set()
        worker.join(timeout=5)
    assert not errors, errors


async def test_a_cleared_hold_is_audited_as_an_allow_not_a_block(
    monkeypatch: pytest.MonkeyPatch,
    isolated_db: str,
    fake_process_mode: FakeProcessMode,
) -> None:
    """The audit row must say what happened, not what usually happens.

    The audit recorder wrote a hardcoded ``decision="block"``, which was
    correct while resolution could only raise a verdict. Now that a Tier B
    hold can also be cleared, that hardcoded value would file a block row
    for a hypothesis the same pass published -- and the adjudication UI
    reads these rows, so it would show a reviewer a block that never
    happened.
    """
    import litellm

    _stub_eligible(monkeypatch, fake_process_mode)

    async def _allow(**_: object) -> SimpleNamespace:
        return _fake_semantic_response("allowed")

    monkeypatch.setattr(litellm, "acompletion", _allow)
    run = _real_run("cleared hold audit")

    await drain_final_state.persist_final_state(
        run_id=run.id,
        final_state=_escalation_state(),
        db_path=isolated_db,
    )

    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    held_rows = [
        row
        for row in decisions
        if row["stage"] == "hypothesis" and "uncertain" not in row["reason"]
    ]
    assert held_rows, "the resolution must leave an audit row"
    assert all(row["decision"] == "allow" for row in held_rows), (
        f"a cleared hold was audited as a block: {held_rows}"
    )
